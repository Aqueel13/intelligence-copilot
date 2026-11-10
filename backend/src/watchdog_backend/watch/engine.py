"""The Watch engine: evaluate KPI monitors month by month and maintain alerts.

- Every value comes from the metrics engine (the same numbers as the dashboard and the agent).
- A segment's status for the latest month is ok / warning / critical / insufficient_data.
  "critical" can require several consecutive bad months (policies say "two consecutive
  months"); a single bad month is then a warning.
- Alerts: one open alert per (monitor, segment). It is updated while the condition holds,
  resolved when the segment is back to ok, and left alone when data is insufficient.
"""

import time
from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricQuery, MetricsEngine
from watchdog_backend.domain.pack import current_domain, get_pack, pack_file
from watchdog_backend.lib_format import format_value

Status = Literal["ok", "warning", "critical", "insufficient_data"]


class Monitor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str
    metric: str
    direction: Literal["above", "below"]
    warning: float
    critical: float
    critical_months: int = 1
    filters: dict[str, list[str]] = Field(default_factory=dict)
    group_by: str | None = None
    min_sample: int = 30
    policy_ref: str | None = None
    question: str


@lru_cache
def _monitors(domain: str) -> list[Monitor]:
    raw = yaml.safe_load(pack_file("monitors.yaml", domain=domain).read_text(encoding="utf-8"))[
        "monitors"
    ]
    return [Monitor(id=k, **v) for k, v in raw.items()]


def get_monitors() -> list[Monitor]:
    """The active pack's monitors (cached per pack)."""
    return _monitors(current_domain())


class Point(BaseModel):
    period: str
    value: float | None
    n: int
    status: Status


class Evaluation(BaseModel):
    monitor_id: str
    title: str
    metric: str
    unit: str
    segment: str  # "" for the whole scope, else "dimension=value"
    segment_label: str
    period: str
    value: float | None
    n: int
    status: Status
    threshold: float | None  # the threshold that was crossed (None when ok)
    warning: float
    critical: float
    direction: str
    critical_months: int
    message: str
    policy_ref: str | None
    question: str
    scope: dict[str, list[str]]  # filters an investigation of this alert should use
    series: list[Point]


def _bad(value: float, threshold: float, direction: str) -> bool:
    return value > threshold if direction == "above" else value < threshold


def latest_period(conn: Connection) -> str | None:
    pack = get_pack()
    return conn.execute(
        text(
            "SELECT to_char(max(opened_at AT TIME ZONE :tz), 'YYYY-MM') "
            "FROM operational.cases WHERE domain = :d"
        ),
        {"tz": pack.case.timezone, "d": pack.domain},
    ).scalar_one_or_none()


def evaluate(
    conn: Connection, engine: MetricsEngine, monitor: Monitor, period: str
) -> list[Evaluation]:
    metric = engine.pack.metrics[monitor.metric]
    group = ["month"] + ([monitor.group_by] if monitor.group_by else [])
    result = engine.run(
        conn, MetricQuery(metric=monitor.metric, filters=monitor.filters, group_by=group)
    )

    by_segment: dict[str, list] = {}
    for row in result.rows:
        seg = f"{monitor.group_by}={row.group[monitor.group_by]}" if monitor.group_by else ""
        by_segment.setdefault(seg, []).append(row)

    def point_status(value: float | None, n: int) -> Status:
        if value is None or n < monitor.min_sample:
            return "insufficient_data"
        if _bad(value, monitor.critical, monitor.direction):
            return "critical"
        return "warning" if _bad(value, monitor.warning, monitor.direction) else "ok"

    evaluations = []
    for seg, rows in sorted(by_segment.items()):
        rows.sort(key=lambda r: r.group["month"])
        series = [
            Point(period=r.group["month"], value=r.value, n=r.n, status=point_status(r.value, r.n))
            for r in rows
        ]
        current = next((p for p in series if p.period == period), None)
        label = seg.split("=", 1)[1] if seg else ""
        value, n = (current.value, current.n) if current else (None, 0)
        status: Status = current.status if current else "insufficient_data"
        threshold: float | None = None
        if status == "critical":
            recent = [p for p in series if p.period <= period][-monitor.critical_months :]
            sustained = len(recent) == monitor.critical_months and all(
                p.status == "critical" for p in recent
            )
            if not sustained:
                status = "warning" if _bad(value, monitor.warning, monitor.direction) else "ok"
        if status == "critical":
            threshold = monitor.critical
        elif status == "warning":
            threshold = monitor.warning

        unit = metric.unit
        fmt = lambda v, u=unit: format_value(v, u)  # noqa: E731
        where = f" for {monitor.group_by.replace('_', ' ')} '{label}'" if seg else ""
        if status in ("warning", "critical"):
            sustained_text = (
                f" for {monitor.critical_months} consecutive months"
                if status == "critical" and monitor.critical_months > 1
                else ""
            )
            message = (
                f"{monitor.title}{where} is {fmt(value)} in {period}, "
                f"{monitor.direction} the {status} threshold of {fmt(threshold)}{sustained_text}."
            )
        elif status == "ok":
            message = f"{monitor.title}{where} is {fmt(value)} in {period}: within thresholds."
        else:
            message = f"{monitor.title}{where}: not enough data in {period} (n={n})."

        scope = dict(monitor.filters)
        if seg:
            scope[monitor.group_by] = [label]
        evaluations.append(
            Evaluation(
                monitor_id=monitor.id,
                title=monitor.title,
                metric=monitor.metric,
                unit=unit,
                segment=seg,
                segment_label=label,
                period=period,
                value=value,
                n=n,
                status=status,
                threshold=threshold,
                warning=monitor.warning,
                critical=monitor.critical,
                direction=monitor.direction,
                critical_months=monitor.critical_months,
                message=message,
                policy_ref=monitor.policy_ref,
                question=monitor.question.replace("{segment}", label or "these"),
                # Investigations scope by case dimensions only; event filters stay in the question.
                scope={k: v for k, v in scope.items() if k in _CASE_DIMENSIONS(engine)},
                series=series,
            )
        )
    return evaluations


def _CASE_DIMENSIONS(engine: MetricsEngine) -> set[str]:
    return {d.name for d in engine.dimensions_for("cases")}


class RunSummary(BaseModel):
    period: str | None
    evaluated: int
    opened: int
    updated: int
    resolved: int
    duration_ms: int
    evaluations: list[Evaluation]


def run_monitors(conn: Connection, trigger: str = "manual") -> RunSummary:
    started = time.perf_counter()
    pack = get_pack()
    engine = MetricsEngine(pack)
    period = latest_period(conn)
    if period is None:
        return RunSummary(
            period=None, evaluated=0, opened=0, updated=0, resolved=0, duration_ms=0, evaluations=[]
        )
    evaluations = [e for m in get_monitors() for e in evaluate(conn, engine, m, period)]
    opened = updated = resolved = 0
    for e in evaluations:
        existing = conn.execute(
            text("""SELECT alert_id FROM intelligence.alerts
                    WHERE domain = :d AND monitor_id = :m AND segment = :s
                      AND status <> 'resolved' FOR UPDATE"""),
            {"d": pack.domain, "m": e.monitor_id, "s": e.segment},
        ).scalar_one_or_none()
        if e.status in ("warning", "critical"):
            params = {
                "sev": e.status,
                "v": e.value,
                "t": e.threshold,
                "p": e.period,
                "msg": e.message,
            }
            if existing:
                conn.execute(
                    text("""UPDATE intelligence.alerts
                            SET severity = :sev, value = :v, threshold = :t, last_period = :p,
                                message = :msg, updated_at = now()
                            WHERE alert_id = :id"""),
                    {**params, "id": existing},
                )
                updated += 1
            else:
                conn.execute(
                    text("""INSERT INTO intelligence.alerts
                              (domain, monitor_id, segment, severity, status, value, threshold,
                               first_period, last_period, message)
                            VALUES (:d, :m, :s, :sev, 'open', :v, :t, :p, :p, :msg)"""),
                    {**params, "d": pack.domain, "m": e.monitor_id, "s": e.segment},
                )
                opened += 1
        elif e.status == "ok" and existing:
            conn.execute(
                text("""UPDATE intelligence.alerts
                        SET status = 'resolved', resolved_at = now(), updated_at = now(),
                            message = :msg
                        WHERE alert_id = :id"""),
                {"id": existing, "msg": f"Resolved: {e.message}"},
            )
            resolved += 1
    duration = int((time.perf_counter() - started) * 1000)
    conn.execute(
        text("""INSERT INTO intelligence.monitor_runs
                  (domain, duration_ms, period, trigger, evaluated, opened, updated, resolved)
                VALUES (:d, :ms, :p, :t, :e, :o, :u, :r)"""),
        {
            "d": pack.domain,
            "ms": duration,
            "p": period,
            "t": trigger,
            "e": len(evaluations),
            "o": opened,
            "u": updated,
            "r": resolved,
        },
    )
    conn.commit()
    return RunSummary(
        period=period,
        evaluated=len(evaluations),
        opened=opened,
        updated=updated,
        resolved=resolved,
        duration_ms=duration,
        evaluations=evaluations,
    )

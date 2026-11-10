"""Follow-ups: is each executed action actually moving the metric it was meant to move?

For an executed action, the "effective month" is the first month of data that arrived after it
was executed (here: the first simulated month that had it applied). The action's follow-up
metric is compared before (the 3 months before) vs after (every month since), against the
target from the action catalogue.
"""

from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel
from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricQuery, MetricsEngine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.investigation.actions import get_catalogue
from watchdog_backend.lib_format import format_value

Verdict = Literal["awaiting_data", "on_target", "improving", "no_change", "worse"]


class FollowUp(BaseModel):
    request_id: str
    action_id: str
    title: str
    executed_at: str | None
    metric: str
    unit: str
    target: float
    expect: str
    effective_month: str | None
    before: float | None
    after: float | None
    after_n: int
    verdict: Verdict
    message: str


def _value(conn, engine, metric, filters, start: date | None, end: date | None):
    r = engine.run(
        conn, MetricQuery(metric=metric, filters=filters, period_from=start, period_to=end)
    )
    row = r.rows[0] if r.rows else None
    return (row.value, row.n) if row else (None, 0)


def follow_ups(conn: Connection) -> list[FollowUp]:
    pack = get_pack()
    engine = MetricsEngine(pack)
    catalogue = get_catalogue()
    executed = (
        conn.execute(
            text("""SELECT request_id, action_id, title, executed_at
                FROM operations.action_requests
                WHERE domain = :d AND status = 'executed' ORDER BY executed_at"""),
            {"d": pack.domain},
        )
        .mappings()
        .all()
    )
    out = []
    for req in executed:
        action = catalogue.actions.get(req["action_id"])
        if action is None or action.follow_up is None:
            continue
        f = action.follow_up
        unit = pack.metrics[f.metric].unit
        fmt = lambda v, u=unit: format_value(v, u)  # noqa: E731
        month = conn.execute(
            text("""SELECT min(month) FROM intelligence.simulated_months
                    WHERE domain = :d AND generated_at > :at AND :a = ANY(applied_actions)"""),
            {"d": pack.domain, "at": req["executed_at"], "a": req["action_id"]},
        ).scalar_one_or_none()
        base = dict(
            request_id=str(req["request_id"]),
            action_id=action.id,
            title=action.title,
            executed_at=req["executed_at"].isoformat() if req["executed_at"] else None,
            metric=f.metric,
            unit=unit,
            target=f.target,
            expect=f.expect,
            effective_month=month,
        )
        if month is None:
            out.append(
                FollowUp(
                    **base,
                    before=None,
                    after=None,
                    after_n=0,
                    verdict="awaiting_data",
                    message="No data has arrived since the action was executed.",
                )
            )
            continue
        start = date.fromisoformat(f"{month}-01")
        before, _ = _value(
            conn,
            engine,
            f.metric,
            f.filters,
            start - relativedelta(months=3),
            start - relativedelta(days=1),
        )
        after, n = _value(conn, engine, f.metric, f.filters, start, None)
        better = (lambda a, b: a < b) if f.expect == "below" else (lambda a, b: a > b)
        if after is None:
            verdict: Verdict = "awaiting_data"
        elif better(after, f.target) or after == f.target:
            verdict = "on_target"
        elif (
            before is not None
            and better(after, before)
            and abs(after - before) >= 0.1 * abs(before)
        ):
            verdict = "improving"
        elif (
            before is not None
            and better(before, after)
            and abs(after - before) >= 0.1 * abs(before)
        ):
            verdict = "worse"
        else:
            verdict = "no_change"
        words = {
            "on_target": "on target",
            "improving": "improving but not yet on target",
            "no_change": "no clear change",
            "worse": "worse than before",
            "awaiting_data": "no data yet",
        }
        message = (
            f"{pack.metrics[f.metric].label} {fmt(before)} before → {fmt(after)} since {month} "
            f"(target {'≤' if f.expect == 'below' else '≥'} {fmt(f.target)}): {words[verdict]}."
        )
        out.append(
            FollowUp(
                **base, before=before, after=after, after_n=n, verdict=verdict, message=message
            )
        )
    return out

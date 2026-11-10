"""Metrics engine: compiles a (metric, filters, group_by, period) request into safe SQL.

Safety model:
- Metric expressions and dimension expressions come only from the trusted domain pack or
  from this module. Callers (the UI, the LLM) can only *name* them.
- Every caller-supplied value (filter values, dates) is a bound parameter.
- Unknown metrics, dimensions or values are rejected with a message that lists what is
  allowed, so an LLM caller can correct itself.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from watchdog_backend.domain.pack import Dimension, DomainPack

Base = Literal["cases", "events", "feedback"]

VIEWS: dict[str, str] = {
    "cases": "operational.case_facts",
    "events": "operational.event_facts",
    "feedback": "operational.feedback_facts",
}
LOW_SAMPLE_THRESHOLD = 100
MAX_GROUP_BY = 3
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class MetricQueryError(ValueError):
    """The request is invalid; the message explains what is allowed."""


class MetricQuery(BaseModel):
    metric: str
    filters: dict[str, list[str]] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    period_from: date | None = Field(None, description="FNOL date from (inclusive)")
    period_to: date | None = Field(None, description="FNOL date to (inclusive)")


class MetricRow(BaseModel):
    group: dict[str, str]
    value: float | None
    n: int
    low_sample: bool


class MetricResult(BaseModel):
    metric: str
    label: str
    unit: str
    description: str
    group_by: list[str]
    filters: dict[str, list[str]]
    period_from: date | None
    period_to: date | None
    rows: list[MetricRow]
    sql: str
    params: dict[str, object]


@dataclass(frozen=True)
class DimensionSpec:
    name: str
    label: str
    expression: str
    bases: frozenset[str]
    values: tuple[str, ...] | None  # None = free-form but validated by `pattern`
    pattern: re.Pattern[str] | None = None
    sort_expression: str | None = None  # natural order (bands, weekdays); default: the value

    @property
    def order_by(self) -> str:
        return self.sort_expression or self.expression


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _pack_dimension(d: Dimension, tz: str) -> DimensionSpec:
    all_bases = frozenset(VIEWS)
    if d.source == "attribute":
        return DimensionSpec(
            d.name,
            d.label,
            f"(attributes->>{_literal(d.name)})",
            all_bases,
            tuple(d.values) if d.values else None,
        )
    if d.source == "amount_band":
        bands = d.bands or []
        whens = " ".join(
            f"WHEN amount <= {float(b.max)} THEN {_literal(b.label)}" for b in bands[:-1]
        )
        expr = f"(CASE {whens} ELSE {_literal(bands[-1].label)} END)"
        order_whens = " ".join(
            f"WHEN amount <= {float(b.max)} THEN {i}" for i, b in enumerate(bands[:-1])
        )
        order = f"(CASE {order_whens} ELSE {len(bands) - 1} END)"
        return DimensionSpec(
            d.name, d.label, expr, all_bases, tuple(b.label for b in bands), sort_expression=order
        )
    # opened_month
    expr = f"to_char(opened_at AT TIME ZONE {_literal(tz)}, 'YYYY-MM')"
    return DimensionSpec(d.name, d.label, expr, all_bases, None, _MONTH)


def _builtin_event_dimensions(pack: DomainPack, tz: str) -> list[DimensionSpec]:
    events = frozenset({"events"})
    local_handoff = f"(handoff_at AT TIME ZONE {_literal(tz)})"
    return [
        DimensionSpec(
            "activity", "Activity", "activity", events, tuple(a.name for a in pack.activities)
        ),
        DimensionSpec("resource", "Resource", "resource", events, None, re.compile(r"^.{1,80}$")),
        DimensionSpec(
            "attempt",
            "First attempt or repeat",
            "(CASE WHEN occurrence > 1 THEN 'repeat' ELSE 'first' END)",
            events,
            ("first", "repeat"),
        ),
        DimensionSpec(
            "handoff_weekday",
            "Weekday the work was handed over",
            f"trim(to_char({local_handoff}, 'Dy'))",
            events,
            ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
            sort_expression=f"extract(isodow FROM {local_handoff})",
        ),
        DimensionSpec(
            "handoff_hour",
            "Hour of day the work was handed over (0-23)",
            f"extract(hour FROM {local_handoff})::int::text",
            events,
            tuple(str(h) for h in range(24)),
            sort_expression=f"extract(hour FROM {local_handoff})",
        ),
    ]


class MetricsEngine:
    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack
        ZoneInfo(pack.case.timezone)  # validates the timezone before it is used in SQL
        self.tz = pack.case.timezone
        specs = [_pack_dimension(d, self.tz) for d in pack.dimensions]
        specs += _builtin_event_dimensions(pack, self.tz)
        self.dimensions: dict[str, DimensionSpec] = {s.name: s for s in specs}

    def dimensions_for(self, base: str) -> list[DimensionSpec]:
        return [d for d in self.dimensions.values() if base in d.bases]

    # ------------------------------------------------------------------ build

    def _dimension(self, name: str, base: str, role: str) -> DimensionSpec:
        spec = self.dimensions.get(name)
        if spec is None or base not in spec.bases:
            allowed = ", ".join(d.name for d in self.dimensions_for(base))
            raise MetricQueryError(
                f"Unknown {role} dimension {name!r} for this metric. Allowed: {allowed}"
            )
        return spec

    def build(self, q: MetricQuery) -> tuple[str, dict[str, object]]:
        metric = self.pack.metrics.get(q.metric)
        if metric is None:
            raise MetricQueryError(
                f"Unknown metric {q.metric!r}. Allowed: {', '.join(self.pack.metrics)}"
            )
        if len(q.group_by) > MAX_GROUP_BY:
            raise MetricQueryError(f"At most {MAX_GROUP_BY} group_by dimensions are allowed")
        if len(set(q.group_by)) != len(q.group_by):
            raise MetricQueryError("group_by contains duplicates")
        if q.period_from and q.period_to and q.period_from > q.period_to:
            raise MetricQueryError("period_from is after period_to")

        params: dict[str, object] = {"domain": self.pack.domain}
        where = ["domain = :domain"]
        for i, (name, values) in enumerate(sorted(q.filters.items())):
            spec = self._dimension(name, metric.base, "filter")
            if not values:
                raise MetricQueryError(f"Filter {name!r} needs at least one value")
            for v in values:
                if spec.values is not None and v not in spec.values:
                    raise MetricQueryError(
                        f"Unknown value {v!r} for {name!r}. Allowed: {', '.join(spec.values)}"
                    )
                if spec.pattern is not None and not spec.pattern.match(v):
                    raise MetricQueryError(f"Invalid value {v!r} for {name!r}")
            params[f"f{i}"] = list(values)
            where.append(f"{spec.expression} = ANY(:f{i})")

        local_opened = f"(opened_at AT TIME ZONE {_literal(self.tz)})::date"
        if q.period_from:
            params["period_from"] = q.period_from
            where.append(f"{local_opened} >= :period_from")
        if q.period_to:
            params["period_to"] = q.period_to
            where.append(f"{local_opened} <= :period_to")

        groups = [self._dimension(g, metric.base, "group_by") for g in q.group_by]
        select = [f"{g.expression} AS g{i}" for i, g in enumerate(groups)]
        select += [f"({metric.expression})::float8 AS value", f"{metric.sample} AS n"]
        sql = f"SELECT {', '.join(select)}\nFROM {VIEWS[metric.base]}\nWHERE {' AND '.join(where)}"
        if groups:
            positions = ", ".join(str(i + 1) for i in range(len(groups)))
            order = ", ".join(f"min({g.order_by})" for g in groups)
            sql += f"\nGROUP BY {positions}\nORDER BY {order}"
        return sql, params

    # ---------------------------------------------------------------- execute

    def run(self, conn: Connection, q: MetricQuery) -> MetricResult:
        sql, params = self.build(q)
        metric = self.pack.metrics[q.metric]
        rows = []
        for r in conn.execute(text(sql), params).mappings():
            n = int(r["n"])
            rows.append(
                MetricRow(
                    group={
                        g: "(none)" if r[f"g{i}"] is None else str(r[f"g{i}"])
                        for i, g in enumerate(q.group_by)
                    },
                    value=None if r["value"] is None else float(r["value"]),
                    n=n,
                    low_sample=n < LOW_SAMPLE_THRESHOLD,
                )
            )
        return MetricResult(
            metric=q.metric,
            label=metric.label,
            unit=metric.unit,
            description=metric.description,
            group_by=q.group_by,
            filters=q.filters,
            period_from=q.period_from,
            period_to=q.period_to,
            rows=rows,
            sql=sql,
            params={k: v for k, v in params.items()},
        )

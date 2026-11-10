"""Analysis frames: the scoped event log and case table as pandas DataFrames.

Everything the investigation computes deterministically starts here, so every number can be
traced to the same rows the metrics engine and process mining use.
"""

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricsEngine, _literal
from watchdog_backend.analytics.process import ProcessQuery


@dataclass
class Frames:
    cases: pd.DataFrame  # one row per case, dimensions as columns, outcome flags
    events: pd.DataFrame  # one row per event with wait/work hours and handoff time
    sla_hours: float
    months: float  # length of the period covered, for annualising
    timezone: str


def load_frames(conn: Connection, metrics: MetricsEngine, scope: ProcessQuery) -> Frames:
    pack = metrics.pack
    where, params = metrics.where_clause("cases", scope.filters, scope.period_from, scope.period_to)
    tz = _literal(pack.case.timezone)
    attr_dims = [d.name for d in pack.dimensions if d.source == "attribute"]
    band = metrics.dimensions["amount_band"].expression
    attr_cols = ", ".join(f"attributes->>{_literal(d)} AS {d}" for d in attr_dims)
    cases = pd.read_sql(
        text(f"""
            SELECT case_id, amount, opened_at, closed_at, sla_due_at, cycle_hours, breached,
                   {band} AS amount_band,
                   to_char(opened_at AT TIME ZONE {tz}, 'YYYY-MM') AS month,
                   {attr_cols},
                   coalesce((activity_counts->>'Request Additional Documents')::int, 0)
                       AS doc_requests,
                   coalesce((activity_counts->>'Verification')::int, 0) > 1 AS rework,
                   activity_counts ? 'Senior Approval' AS senior_approval
            FROM operational.case_facts
            WHERE {" AND ".join(where)}
        """),
        conn,
        params=params,
    )
    cases["doc_requested"] = cases["doc_requests"] > 0
    events = pd.read_sql(
        text(f"""
            SELECT case_id, seq, activity, resource, started_at, ended_at, handoff_at,
                   wait_hours, work_hours, occurrence,
                   extract(isodow FROM handoff_at AT TIME ZONE {tz})::int AS handoff_isodow,
                   extract(hour FROM handoff_at AT TIME ZONE {tz})::int AS handoff_hour
            FROM operational.event_facts
            WHERE {" AND ".join(where)}
            ORDER BY case_id, seq
        """),
        conn,
        params=params,
    )
    if len(cases):
        span_days = (cases["opened_at"].max() - cases["opened_at"].min()).days + 1
        months = max(span_days / 30.44, 1.0)
    else:
        months = 1.0
    return Frames(
        cases=cases,
        events=events,
        sla_hours=pack.sla.target_hours,
        months=months,
        timezone=pack.case.timezone,
    )

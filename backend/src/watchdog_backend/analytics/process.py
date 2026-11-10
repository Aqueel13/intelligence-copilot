"""SQL-native process mining: process map (directly-follows graph), variants, activity stats.

Every number is computed in Postgres from `operational.event_facts`. Filters are restricted
to case-level dimensions so that a filter selects whole cases and never cuts a trace.

Definitions (also returned to callers, so the UI and the LLM describe them correctly):
- Waiting time: calendar hours between the previous activity finishing and this one starting.
- Bottleneck: an internal activity whose mean waiting time is at least
  BOTTLENECK_FACTOR times the median of all internal activities' mean waiting times.
- Customer time: duration of activities of kind `customer_wait` (e.g. waiting for the
  customer to send documents). Reported separately: it is not an internal queue.
"""

import statistics
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import LOW_SAMPLE_THRESHOLD, MetricsEngine

BOTTLENECK_FACTOR = 2.0
DEFINITIONS = {
    "waiting_time": "Calendar hours between the previous activity finishing and this one starting.",
    "bottleneck": (
        f"An internal activity whose mean waiting time is at least {BOTTLENECK_FACTOR:g}× the "
        "median of all internal activities' mean waiting times."
    ),
    "customer_time": (
        "Time spent waiting on the customer (e.g. for additional documents). "
        "Reported separately because it is not an internal queue."
    ),
    "variant": "A distinct sequence of activities from start to end of a case.",
}


class ProcessQuery(BaseModel):
    filters: dict[str, list[str]] = Field(default_factory=dict)
    period_from: date | None = None
    period_to: date | None = None


class ProcessNode(BaseModel):
    activity: str
    kind: str
    instances: int
    cases: int
    mean_wait_hours: float
    mean_work_hours: float


class ProcessEdge(BaseModel):
    source: str
    target: str
    transitions: int
    cases: int
    mean_hours: float
    median_hours: float


class ProcessMap(BaseModel):
    cases: int
    start_activities: dict[str, int]
    end_activities: dict[str, int]
    nodes: list[ProcessNode]
    edges: list[ProcessEdge]


class Variant(BaseModel):
    rank: int
    activities: list[str]
    cases: int
    share: float
    mean_cycle_days: float
    breach_rate: float
    low_sample: bool


class VariantSummary(BaseModel):
    cases: int
    distinct_variants: int
    top_variants_share: float
    variants: list[Variant]


class ActivityStats(BaseModel):
    activity: str
    kind: str
    instances: int
    cases: int
    mean_wait_hours: float
    median_wait_hours: float
    p90_wait_hours: float
    total_wait_hours: float
    share_of_internal_wait: float
    mean_work_hours: float
    repeat_rate: float = Field(description="Share of cases with this activity that repeat it")
    breach_rate_with: float = Field(description="SLA breach rate of cases that include it")
    breach_rate_without: float | None = Field(description="Breach rate of cases that don't")
    is_bottleneck: bool


class ActivityAnalysis(BaseModel):
    cases: int
    bottleneck_threshold_hours: float
    internal: list[ActivityStats]
    customer_time: list[ActivityStats]
    definitions: dict[str, str]


class ProcessAnalyzer:
    def __init__(self, metrics: MetricsEngine) -> None:
        self.metrics = metrics
        self.pack = metrics.pack
        self.kinds = {a.name: a.kind for a in self.pack.activities}
        self.order = {a.name: i for i, a in enumerate(self.pack.activities)}
        sla, end = self.pack.sla.start_activity, self.pack.sla.end_activity
        self.boundary = {sla, end}

    def _scope(self, q: ProcessQuery) -> tuple[str, dict[str, object]]:
        where, params = self.metrics.where_clause("cases", q.filters, q.period_from, q.period_to)
        return " AND ".join(where), params

    # ------------------------------------------------------------- process map

    def process_map(self, conn: Connection, q: ProcessQuery) -> ProcessMap:
        where, params = self._scope(q)
        edges_sql = f"""
            WITH ev AS (
                SELECT case_id, seq, activity, started_at, ended_at
                FROM operational.event_facts WHERE {where}
            ), pairs AS (
                SELECT case_id, activity, ended_at,
                       lead(activity)   OVER w AS next_activity,
                       lead(started_at) OVER w AS next_started
                FROM ev WINDOW w AS (PARTITION BY case_id ORDER BY seq)
            )
            SELECT activity AS source, next_activity AS target,
                   count(*) AS transitions, count(DISTINCT case_id) AS cases,
                   avg(extract(epoch FROM next_started - ended_at)) / 3600 AS mean_hours,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY extract(epoch FROM next_started - ended_at)) / 3600 AS median_hours
            FROM pairs WHERE next_activity IS NOT NULL
            GROUP BY 1, 2
        """
        nodes_sql = f"""
            SELECT activity, count(*) AS instances, count(DISTINCT case_id) AS cases,
                   avg(wait_hours) AS mean_wait_hours, avg(work_hours) AS mean_work_hours
            FROM operational.event_facts WHERE {where}
            GROUP BY 1
        """
        bounds_sql = f"""
            SELECT
                (SELECT jsonb_object_agg(activity, n) FROM (
                    SELECT activity, count(*) AS n FROM operational.event_facts
                    WHERE {where} AND seq = 1 GROUP BY 1) s) AS starts,
                (SELECT count(DISTINCT case_id) FROM operational.event_facts WHERE {where}) AS cases
        """
        ends_sql = f"""
            SELECT activity, count(*) AS n FROM (
                SELECT DISTINCT ON (case_id) activity
                FROM operational.event_facts WHERE {where}
                ORDER BY case_id, seq DESC
            ) last_ev GROUP BY 1
        """
        edges = [ProcessEdge(**r) for r in conn.execute(text(edges_sql), params).mappings()]
        nodes = [
            ProcessNode(kind=self.kinds.get(r["activity"], "work"), **r)
            for r in conn.execute(text(nodes_sql), params).mappings()
        ]
        bounds = conn.execute(text(bounds_sql), params).mappings().one()
        ends = {r["activity"]: r["n"] for r in conn.execute(text(ends_sql), params).mappings()}
        nodes.sort(key=lambda n: self.order.get(n.activity, len(self.order)))
        edges.sort(key=lambda e: (self.order.get(e.source, 99), self.order.get(e.target, 99)))
        return ProcessMap(
            cases=bounds["cases"] or 0,
            start_activities=bounds["starts"] or {},
            end_activities=ends,
            nodes=nodes,
            edges=edges,
        )

    # ---------------------------------------------------------------- variants

    def variants(self, conn: Connection, q: ProcessQuery, top: int = 10) -> VariantSummary:
        where, params = self._scope(q)
        sql = f"""
            WITH traces AS (
                SELECT case_id, array_agg(activity ORDER BY seq) AS activities
                FROM operational.event_facts WHERE {where}
                GROUP BY case_id
            ), grouped AS (
                SELECT t.activities, count(*) AS cases,
                       avg(c.cycle_hours) / 24 AS mean_cycle_days,
                       avg(c.breached::int) AS breach_rate
                FROM traces t JOIN operational.case_facts c USING (case_id)
                GROUP BY t.activities
            )
            SELECT activities, cases, mean_cycle_days, breach_rate,
                   sum(cases) OVER () AS total_cases, count(*) OVER () AS distinct_variants
            FROM grouped
            ORDER BY cases DESC, activities
            LIMIT :top
        """
        rows = list(conn.execute(text(sql), {**params, "top": top}).mappings())
        if not rows:
            return VariantSummary(cases=0, distinct_variants=0, top_variants_share=0, variants=[])
        total = int(rows[0]["total_cases"])
        variants = [
            Variant(
                rank=i + 1,
                activities=list(r["activities"]),
                cases=r["cases"],
                share=r["cases"] / total,
                mean_cycle_days=float(r["mean_cycle_days"]),
                breach_rate=float(r["breach_rate"]),
                low_sample=r["cases"] < LOW_SAMPLE_THRESHOLD,
            )
            for i, r in enumerate(rows)
        ]
        return VariantSummary(
            cases=total,
            distinct_variants=int(rows[0]["distinct_variants"]),
            top_variants_share=sum(v.cases for v in variants) / total,
            variants=variants,
        )

    # -------------------------------------------------------------- activities

    def activities(self, conn: Connection, q: ProcessQuery) -> ActivityAnalysis:
        where, params = self._scope(q)
        sql = f"""
            WITH ev AS (
                SELECT * FROM operational.event_facts WHERE {where}
            ), case_flags AS (
                SELECT case_id, closed_at > sla_due_at AS breached
                FROM operational.cases WHERE case_id IN (SELECT case_id FROM ev)
            ), per_case AS (
                SELECT activity, case_id, count(*) AS n FROM ev GROUP BY 1, 2
            ), totals AS (
                SELECT count(*) AS cases, avg(breached::int) AS breach_all,
                       sum(breached::int) AS breached_all
                FROM case_flags
            )
            SELECT
                ev.activity,
                count(*) AS instances,
                count(DISTINCT ev.case_id) AS cases,
                avg(wait_hours) AS mean_wait_hours,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_hours) AS median_wait_hours,
                percentile_cont(0.9) WITHIN GROUP (ORDER BY wait_hours) AS p90_wait_hours,
                sum(wait_hours) AS total_wait_hours,
                avg(work_hours) AS mean_work_hours,
                sum(work_hours) AS total_work_hours,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY work_hours) AS median_work_hours,
                percentile_cont(0.9) WITHIN GROUP (ORDER BY work_hours) AS p90_work_hours,
                (SELECT avg((pc.n > 1)::int) FROM per_case pc
                  WHERE pc.activity = ev.activity) AS repeat_rate,
                (SELECT avg(cf.breached::int) FROM case_flags cf
                  WHERE cf.case_id IN (SELECT case_id FROM per_case pc
                                       WHERE pc.activity = ev.activity)) AS breach_rate_with,
                (SELECT cases FROM totals) AS total_cases,
                (SELECT breached_all FROM totals) AS breached_all
            FROM ev
            GROUP BY ev.activity
        """
        rows = list(conn.execute(text(sql), params).mappings())
        total_cases = int(rows[0]["total_cases"]) if rows else 0

        customer = [r for r in rows if self.kinds.get(r["activity"]) == "customer_wait"]
        internal = [r for r in rows if r not in customer and r["activity"] not in self.boundary]
        internal_wait_total = sum(float(r["total_wait_hours"]) for r in internal) or 1.0
        means = [float(r["mean_wait_hours"]) for r in internal]
        threshold = BOTTLENECK_FACTOR * statistics.median(means) if means else 0.0

        def stats(r, is_customer: bool) -> ActivityStats:
            cases, with_rate = int(r["cases"]), float(r["breach_rate_with"])
            without_n = total_cases - cases
            without = (
                (float(r["breached_all"]) - with_rate * cases) / without_n if without_n else None
            )
            # For customer-wait activities the time that matters is their duration.
            col = "work" if is_customer else "wait"
            wait_mean = float(r[f"mean_{col}_hours"])
            return ActivityStats(
                activity=r["activity"],
                kind=self.kinds.get(r["activity"], "work"),
                instances=int(r["instances"]),
                cases=cases,
                mean_wait_hours=wait_mean,
                median_wait_hours=float(r[f"median_{col}_hours"]),
                p90_wait_hours=float(r[f"p90_{col}_hours"]),
                total_wait_hours=float(r[f"total_{col}_hours"]),
                share_of_internal_wait=0.0
                if is_customer
                else float(r["total_wait_hours"]) / internal_wait_total,
                mean_work_hours=float(r["mean_work_hours"]),
                repeat_rate=float(r["repeat_rate"]),
                breach_rate_with=with_rate,
                breach_rate_without=without,
                is_bottleneck=not is_customer and wait_mean >= threshold,
            )

        by_wait = lambda s: -s.mean_wait_hours  # noqa: E731
        return ActivityAnalysis(
            cases=total_cases,
            bottleneck_threshold_hours=threshold,
            internal=sorted((stats(r, False) for r in internal), key=by_wait),
            customer_time=sorted((stats(r, True) for r in customer), key=by_wait),
            definitions=DEFINITIONS,
        )

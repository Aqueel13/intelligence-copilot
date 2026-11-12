"""Analytics MCP server: lets MCP clients (Claude Desktop, any agent) read the same numbers
the web app shows. Every tool is read-only.

Tools
- list_packs                   the processes (domain packs) this server can answer for
- list_metrics                 governed metric definitions and the dimensions to slice them by
- query_metric                 run a governed metric, optionally filtered and grouped
- process_map                  activities and transitions with volumes and waiting times
- process_variants             the most common paths through the process
- activity_bottlenecks         per-activity work and waiting time, loops, share of breaches
- open_alerts                  the Watch layer's current alerts
- list_investigations          recent investigations with their outcome
- get_investigation_result     one investigation's hypotheses, verdicts, evidence summaries,
                               recommendations and executive summary
- describe_exploration_tables  the tables exploratory SQL may read
- run_exploratory_sql          read-only SQL in the sandbox (clearly not a governed metric)

The numbers come from code (D4): a client gets the same answer as the web app, never a
model's estimate. Tools take an optional `domain` (default: the default pack).
Run: uvicorn watchdog_backend.mcp_servers.analytics:app --host 0.0.0.0 --port 8101
"""

from datetime import date
from typing import Any
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import text

from watchdog_backend.analytics import explore
from watchdog_backend.analytics.metrics import MetricQuery, MetricQueryError, MetricsEngine
from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery
from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import available_domains, get_pack
from watchdog_backend.investigation import service as investigations
from watchdog_backend.mcp_servers.common import READ, build_asgi, call, make_server

PORT = 8101
ERRORS = (MetricQueryError, explore.ExploreError)

server = make_server(
    name="watchdog-analytics",
    title="Intelligence WatchDog: Analytics",
    instructions=(
        "Read-only process analytics for business operations, one domain pack per process "
        "(e.g. insurance_claims, procure_to_pay). Prefer query_metric for KPIs: its metrics "
        "are governed definitions. Use process tools for flow, waiting time and rework, and "
        "investigations for root causes already analysed. run_exploratory_sql is a fallback "
        "for questions no metric covers; say that its results are exploratory."
    ),
    port=PORT,
    scope="analytics",
    tokens=lambda: get_settings().analytics_mcp_tokens,
)


def _scope(filters: dict[str, list[str]] | None, period_from: str | None, period_to: str | None):
    try:
        return ProcessQuery(
            filters=filters or {},
            period_from=date.fromisoformat(period_from) if period_from else None,
            period_to=date.fromisoformat(period_to) if period_to else None,
        )
    except ValueError as exc:
        raise ToolError(f"Dates must be YYYY-MM-DD: {exc}") from exc


@server.tool(annotations=READ)
async def list_packs() -> list[dict[str, str]]:
    """List the processes (domain packs) available, with what each covers."""
    return [
        {
            "domain": d,
            "name": get_pack(d).display_name,
            "subject": get_pack(d).subject,
            "case": get_pack(d).case.label,
        }
        for d in available_domains()
    ]


@server.tool(annotations=READ)
async def list_metrics(domain: str | None = None) -> list[dict[str, Any]]:
    """List a pack's governed metrics, each with the dimensions it can be filtered and grouped
    by (and their allowed values, where fixed)."""

    def work(_conn) -> list[dict[str, Any]]:
        engine = MetricsEngine(get_pack())
        return [
            {
                "metric": m.name,
                "label": m.label,
                "description": m.description,
                "unit": m.unit,
                "dimensions": {
                    d.name: list(d.values) if d.values else None
                    for d in engine.dimensions_for(m.base)
                },
            }
            for m in engine.pack.metrics.values()
        ]

    return await call(work, domain=domain)


@server.tool(annotations=READ)
async def query_metric(
    metric: str,
    filters: dict[str, list[str]] | None = None,
    group_by: list[str] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Compute a governed metric. filters: {dimension: [values]}; group_by: up to three
    dimensions; period_from/period_to: YYYY-MM-DD on the case start date. Rows flagged
    low_sample have too few cases to rely on. The SQL used is returned for transparency."""
    scope = _scope(filters, period_from, period_to)

    def work(conn) -> dict[str, Any]:
        q = MetricQuery(
            metric=metric,
            filters=scope.filters,
            group_by=group_by or [],
            period_from=scope.period_from,
            period_to=scope.period_to,
        )
        return MetricsEngine(get_pack()).run(conn, q).model_dump(mode="json")

    return await call(work, domain=domain, errors=ERRORS)


@server.tool(annotations=READ)
async def process_map(
    filters: dict[str, list[str]] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """The process as a directly-follows graph: activities (cases, mean work and wait hours)
    and transitions (cases, mean hours between), including rework loops."""
    scope = _scope(filters, period_from, period_to)
    return await call(
        lambda conn: (
            ProcessAnalyzer(MetricsEngine(get_pack()))
            .process_map(conn, scope)
            .model_dump(mode="json")
        ),
        domain=domain,
        errors=ERRORS,
    )


@server.tool(annotations=READ)
async def process_variants(
    top: int = 10,
    filters: dict[str, list[str]] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """The most common paths through the process, with their share of cases, mean cycle time
    and breach rate."""
    scope = _scope(filters, period_from, period_to)
    top = max(1, min(top, 50))
    return await call(
        lambda conn: (
            ProcessAnalyzer(MetricsEngine(get_pack()))
            .variants(conn, scope, top)
            .model_dump(mode="json")
        ),
        domain=domain,
        errors=ERRORS,
    )


@server.tool(annotations=READ)
async def activity_bottlenecks(
    filters: dict[str, list[str]] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Per activity: work time, waiting time before it, how often it repeats (rework), and its
    share of SLA breaches. Customer waits are reported separately from internal queues."""
    scope = _scope(filters, period_from, period_to)
    return await call(
        lambda conn: (
            ProcessAnalyzer(MetricsEngine(get_pack()))
            .activities(conn, scope)
            .model_dump(mode="json")
        ),
        domain=domain,
        errors=ERRORS,
    )


@server.tool(annotations=READ)
async def open_alerts(domain: str | None = None) -> list[dict[str, Any]]:
    """The Watch layer's alerts that are not resolved: which KPI breached its threshold, for
    which segment, since when, and the investigation started for it (if any)."""

    def work(conn) -> list[dict[str, Any]]:
        rows = conn.execute(
            text("""SELECT alert_id, monitor_id, segment, severity, status, value, threshold,
                           first_period, last_period, message, investigation_id,
                           triage_status, triage_note
                    FROM intelligence.alerts WHERE domain = :d AND status <> 'resolved'
                    ORDER BY (severity = 'warning'), updated_at DESC"""),
            {"d": get_pack().domain},
        ).mappings()
        return [{k: (str(v) if isinstance(v, UUID) else v) for k, v in r.items()} for r in rows]

    return await call(work, domain=domain)


@server.tool(annotations=READ)
async def list_investigations(limit: int = 20, domain: str | None = None) -> list[dict[str, Any]]:
    """Recent investigations: question, status, how many hypotheses were supported, models."""
    from fastapi.encoders import jsonable_encoder

    limit = max(1, min(limit, 100))
    return await call(
        lambda conn: jsonable_encoder(investigations.list_investigations(conn, limit)),
        domain=domain,
    )


@server.tool(annotations=READ)
async def get_investigation_result(investigation_id: str) -> dict[str, Any]:
    """One investigation: the executive summary, each hypothesis with its verdict, reasoning
    and evidence summaries, and the recommended actions with their estimated impact."""
    try:
        inv_id = UUID(investigation_id)
    except ValueError as exc:
        raise ToolError(f"'{investigation_id}' is not a valid investigation id") from exc

    def work(conn) -> dict[str, Any]:
        row = investigations.get_investigation(conn, inv_id)
        if row is None:
            raise ToolError("Investigation not found")
        result = row["result"] or {}
        return {
            "investigation_id": investigation_id,
            "domain": row["domain"],
            "question": row["question"],
            "scope": row["scope"],
            "status": row["status"],
            "error": row["error"],
            "models": row["models"],
            "summary": result.get("summary"),
            "number_check": result.get("number_check"),
            "overview": result.get("overview"),
            "hypotheses": [
                {
                    "statement": h.get("statement"),
                    "verdict": h.get("verdict"),
                    "confidence": h.get("confidence"),
                    "reasoning": h.get("reasoning"),
                    "override": h.get("override"),
                    "evidence": [e.get("summary") for e in h.get("evidence", [])],
                }
                for h in result.get("hypotheses") or []
            ],
            "recommendations": [
                {
                    "action_id": r.get("action_id"),
                    "title": r.get("title"),
                    "recommended": r.get("recommended"),
                    "rationale": r.get("rationale"),
                    "impact": r.get("impact"),
                    "policy": [p.get("ref") for p in r.get("policy", [])],
                }
                for r in result.get("recommendations") or []
            ],
            "answer": result.get("answer") or result.get("metric_answer"),
        }

    return await call(work)


@server.tool(annotations=READ)
async def describe_exploration_tables(domain: str | None = None) -> str:
    """The tables, columns, attribute keys and activity names run_exploratory_sql can use."""
    return await call(lambda _conn: explore.schema_doc(), domain=domain)


@server.tool(annotations=READ)
async def run_exploratory_sql(sql: str, domain: str | None = None) -> dict[str, Any]:
    """Run one read-only SELECT over the pack's cases, events and feedback tables (see
    describe_exploration_tables). Sandboxed: no other data, 5-second limit, at most 500 rows.
    Results are exploratory, not governed metrics: prefer query_metric when a metric fits."""
    return await call(
        lambda _conn: explore.run(sql).model_dump(mode="json"), domain=domain, errors=ERRORS
    )


def build_app():
    return build_asgi(server, PORT, "analytics-mcp")


app = build_app()

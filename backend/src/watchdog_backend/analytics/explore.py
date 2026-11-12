"""Exploratory SQL: read-only, sandboxed, clearly labelled as not a verified metric.

The metrics layer (D5) answers the questions it was designed for, with definitions an analyst
signed off. Exploration covers the rest: a person (or a model drafting for them) writes a
SELECT over three views of the active pack, and sees the SQL next to the result.

Defences, each enough on its own for most attacks, together for the rest:
1. Validation: one SELECT/WITH statement, no semicolons or comments, no session or
   server-side functions (set_config, pg_sleep, file and large-object access…).
2. It runs as `watchdog_explorer` (SET LOCAL ROLE), a role that can only SELECT the three
   fact views, in a READ ONLY transaction with a statement timeout, wrapped as a subquery
   (so a data-modifying CTE is rejected by Postgres) with a row cap.
3. On its own connection that is closed afterwards (NullPool), so nothing it changes in the
   session can leak into a pooled connection.

`cases`, `events` and `feedback` are the active pack's rows of operational.case_facts,
event_facts and feedback_facts; unqualified names resolve to them first.
"""

import re
import time
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import DomainPack, get_pack

MAX_ROWS = 500
MAX_SQL_CHARS = 4000
TIMEOUT_MS = 5000
ROLE = "watchdog_explorer"

TABLES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "cases": (
        "operational.case_facts",
        [
            ("case_id", "text"),
            ("amount", "numeric, in the pack's currency"),
            ("opened_at", "timestamptz, when the SLA clock starts"),
            ("closed_at", "timestamptz, null while open"),
            ("sla_due_at", "timestamptz"),
            ("attributes", "jsonb, the case dimensions (keys below)"),
            ("cycle_hours", "numeric, opened to closed"),
            ("breached", "boolean, closed after sla_due_at (or still open past it)"),
            ("activity_counts", "jsonb, activity name -> times it happened in the case"),
        ],
    ),
    "events": (
        "operational.event_facts",
        [
            ("event_id", "bigint"),
            ("case_id", "text"),
            ("seq", "integer, order within the case"),
            ("activity", "text (names below)"),
            ("resource", "text, team or person"),
            ("started_at", "timestamptz"),
            ("ended_at", "timestamptz"),
            ("handoff_at", "timestamptz, when the previous activity ended"),
            ("wait_hours", "numeric, handoff_at to started_at"),
            ("work_hours", "numeric, started_at to ended_at"),
            ("occurrence", "bigint, 1 for the first time this activity happens in the case"),
            ("amount", "numeric, the case's amount"),
            ("opened_at", "timestamptz, the case's opened_at"),
            ("attributes", "jsonb, the case's dimensions"),
        ],
    ),
    "feedback": (
        "operational.feedback_facts",
        [
            ("case_id", "text"),
            ("sent_at", "timestamptz, survey sent"),
            ("responded_at", "timestamptz, null if no response"),
            ("responded", "boolean"),
            ("csat", "smallint 1-5"),
            ("nps", "smallint 0-10"),
            ("comment", "text"),
            ("amount", "numeric, the case's amount"),
            ("opened_at", "timestamptz, the case's opened_at"),
            ("attributes", "jsonb, the case's dimensions"),
        ],
    ),
}

_FORBIDDEN = re.compile(
    r"\b(set_config|current_setting|pg_sleep\w*|pg_read\w*|pg_ls\w*|pg_stat_file|lo_\w+|"
    r"dblink\w*|pg_terminate_backend|pg_cancel_backend|pg_advisory\w*|pg_notify|"
    r"pg_reload_conf|pg_rotate_logfile|copy|query_to_xml\w*|table_to_xml\w*|"
    r"cursor_to_xml\w*|database_to_xml\w*|schema_to_xml\w*)\b",
    re.IGNORECASE,
)
_STARTS = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_DOMAIN = re.compile(r"^[a-z][a-z0-9_]*$")


class ExploreError(ValueError):
    """The query was refused or failed; the message says why in plain words."""


class ExploreResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool  # more than MAX_ROWS rows; only the first MAX_ROWS are returned
    duration_ms: int
    label: str = "Exploratory query: not a verified metric definition. Check the SQL."


def validate(sql: str) -> str:
    """Return the query to run, or raise ExploreError explaining what is not allowed."""
    q = sql.strip()
    while q.endswith(";"):
        q = q[:-1].rstrip()
    if not q:
        raise ExploreError("Write a SELECT query.")
    if len(q) > MAX_SQL_CHARS:
        raise ExploreError(f"Queries are limited to {MAX_SQL_CHARS} characters.")
    if ";" in q:
        raise ExploreError("Only one statement is allowed (no semicolons inside the query).")
    if "--" in q or "/*" in q:
        raise ExploreError("Remove the comments from the query.")
    if "$" in q or "\\" in q:
        raise ExploreError("Dollar-quoted strings and backslash escapes are not allowed.")
    if not _balanced(q):
        raise ExploreError("The parentheses in the query do not match.")
    if not _STARTS.match(q):
        raise ExploreError("Only SELECT queries (optionally starting with WITH) are allowed.")
    if m := _FORBIDDEN.search(q):
        raise ExploreError(f"The function or command '{m.group(0)}' is not allowed here.")
    return q


def _balanced(q: str) -> bool:
    """Parentheses outside string literals and quoted identifiers never close more than they
    opened, and end balanced (so the query cannot break out of the subquery it runs in)."""
    depth, quote = 0, ""
    for ch in q:
        if quote:
            if ch == quote:
                quote = ""  # a doubled quote ('it''s') closes and reopens: still correct
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quote


@lru_cache
def _engine() -> Engine:
    # NullPool: every query gets a new connection that is closed afterwards.
    return create_engine(get_settings().database_url, poolclass=NullPool)


def run(sql: str, domain: str | None = None) -> ExploreResult:
    pack = get_pack(domain)
    q = validate(sql)
    if not _DOMAIN.match(pack.domain):  # it is inlined below (no bind parameters, see run)
        raise ExploreError("Invalid pack name")
    d = pack.domain
    ctes = ", ".join(
        f"{name} AS (SELECT * FROM {view} WHERE domain = '{d}')"
        for name, (view, _) in TABLES.items()
    )
    # No bind parameters: user SQL may contain % (LIKE) and :: casts. Without parameters the
    # driver could send several statements, which validate() already rules out.
    wrapped = f"WITH {ctes} SELECT * FROM (\n{q}\n) AS exploration LIMIT {MAX_ROWS + 1}"
    started = time.perf_counter()
    try:
        with _engine().connect() as conn:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
            conn.exec_driver_sql("SET LOCAL lock_timeout = 1000")
            conn.exec_driver_sql("SET LOCAL search_path = pg_catalog")
            conn.exec_driver_sql(f"SET LOCAL ROLE {ROLE}")
            result = conn.exec_driver_sql(wrapped)
            columns = list(result.keys())
            rows = [list(r) for r in result.fetchall()]
            conn.rollback()
    except DBAPIError as exc:
        raise ExploreError(_explain(exc)) from exc
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return ExploreResult(
        sql=q,
        columns=columns,
        rows=[[_plain(v) for v in r] for r in rows],
        row_count=len(rows),
        truncated=truncated,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _plain(v: Any) -> Any:
    """JSON-friendly values (Decimal → float, timestamps → ISO strings)."""
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _explain(exc: DBAPIError) -> str:
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None) or ""
    first = str(orig).strip().splitlines()[0] if orig else str(exc)
    if sqlstate == "57014":
        return f"The query took longer than {TIMEOUT_MS // 1000} s and was stopped."
    if sqlstate == "42501":
        return (
            "Permission denied: exploration can only read the cases, events and feedback "
            f"views. ({first})"
        )
    if sqlstate == "25006":
        return "Exploration is read-only."
    return first


def schema_doc(pack: DomainPack | None = None) -> str:
    """The tables, columns, attribute keys and activity names, as plain text (shown in the UI,
    given to a model drafting SQL, and returned by the MCP tool)."""
    pack = pack or get_pack()
    lines = [
        f"Exploration tables for {pack.display_name} (PostgreSQL; read-only).",
        "",
    ]
    for name, (_, cols) in TABLES.items():
        lines.append(f"{name}:")
        lines.extend(f"  {c}  {desc}" for c, desc in cols)
        lines.append("")
    attrs = [d for d in pack.dimensions if d.source == "attribute"]
    lines.append("attributes keys (read with attributes->>'key'):")
    for d in attrs:
        values = f": {', '.join(d.values)}" if d.values else ""
        lines.append(f"  {d.name} ({d.label}){values}")
    lines.append("")
    lines.append("activities: " + ", ".join(a.name for a in pack.activities))
    lines.append(
        f"SLA: {pack.sla.start_activity} to {pack.sla.end_activity}; "
        f"timestamps are UTC; local business time is {pack.case.timezone} "
        f"(e.g. opened_at AT TIME ZONE '{pack.case.timezone}')."
    )
    return "\n".join(lines)


class Draft(BaseModel):
    sql: str
    explanation: str  # one or two sentences: what the query computes and any caveat


DRAFT_SYSTEM = """You write one PostgreSQL SELECT query over the tables described below to
answer the user's question about {subject}. Rules:
- Use only the tables cases, events and feedback and the columns listed. Read case
  dimensions with attributes->>'key'.
- One statement. No semicolons, comments, dollar quoting or backslashes.
- Aggregate where possible and keep result sets small (at most {max_rows} rows); round rates
  and averages to 1-3 decimals; give columns readable aliases.
- A rate of a boolean is avg(flag::int).
- If the question cannot be answered from these tables, write the closest useful query and
  say what is missing in the explanation.

{schema}"""


def draft(question: str) -> tuple[Draft, str]:
    """Ask the model for a query (not run). Returns (draft, model id)."""
    from watchdog_backend.investigation.llm import structured
    from watchdog_backend.llm.gateway import get_chat_model

    pack = get_pack()
    model, spec = get_chat_model("explorer")
    system = DRAFT_SYSTEM.format(subject=pack.subject, max_rows=MAX_ROWS, schema=schema_doc(pack))
    out = structured(model, Draft, system, question)
    return Draft(sql=out.sql.strip(), explanation=out.explanation.strip()), spec.id

"""Summaries for the Observability page. Platform-wide by default (all packs), optionally one
pack. Percentiles come from Postgres (percentile_cont), never from sampled data."""

from typing import Any

from sqlalchemy import Connection, text

from watchdog_backend.config import get_settings


def _where(hours: int, pack: str | None) -> tuple[str, dict[str, Any]]:
    where = "at >= now() - make_interval(hours => :hours)"
    params: dict[str, Any] = {"hours": hours}
    if pack:
        where += " AND domain = :pack"
        params["pack"] = pack
    return where, params


def _rows(conn: Connection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


_LLM_AGG = """
    count(*) FILTER (WHERE status <> 'cache_hit')                     AS calls,
    count(*) FILTER (WHERE status = 'error')                          AS errors,
    count(*) FILTER (WHERE status = 'cache_hit')                      AS cache_hits,
    coalesce(sum(input_tokens), 0)                                    AS input_tokens,
    coalesce(sum(output_tokens), 0)                                   AS output_tokens,
    coalesce(sum(tokens_saved), 0)                                    AS tokens_saved,
    count(*) FILTER (WHERE tier = 'light' AND status <> 'cache_hit')  AS light_calls,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)
        FILTER (WHERE status = 'ok')                                  AS p50_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
        FILTER (WHERE status = 'ok')                                  AS p95_ms
"""


def summary(conn: Connection, hours: int = 24, pack: str | None = None) -> dict[str, Any]:
    where, p = _where(hours, pack)
    bucket = "hour" if hours <= 72 else "day"
    llm = _rows(conn, f"SELECT {_LLM_AGG} FROM observability.llm_calls WHERE {where}", p)[0]
    by = {
        dim: _rows(
            conn,
            f"SELECT {dim} AS key, {_LLM_AGG} FROM observability.llm_calls WHERE {where} "
            f"GROUP BY {dim} ORDER BY count(*) DESC",
            p,
        )
        for dim in ("model", "role", "purpose", "domain", "tier")
    }
    series = _rows(
        conn,
        f"""SELECT date_trunc('{bucket}', at) AS bucket,
                   count(*) FILTER (WHERE status <> 'cache_hit') AS calls,
                   count(*) FILTER (WHERE status = 'error') AS errors,
                   count(*) FILTER (WHERE status = 'cache_hit') AS cache_hits,
                   coalesce(sum(input_tokens + output_tokens), 0) AS tokens
            FROM observability.llm_calls WHERE {where}
            GROUP BY 1 ORDER BY 1""",
        p,
    )
    api = _rows(
        conn,
        f"""SELECT method || ' ' || route AS key, count(*) AS requests,
                   count(*) FILTER (WHERE status >= 500) AS server_errors,
                   count(*) FILTER (WHERE status BETWEEN 400 AND 499) AS client_errors,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
            FROM observability.api_requests WHERE {where}
            GROUP BY 1 ORDER BY count(*) DESC LIMIT 25""",
        p,
    )
    errors = _rows(
        conn,
        f"""SELECT at, domain, role, model, purpose, investigation_id, error
            FROM observability.llm_calls WHERE {where} AND status = 'error'
            ORDER BY at DESC LIMIT 20""",
        p,
    )
    return {
        "hours": hours,
        "bucket": bucket,
        "llm": llm,
        "by": by,
        "series": series,
        "api": api,
        "errors": errors,
        "quota": quota(conn),
    }


def quota(conn: Connection) -> list[dict[str, Any]]:
    """Free-tier daily token quota per cloud model, over the rolling last 24 hours (Groq's
    limit is per model, per day)."""
    limit = get_settings().groq_daily_token_limit
    rows = _rows(
        conn,
        """SELECT model, coalesce(sum(input_tokens + output_tokens), 0) AS tokens
           FROM observability.llm_calls
           WHERE provider = 'groq' AND at >= now() - interval '24 hours'
           GROUP BY model ORDER BY 2 DESC""",
        {},
    )
    return [{**r, "limit": limit, "share": r["tokens"] / limit if limit else None} for r in rows]


def investigation_calls(conn: Connection, investigation_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """SELECT at, role, model, tier, duration_ms, input_tokens, output_tokens, status,
                  error
           FROM observability.llm_calls WHERE investigation_id = CAST(:id AS uuid)
           ORDER BY at""",
        {"id": investigation_id},
    )


def recent_investigations(conn: Connection, limit: int = 15) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """SELECT i.investigation_id, i.domain, i.question, i.status, i.created_at,
                  i.duration_ms,
                  count(c.call_id) AS llm_calls,
                  coalesce(sum(c.input_tokens + c.output_tokens), 0) AS tokens,
                  count(c.call_id) FILTER (WHERE c.status = 'error') AS errors
           FROM intelligence.investigations i
           LEFT JOIN observability.llm_calls c ON c.investigation_id = i.investigation_id
           GROUP BY i.investigation_id
           ORDER BY i.created_at DESC LIMIT :n""",
        {"n": limit},
    )

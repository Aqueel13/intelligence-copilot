"""Run an investigation, persist it, and stream its progress as Server-Sent Events."""

import json
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.investigation import cache
from watchdog_backend.investigation.graph import Deps, run
from watchdog_backend.knowledge.models import get_reranker
from watchdog_backend.knowledge.service import get_retriever
from watchdog_backend.llm.gateway import get_chat_model, get_light_model

ROLES = ("router", "planner", "assessor", "recommender", "synthesizer", "answer")


def build_deps(conn: Connection, trace: dict[str, str | None] | None = None) -> Deps:
    models = {role: (lambda m: (m[0], m[1].id))(get_chat_model(role)) for role in ROLES}
    models["default"] = models["planner"]
    if light := get_light_model("router"):  # classifying the question is a simple request
        models["router"] = (light[0], light[1].id)
    return Deps(
        conn, MetricsEngine(get_pack()), get_retriever(), get_reranker(), models, trace or {}
    )


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


def current_models() -> dict[str, str]:
    """The model per role an investigation started now would use."""
    models = {role: get_chat_model(role)[1].id for role in ROLES}
    if light := get_light_model("router"):
        models["router"] = light[1].id
    return models


def find_previous_run(
    conn: Connection, question: str, scope: ProcessQuery
) -> tuple[str, dict[str, str], dict[str, Any] | None]:
    """(cache key, models, the latest identical completed run or None)."""
    models = current_models()
    key = cache.cache_key(conn, get_pack().domain, question, scope, models)
    return key, models, cache.find_cached(conn, key)


def stream_investigation(
    question: str,
    scope: ProcessQuery,
    user: dict[str, str | None] | None = None,
    key: str | None = None,
) -> Iterator[str]:
    """Generator for a StreamingResponse. Uses its own connections (it outlives the request)."""
    engine = get_engine()
    domain = get_pack().domain
    started = time.perf_counter()
    user_id = (user or {}).get("user_id")
    with engine.begin() as conn:
        deps_models = current_models()
        inv_id = conn.execute(
            text("""
                INSERT INTO intelligence.investigations
                    (domain, question, scope, status, models, cache_key, user_id)
                VALUES (:d, :q, CAST(:s AS jsonb), 'running', CAST(:m AS jsonb), :k, :u)
                RETURNING investigation_id
            """),
            {
                "d": domain,
                "q": question,
                "s": scope.model_dump_json(),
                "m": json.dumps(deps_models),
                "k": key,
                "u": user_id,
            },
        ).scalar_one()
    yield _sse("start", {"id": str(inv_id), "models": deps_models})

    state: dict[str, Any] = {"question": question, "scope": scope.model_dump(mode="json")}
    events: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            trace = {"purpose": "investigation", "investigation_id": str(inv_id), **(user or {})}
            for node, update in run(build_deps(conn, trace), question, scope):
                state.update(update)
                events.append(jsonable_encoder({"node": node, "update": update}))
                yield _sse("step", events[-1])
        result = jsonable_encoder({k: v for k, v in state.items() if k not in ("question",)})
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE intelligence.investigations
                    SET status = 'completed', route = :route, result = CAST(:r AS jsonb),
                        events = CAST(:ev AS jsonb), completed_at = now(), duration_ms = :ms
                    WHERE investigation_id = :id
                """),
                {
                    "id": inv_id,
                    "route": state.get("route"),
                    "r": json.dumps(result),
                    "ev": json.dumps(events),
                    "ms": int((time.perf_counter() - started) * 1000),
                },
            )
        yield _sse("done", {"id": str(inv_id)})
    except Exception as exc:  # report every failure to the client and record it
        message = str(exc)[:500]
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE intelligence.investigations
                    SET status = 'failed', error = :e, completed_at = now(), duration_ms = :ms
                    WHERE investigation_id = :id
                """),
                {"id": inv_id, "e": message, "ms": int((time.perf_counter() - started) * 1000)},
            )
        yield _sse("error", {"id": str(inv_id), "message": message})


def replay_investigation(
    record: dict[str, Any],
    *,
    speed: float,
    min_delay: float = 0.05,
    max_delay: float = 2.5,
    cached: bool = False,
) -> Iterator[str]:
    """Play a recorded run back as the same SSE events, without calling a model. `start`
    carries `replay: true` (and `cached: true` for a cache hit) and when the run was made."""
    yield _sse(
        "start",
        {
            "id": str(record["investigation_id"]),
            "models": record["models"],
            "replay": True,
            "cached": cached,
            "recorded_at": record["completed_at"],
        },
    )
    for delay, event in cache.replay_steps(record["events"] or [], speed, min_delay, max_delay):
        time.sleep(delay)
        yield _sse("step", event)
    yield _sse("done", {"id": str(record["investigation_id"])})


def set_showcase(conn: Connection, inv_id: UUID, on: bool) -> bool:
    """Mark or unmark a completed, replayable run. False if there is no such run."""
    return (
        conn.execute(
            text("""UPDATE intelligence.investigations SET showcase = :on
                    WHERE investigation_id = :id AND domain = :d AND status = 'completed'
                      AND events IS NOT NULL"""),
            {"id": inv_id, "on": on, "d": get_pack().domain},
        ).rowcount
        == 1
    )


def get_investigation(conn: Connection, inv_id: UUID) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("SELECT * FROM intelligence.investigations WHERE investigation_id = :id"),
            {"id": inv_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def list_investigations(
    conn: Connection, limit: int = 20, showcase_only: bool = False
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(f"""
            SELECT investigation_id, question, status, route, models, created_at, duration_ms,
                   error, showcase, events IS NOT NULL AS replayable,
                   (SELECT count(*) FROM jsonb_array_elements(coalesce(result->'hypotheses',
                       '[]'::jsonb)) h WHERE h->>'verdict' = 'supported') AS supported
            FROM intelligence.investigations
            WHERE domain = :d {"AND showcase" if showcase_only else ""}
            ORDER BY created_at DESC LIMIT :n
        """),
        {"d": get_pack().domain, "n": limit},
    ).mappings()
    return [dict(r) for r in rows]

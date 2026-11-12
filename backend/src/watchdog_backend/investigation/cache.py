"""Investigation cache and replay.

A completed investigation keeps the stream it produced, so it can be played back step by step
without a model call. Two uses:

- **Cache hit.** An identical request (same normalised question, scope and models, on the same
  data, documents and pack configuration) replays the latest completed run instead of spending
  tokens again. Anything the result depends on is in the key, so changing the data (a new
  simulated month, `make seed`), a policy document or the pack's YAML misses the cache.
- **Showcase.** An admin marks good runs; anyone, including a read-only viewer, can replay them
  at a watchable pace. This is how a public demo survives free-tier model limits.
"""

import hashlib
import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import Connection, text

from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.domain.pack import pack_file
from watchdog_backend.knowledge.cache import corpus_version, normalise
from watchdog_backend.observability.recorder import record

# Bump when a code change alters what an investigation produces for the same inputs.
ENGINE_VERSION = 2  # 2: D54-D55 rules and the annualisation basis (D57)


def data_version(conn: Connection, domain: str) -> str:
    """Changes when the pack's case data does (regenerated, or a simulated month appended)."""
    return conn.execute(
        text("""SELECT md5(concat_ws('|', count(*), sum(amount), min(opened_at), max(opened_at),
                                      max(closed_at)))
                FROM operational.cases WHERE domain = :d"""),
        {"d": domain},
    ).scalar_one()


def pack_version(domain: str) -> str:
    """Hash of the pack's configuration files (analysis settings, metrics, action catalogue)."""
    digest = hashlib.sha256()
    for path in sorted(pack_file(domain=domain).glob("*.yaml")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def cache_key(
    conn: Connection, domain: str, question: str, scope: ProcessQuery, models: dict[str, str]
) -> str:
    parts = {
        "engine": ENGINE_VERSION,
        "domain": domain,
        "question": normalise(question),
        "scope": scope.model_dump(mode="json"),
        "models": models,
        "data": data_version(conn, domain),
        "corpus": corpus_version(conn, domain),
        "pack": pack_version(domain),
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def find_cached(conn: Connection, key: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text("""SELECT investigation_id, question, models, events, completed_at
                    FROM intelligence.investigations
                    WHERE cache_key = :k AND status = 'completed' AND events IS NOT NULL
                    ORDER BY completed_at DESC LIMIT 1"""),
            {"k": key},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def tokens_spent(conn: Connection, investigation_id: Any) -> int:
    """What the original run cost, from observability (kept 30 days; 0 if pruned)."""
    return conn.execute(
        text("""SELECT coalesce(sum(input_tokens + output_tokens), 0)
                FROM observability.llm_calls
                WHERE investigation_id = :id AND status <> 'cache_hit'"""),
        {"id": investigation_id},
    ).scalar_one()


def record_hit(conn: Connection, domain: str, cached: dict[str, Any], user_id: str | None) -> None:
    model = cached["models"].get("planner") or next(iter(cached["models"].values()), "unknown")
    record(
        "llm_calls",
        {
            "domain": domain,
            "role": "investigation",
            "model": model,
            "provider": model.split(":", 1)[0],
            "tier": "cache",
            "purpose": "investigation",
            "investigation_id": str(cached["investigation_id"]),
            "user_id": user_id,
            "duration_ms": 0,
            "status": "cache_hit",
            "tokens_saved": tokens_spent(conn, cached["investigation_id"]),
        },
    )


def replay_steps(
    events: list[dict[str, Any]], speed: float, min_delay: float, max_delay: float
) -> Iterator[tuple[float, dict[str, Any]]]:
    """(seconds to wait before it, event) for each recorded step. The wait is the step's
    original duration divided by `speed`, clamped, so a two-minute run replays in seconds
    while still showing its progress."""
    for event in events:
        steps = (event.get("update") or {}).get("steps") or []
        ms = steps[-1].get("ms", 0) if steps else 0
        yield min(max_delay, max(min_delay, ms / 1000 / speed)), event

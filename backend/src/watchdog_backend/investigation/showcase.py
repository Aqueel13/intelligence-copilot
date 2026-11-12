"""Move showcase runs between databases (local machine → public deployment).

A showcase run is a recorded investigation anyone can replay without a model call (D48).
They are made locally, where the model is free, and shipped with the code: `export` writes
every showcase run to a JSON file that is committed; `import` loads it into another database.

Safeguards:
- A showcase run describes one dataset. The file records each pack's data fingerprint, and
  `import` refuses a database whose data differs (its replays would cite numbers that are not
  there) unless forced. Load the same data first (`make seed`, seed 42).
- Runs keep their ids, so links to them stay valid; importing twice updates, never duplicates.
- Imported runs get no cache key: they replay as showcase runs but never stand in for a fresh
  investigation, whose engine or models may differ on the target.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from watchdog_backend import __version__
from watchdog_backend.domain.pack import available_domains
from watchdog_backend.investigation.cache import data_version

FORMAT = 1
DEFAULT_FILE = Path(__file__).resolve().parents[4] / "showcase" / "showcase_runs.json"
IMPORTED_BY = "showcase-import"
COLUMNS = (
    "investigation_id",
    "question",
    "scope",
    "route",
    "models",
    "result",
    "events",
    "duration_ms",
    "created_at",
    "completed_at",
)


class ShowcaseError(ValueError):
    pass


def export_runs(conn: Connection) -> dict[str, Any]:
    packs: dict[str, Any] = {}
    for domain in available_domains():
        rows = conn.execute(
            text(f"""SELECT {", ".join(COLUMNS)} FROM intelligence.investigations
                     WHERE domain = :d AND showcase AND status = 'completed'
                       AND events IS NOT NULL
                     ORDER BY created_at"""),
            {"d": domain},
        ).mappings()
        runs = [
            {
                **dict(r),
                "investigation_id": str(r["investigation_id"]),
                "created_at": r["created_at"].isoformat(),
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ]
        if runs:
            packs[domain] = {"data_version": data_version(conn, domain), "runs": runs}
    return {
        "format": FORMAT,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": __version__,
        "packs": packs,
    }


def write_export(conn: Connection, path: Path) -> dict[str, int]:
    doc = export_runs(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact: the file is generated, and runs carry their whole recorded stream.
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(body + "\n", encoding="utf-8")
    return {d: len(p["runs"]) for d, p in doc["packs"].items()}


def import_runs(conn: Connection, doc: dict[str, Any], force: bool = False) -> dict[str, int]:
    """Load the runs; returns how many per pack. Raises ShowcaseError, changing nothing, if a
    pack is unknown here or its data differs (unless `force`)."""
    if doc.get("format") != FORMAT:
        raise ShowcaseError(f"Unsupported file format {doc.get('format')!r} (expected {FORMAT})")
    packs = doc.get("packs") or {}
    enabled = set(available_domains())
    problems = []
    for domain, pack in packs.items():
        if domain not in enabled:
            problems.append(f"{domain}: pack not enabled here")
        elif not force and pack["data_version"] != data_version(conn, domain):
            problems.append(
                f"{domain}: this database holds different {domain} data than the runs were "
                "recorded on (load the same dataset, e.g. `make seed`, or use --force)"
            )
    if problems:
        raise ShowcaseError("; ".join(problems))
    counts: dict[str, int] = {}
    for domain, pack in packs.items():
        for run in pack["runs"]:
            conn.execute(
                text("""
                    INSERT INTO intelligence.investigations
                      (investigation_id, domain, question, scope, status, route, models,
                       result, events, duration_ms, created_at, completed_at, user_id,
                       showcase, cache_key)
                    VALUES (:id, :d, :q, CAST(:scope AS jsonb), 'completed', :route,
                            CAST(:models AS jsonb), CAST(:result AS jsonb),
                            CAST(:events AS jsonb), :ms, :created, :completed, :by, true, NULL)
                    ON CONFLICT (investigation_id) DO UPDATE SET
                      domain = EXCLUDED.domain, question = EXCLUDED.question,
                      scope = EXCLUDED.scope, status = 'completed', route = EXCLUDED.route,
                      models = EXCLUDED.models, result = EXCLUDED.result,
                      events = EXCLUDED.events, duration_ms = EXCLUDED.duration_ms,
                      completed_at = EXCLUDED.completed_at, showcase = true
                """),
                {
                    "id": run["investigation_id"],
                    "d": domain,
                    "q": run["question"],
                    "scope": json.dumps(run["scope"]),
                    "route": run["route"],
                    "models": json.dumps(run["models"]),
                    "result": json.dumps(run["result"]),
                    "events": json.dumps(run["events"]),
                    "ms": run["duration_ms"],
                    "created": run["created_at"],
                    "completed": run["completed_at"],
                    "by": IMPORTED_BY,
                },
            )
        counts[domain] = len(pack["runs"])
    return counts


def read_import(conn: Connection, path: Path, force: bool = False) -> dict[str, int]:
    return import_runs(conn, json.loads(path.read_text(encoding="utf-8")), force=force)

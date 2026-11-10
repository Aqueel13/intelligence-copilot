"""Write observability records off the request path: a queue drained by one daemon thread in
small batches. Losing a few records on a crash is acceptable; slowing a request is not."""

import logging
import queue
import threading
import time
from typing import Any

from sqlalchemy import text

log = logging.getLogger("watchdog.observability")

_TABLES = {
    "llm_calls": (
        "domain",
        "role",
        "model",
        "provider",
        "tier",
        "purpose",
        "investigation_id",
        "user_id",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "status",
        "error",
        "tokens_saved",
    ),
    "api_requests": ("method", "route", "status", "duration_ms", "domain", "user_id"),
}
# Values for NOT NULL columns a caller may leave out (a cache hit has no token counts).
_DEFAULTS = {"input_tokens": 0, "output_tokens": 0, "tokens_saved": 0, "duration_ms": 0}
RETENTION_DAYS = 30

_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=10_000)
_lock = threading.Lock()
_thread: threading.Thread | None = None
_enabled = True


def set_enabled(on: bool) -> None:
    """Tests that do not exercise observability can switch recording off."""
    global _enabled
    _enabled = on


def record(table: str, row: dict[str, Any]) -> None:
    if not _enabled:
        return
    cols = _TABLES[table]
    try:
        _queue.put_nowait((table, {c: row.get(c, _DEFAULTS.get(c)) for c in cols}))
    except queue.Full:  # never block the caller
        return
    _ensure_thread()


def _ensure_thread() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="observability-writer", daemon=True)
            _thread.start()


def _drain(max_items: int = 500) -> list[tuple[str, dict[str, Any]]]:
    items = []
    while len(items) < max_items:
        try:
            items.append(_queue.get_nowait())
        except queue.Empty:
            break
    return items


def _write(items: list[tuple[str, dict[str, Any]]]) -> None:
    from watchdog_backend.db import get_engine

    by_table: dict[str, list[dict[str, Any]]] = {}
    for table, row in items:
        by_table.setdefault(table, []).append(row)
    with get_engine().begin() as conn:
        for table, rows in by_table.items():
            cols = _TABLES[table]
            conn.execute(
                text(
                    f"INSERT INTO observability.{table} ({', '.join(cols)}) "
                    f"VALUES ({', '.join(':' + c for c in cols)})"
                ),
                rows,
            )


def _prune() -> None:
    from watchdog_backend.db import get_engine

    with get_engine().begin() as conn:
        for table in _TABLES:
            conn.execute(
                text(
                    f"DELETE FROM observability.{table} "
                    f"WHERE at < now() - make_interval(days => {RETENTION_DAYS})"
                )
            )


def _run() -> None:
    last_prune = 0.0
    while True:
        first = _queue.get()  # block until there is work
        items = [first, *_drain()]
        try:
            _write(items)
            if time.monotonic() - last_prune > 3600:
                _prune()
                last_prune = time.monotonic()
        except Exception as exc:  # the database may be migrating or down: drop, don't crash
            log.warning("dropped %d observability records: %s", len(items), str(exc)[:200])
        time.sleep(0.2)  # batch whatever arrives meanwhile


def flush(timeout: float = 5.0) -> None:
    """Write everything queued so far (tests, CLI exit)."""
    items = _drain(10_000)
    if items:
        _write(items)
    deadline = time.monotonic() + timeout
    while not _queue.empty() and time.monotonic() < deadline:
        time.sleep(0.05)

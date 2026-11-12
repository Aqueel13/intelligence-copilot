"""In-memory cache for the process-mining endpoints (map, variants, activities).

These read every event of a pack through `event_facts` and take tens of seconds on a small
server, while their inputs only change when the data does. A result is kept per pack, scope
and endpoint, keyed on the same data fingerprint and pack-configuration hash as the
investigation cache: regenerating the data, appending a simulated month or editing the pack's
YAML misses it. The fingerprint is re-read at most every DATA_VERSION_TTL seconds, so new
data shows up within that time.

One lock per key: concurrent identical requests (the Overview and Process pages ask for the
same activities) compute once and share the result.
"""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from pydantic import BaseModel
from sqlalchemy import Connection

from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery
from watchdog_backend.investigation.cache import data_version, pack_version

log = logging.getLogger(__name__)

MAX_ENTRIES = 256  # results are a few KB each
DATA_VERSION_TTL = 30.0

_results: OrderedDict[str, BaseModel] = OrderedDict()
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_versions: dict[str, tuple[float, str]] = {}


def _version(conn: Connection, domain: str) -> str:
    now = time.monotonic()
    with _guard:
        hit = _versions.get(domain)
    if hit and now - hit[0] < DATA_VERSION_TTL:
        return hit[1]
    version = f"{data_version(conn, domain)}:{pack_version(domain)}"
    with _guard:
        _versions[domain] = (now, version)
    return version


def cached[T: BaseModel](
    conn: Connection, domain: str, kind: str, q: ProcessQuery, compute: Callable[[], T]
) -> T:
    key = f"{domain}|{kind}|{q.model_dump_json()}|{_version(conn, domain)}"
    with _guard:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]  # type: ignore[return-value]
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        with _guard:
            if key in _results:  # computed by the request we waited for
                return _results[key]  # type: ignore[return-value]
        try:
            result = compute()
            with _guard:
                _results[key] = result
                while len(_results) > MAX_ENTRIES:
                    _results.popitem(last=False)
        finally:
            with _guard:
                _locks.pop(key, None)
        return result


def clear() -> None:
    with _guard:
        _results.clear()
        _versions.clear()


def warm(conn: Connection, analyzer: ProcessAnalyzer, domain: str) -> None:
    """Compute the default (unfiltered, all-time) view, as the pages first ask for it."""
    q = ProcessQuery()
    started = time.monotonic()
    cached(conn, domain, "activities", q, lambda: analyzer.activities(conn, q))
    cached(conn, domain, "map", q, lambda: analyzer.process_map(conn, q))
    cached(conn, domain, "variants:10", q, lambda: analyzer.variants(conn, q, 10))
    log.info("Process cache warm for %s in %.1fs", domain, time.monotonic() - started)

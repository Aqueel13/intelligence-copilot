"""Process cache: computes once per scope and data version, and once under concurrency."""

import threading
import time
from datetime import date

import pytest

from watchdog_backend.analytics import process_cache
from watchdog_backend.analytics.process import ActivityAnalysis, ProcessQuery


@pytest.fixture
def versions(monkeypatch):
    """Stand-in data fingerprint the test can change; re-read on every call."""
    current = {"v": "a"}
    monkeypatch.setattr(process_cache, "data_version", lambda conn, domain: current["v"])
    monkeypatch.setattr(process_cache, "pack_version", lambda domain: "p")
    monkeypatch.setattr(process_cache, "DATA_VERSION_TTL", 0.0)
    return current


def _counting(calls: list[int], delay: float = 0.0):
    def compute() -> ActivityAnalysis:
        time.sleep(delay)
        calls.append(1)
        return ActivityAnalysis(
            cases=len(calls),
            bottleneck_threshold_hours=0,
            internal=[],
            customer_time=[],
            definitions={},
        )

    return compute


def test_hit_until_scope_or_data_changes(versions) -> None:
    calls: list[int] = []
    q = ProcessQuery()
    first = process_cache.cached(None, "d", "activities", q, _counting(calls))
    assert process_cache.cached(None, "d", "activities", ProcessQuery(), _counting(calls)) is first
    assert len(calls) == 1

    scoped = ProcessQuery(period_from=date(2025, 4, 1))
    process_cache.cached(None, "d", "activities", scoped, _counting(calls))
    process_cache.cached(None, "other", "activities", q, _counting(calls))
    process_cache.cached(None, "d", "map", q, _counting(calls))
    assert len(calls) == 4

    versions["v"] = "b"  # data reloaded
    assert process_cache.cached(None, "d", "activities", q, _counting(calls)) is not first
    assert len(calls) == 5


def test_concurrent_identical_requests_compute_once(versions) -> None:
    calls: list[int] = []
    results = []

    def request() -> None:
        results.append(
            process_cache.cached(None, "d", "activities", ProcessQuery(), _counting(calls, 0.2))
        )

    threads = [threading.Thread(target=request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert all(r is results[0] for r in results)


def test_errors_are_not_cached(versions) -> None:
    def boom() -> ActivityAnalysis:
        raise ValueError("bad scope")

    with pytest.raises(ValueError):
        process_cache.cached(None, "d", "activities", ProcessQuery(), boom)
    calls: list[int] = []
    process_cache.cached(None, "d", "activities", ProcessQuery(), _counting(calls))
    assert calls == [1]

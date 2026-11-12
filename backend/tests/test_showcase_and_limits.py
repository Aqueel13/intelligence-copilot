"""Investigation cache, showcase replay and rate limits (scripted model, no LLM server)."""

import json
from typing import Any

import pytest
from sqlalchemy import text

from tests.test_investigation_graph import _model
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.config import get_settings
from watchdog_backend.investigation import cache
from watchdog_backend.observability.recorder import flush


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        (block.split("\n")[0][7:], json.loads(block.split("\n")[1][6:]))
        for block in body.strip().split("\n\n")
    ]


@pytest.fixture
def scripted(monkeypatch, kb):
    from watchdog_backend.api import investigations as api
    from watchdog_backend.investigation import service
    from watchdog_backend.llm.gateway import ModelSpec

    model = _model()
    fake = lambda role: (model, ModelSpec("ollama", "scripted"))  # noqa: E731
    monkeypatch.setattr(service, "get_chat_model", fake)
    monkeypatch.setattr(api, "get_chat_model", fake)
    return model


def _investigate(client, question: str, **extra: Any):
    return client.post(
        "/api/investigations/stream",
        json={"question": question, "scope": {"filters": {"channel": ["agent"]}}, **extra},
    )


def test_identical_request_is_replayed_from_the_cache(scripted, client_as, db_engine) -> None:
    client = client_as("s.iyer")
    first = _events(_investigate(client, "Why are agent claims late?", fresh=True).text)
    calls_after_first = len(scripted.calls)

    # Same question after normalisation: replayed, no model call, same run and same steps.
    second = _events(_investigate(client, "  why are AGENT claims late  ").text)
    assert len(scripted.calls) == calls_after_first
    assert second[0][0] == "start" and second[0][1]["cached"] and second[0][1]["replay"]
    assert second[0][1]["id"] == first[0][1]["id"]
    assert [d for e, d in second if e == "step"] == [d for e, d in first if e == "step"]

    flush()
    with db_engine.connect() as conn:
        hits = conn.execute(
            text("""SELECT role, tier FROM observability.llm_calls
                    WHERE status = 'cache_hit' AND investigation_id = :id"""),
            {"id": first[0][1]["id"]},
        ).all()
    assert [tuple(h) for h in hits] == [("investigation", "cache")]

    # fresh=True runs again: a new run and new model calls.
    third = _events(_investigate(client, "Why are agent claims late?", fresh=True).text)
    assert not third[0][1].get("replay") and third[0][1]["id"] != first[0][1]["id"]
    assert len(scripted.calls) > calls_after_first


def test_cache_key_covers_question_scope_models_and_data(db_engine, pack) -> None:
    models = {"planner": "ollama:a"}
    scope = ProcessQuery()
    with db_engine.connect() as conn:
        d = pack.domain
        key = cache.cache_key(conn, d, "Why are claims late?", scope, models)
        assert key == cache.cache_key(conn, d, "why are claims late", scope, models)
        assert key != cache.cache_key(conn, d, "Why are health claims late?", scope, models)
        assert key != cache.cache_key(
            conn, d, "Why are claims late?", ProcessQuery(filters={"channel": ["agent"]}), models
        )
        assert key != cache.cache_key(conn, d, "Why are claims late?", scope, {"planner": "b"})
        # Any change to the case data (a simulated month, a reseed) misses the cache.
        conn.execute(
            text("""UPDATE operational.cases SET amount = amount + 1
                    WHERE case_id = (SELECT min(case_id) FROM operational.cases
                                     WHERE domain = :d)"""),
            {"d": d},
        )
        assert key != cache.cache_key(conn, d, "Why are claims late?", scope, models)
        conn.rollback()


def test_replay_pacing_is_clamped() -> None:
    events = [
        {"node": "scan", "update": {"steps": [{"node": "scan", "ms": 100}]}},
        {"node": "plan", "update": {"steps": [{}, {"node": "plan", "ms": 600_000}]}},
        {"node": "x", "update": {}},
    ]
    delays = [d for d, _ in cache.replay_steps(events, speed=10, min_delay=0.05, max_delay=2.5)]
    assert delays == [0.05, 2.5, 0.05]


def test_showcase_is_admin_only_and_viewers_can_replay(scripted, client_as) -> None:
    run_id = _events(
        _investigate(client_as("p.nair"), "Why do agent claims breach?", fresh=True).text
    )[0][1]["id"]
    assert (
        client_as("p.nair")
        .put(f"/api/investigations/{run_id}/showcase", json={"showcase": True})
        .status_code
        == 403
    )
    admin = client_as("admin")
    assert (
        admin.put(f"/api/investigations/{run_id}/showcase", json={"showcase": True}).status_code
        == 200
    )

    guest = client_as("guest")
    listed = guest.get("/api/investigations", params={"showcase": True}).json()
    assert run_id in [r["investigation_id"] for r in listed]
    assert all(r["replayable"] for r in listed)

    replay = _events(guest.get(f"/api/investigations/{run_id}/replay?speed=100").text)
    assert replay[0][1]["replay"] and not replay[0][1]["cached"]
    assert replay[-1][0] == "done"
    assert "events" not in guest.get(f"/api/investigations/{run_id}").json()

    # Guests still cannot start one.
    assert _investigate(guest, "Why do agent claims breach?").status_code == 403
    admin.put(f"/api/investigations/{run_id}/showcase", json={"showcase": False})


def test_runs_without_a_recording_cannot_be_replayed_or_showcased(client_as, db_engine) -> None:
    with db_engine.begin() as conn:
        old = conn.execute(
            text("""INSERT INTO intelligence.investigations (domain, question, status, result)
                    VALUES ('insurance_claims', 'An old run', 'completed', '{}'::jsonb)
                    RETURNING investigation_id"""),
        ).scalar_one()
    admin = client_as("admin")
    assert admin.get(f"/api/investigations/{old}/replay").status_code == 409
    assert (
        admin.put(f"/api/investigations/{old}/showcase", json={"showcase": True}).status_code == 409
    )


@pytest.fixture
def tight_limits(monkeypatch, db_engine):
    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_investigations_per_user_hour", 1)
    monkeypatch.setattr(s, "rate_limit_questions_per_user_hour", 1)
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM identity.usage_events"))
    yield s
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM identity.usage_events"))


def test_fresh_investigations_are_rate_limited_but_cache_hits_are_not(
    scripted, client_as, tight_limits
) -> None:
    client = client_as("r.menon")
    assert _investigate(client, "Why are agent claims slow?", fresh=True).status_code == 200
    blocked = _investigate(client, "Why are agent claims slower in March?", fresh=True)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "last hour" in blocked.json()["detail"]
    # Repeating the first question is a cache hit: free.
    repeat = _events(_investigate(client, "Why are agent claims slow?").text)
    assert repeat[0][1]["cached"]

    usage = client.get("/api/auth/usage").json()
    assert not usage["exempt"]
    assert usage["limits"]["investigate"][0] | {"resets_in": 0} == {
        "scope": "user",
        "limit": 1,
        "used": 1,
        "resets_in": 0,
    }
    # Admins are exempt.
    admin = client_as("admin")
    assert admin.get("/api/auth/usage").json()["exempt"]
    assert (
        _investigate(admin, "Why are agent claims slower in March?", fresh=True).status_code == 200
    )


def test_daily_budget_is_shared_by_everyone(scripted, client_as, tight_limits, monkeypatch) -> None:
    monkeypatch.setattr(tight_limits, "rate_limit_investigations_per_user_hour", 0)
    monkeypatch.setattr(tight_limits, "rate_limit_investigations_per_day", 1)
    assert (
        _investigate(client_as("a.rao"), "Why are agent claims slow now?", fresh=True).status_code
        == 200
    )
    blocked = _investigate(client_as("m.khan"), "Why are agent claims slow lately?", fresh=True)
    assert blocked.status_code == 429 and "daily budget" in blocked.json()["detail"]


def test_policy_questions_are_rate_limited_after_a_cache_miss(
    client_as, tight_limits, monkeypatch, kb, db_engine
) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from watchdog_backend.knowledge import qa
    from watchdog_backend.llm.gateway import ModelSpec

    fake = FakeListChatModel(responses=["The QA rejection target is 5% or lower per team [1]."])
    monkeypatch.setattr(qa, "get_chat_model", lambda role: (fake, ModelSpec("ollama", "fake")))
    client = client_as("s.iyer")
    q = {"question": "What is the QA rejection target for each team?"}
    other = {"question": "Who approves claim delegation?"}
    with db_engine.begin() as conn:  # the test database outlives a session
        conn.execute(
            text("DELETE FROM knowledge.answer_cache WHERE question IN (:a, :b)"),
            {"a": q["question"], "b": other["question"]},
        )
    assert client.post("/api/knowledge/ask", json=q).status_code == 200
    # The same question is answered from the cache; a new one is over the limit.
    assert client.post("/api/knowledge/ask", json=q).json()["cached"]
    r = client.post("/api/knowledge/ask", json=other)
    assert r.status_code == 429

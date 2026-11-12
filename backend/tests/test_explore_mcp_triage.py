"""Exploratory SQL sandbox, the Analytics and Knowledge MCP servers, and automatic triage."""

import pytest
from sqlalchemy import text

from tests.test_investigation_graph import ScriptedModel, _model
from watchdog_backend.analytics import explore
from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import use_domain

# --- exploratory SQL ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("delete from cases", "Only SELECT"),
        ("select 1; select 2", "one statement"),
        ("select 1 -- hi", "comments"),
        ("select set_config('statement_timeout', '0', false)", "set_config"),
        ("select pg_sleep(10)", "pg_sleep"),
        ("select 1) as x, (select 1", "parentheses"),
        ("select $$($$) as x, (select 1)", "Dollar"),
        ("", "Write a SELECT"),
    ],
)
def test_explore_refuses_before_running(sql: str, reason: str) -> None:
    with pytest.raises(explore.ExploreError, match=reason):
        explore.validate(sql)


def _cases(db_engine, domain: str) -> int:
    with db_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM operational.cases WHERE domain = :d"), {"d": domain}
        ).scalar_one()


def test_explore_reads_only_the_active_packs_views(db_engine, pack) -> None:
    r = explore.run(
        "select attributes->>'channel' as channel, count(*) as n from cases group by 1 order by 1"
    )
    assert r.columns == ["channel", "n"]
    assert sum(row[1] for row in r.rows) == _cases(db_engine, "insurance_claims")
    assert "not a verified metric" in r.label
    with use_domain("procure_to_pay"):
        p2p = explore.run("select count(*) from cases").rows
    assert p2p == [[_cases(db_engine, "procure_to_pay")]]
    with use_domain("procure_to_pay"):  # the P2P-only column proves which pack was read
        assert explore.run("select count(distinct attributes->>'po_type') from cases").rows == [[3]]
    for forbidden in ("select * from identity.users", "select * from operational.cases"):
        with pytest.raises(explore.ExploreError, match="Permission denied"):
            explore.run(forbidden)
    with pytest.raises(explore.ExploreError, match="top level"):
        explore.run("with d as (delete from operational.cases returning *) select * from d")


def test_explore_caps_rows_and_time(db_engine, monkeypatch) -> None:
    r = explore.run("select case_id from cases")
    assert r.row_count == explore.MAX_ROWS and r.truncated
    monkeypatch.setattr(explore, "TIMEOUT_MS", 200)
    with pytest.raises(explore.ExploreError, match="longer than"):
        explore.run("select count(*) from events a, events b")


def test_explore_api_roles_and_draft(client_as, monkeypatch, db_engine) -> None:
    from watchdog_backend.llm import gateway
    from watchdog_backend.llm.gateway import ModelSpec

    assert client_as("guest").post("/api/explore/run", json={"sql": "select 1"}).status_code == 403
    analyst = client_as("p.nair")
    assert analyst.post("/api/explore/run", json={"sql": "select 1 as one"}).json()["rows"] == [[1]]
    bad = analyst.post("/api/explore/run", json={"sql": "select * from identity.sessions"})
    assert bad.status_code == 422 and "Permission denied" in bad.json()["detail"]
    assert "attributes keys" in analyst.get("/api/explore/schema").json()["doc"]

    drafted = explore.Draft(
        sql="select attributes->>'channel' as channel, avg(breached::int) as rate "
        "from cases group by 1",
        explanation="Breach rate per channel.",
    )
    model = ScriptedModel({explore.Draft: [drafted]}, ["unused"])
    monkeypatch.setattr(gateway, "get_chat_model", lambda role: (model, ModelSpec("ollama", "s")))
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM identity.usage_events"))
    body = analyst.post("/api/explore/draft", json={"question": "Breach rate by channel?"}).json()
    assert body["sql"].startswith("select") and body["model"] == "ollama:s"
    assert analyst.post("/api/explore/run", json={"sql": body["sql"]}).json()["row_count"] == 3


# --- MCP servers ----------------------------------------------------------------------------

ANALYTICS_TOKEN = "analytics-test-token"
KNOWLEDGE_TOKEN = "knowledge-test-token"


@pytest.fixture
def mcp_tokens(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "analytics_mcp_tokens", {ANALYTICS_TOKEN: "test-agent"})
    monkeypatch.setattr(s, "knowledge_mcp_tokens", {KNOWLEDGE_TOKEN: "test-agent"})


async def _mcp(module: str, port: int, token: str, tool: str, args: dict):
    import importlib

    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    mcp_app = importlib.import_module(f"watchdog_backend.mcp_servers.{module}").build_app()
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=mcp_app),
            headers={"Authorization": f"Bearer {token}"},
            base_url=f"http://localhost:{port}",
        ) as http,
        streamable_http_client(f"http://localhost:{port}/mcp", http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        if tool == "__list__":
            return (await session.list_tools()).tools
        return await session.call_tool(tool, args)


@pytest.mark.anyio
async def test_analytics_mcp_is_read_only_and_matches_the_metrics_engine(
    db_engine, mcp_tokens
) -> None:
    tools = await _mcp("analytics", 8101, ANALYTICS_TOKEN, "__list__", {})
    assert all(t.annotations.read_only_hint for t in tools)
    res = await _mcp(
        "analytics",
        8101,
        ANALYTICS_TOKEN,
        "query_metric",
        {"metric": "sla_breach_rate", "group_by": ["channel"]},
    )
    assert not res.is_error
    rows = {r["group"]["channel"]: r["value"] for r in res.structured_content["rows"]}
    assert set(rows) == {"agent", "broker", "direct"} and rows["broker"] > rows["direct"]

    p2p = await _mcp(
        "analytics",
        8101,
        ANALYTICS_TOKEN,
        "run_exploratory_sql",
        {"sql": "select count(*) as n from cases", "domain": "procure_to_pay"},
    )
    assert p2p.structured_content["rows"] == [[_cases(db_engine, "procure_to_pay")]]
    refused = await _mcp(
        "analytics", 8101, ANALYTICS_TOKEN, "run_exploratory_sql", {"sql": "drop table cases"}
    )
    assert refused.is_error and "Only SELECT" in refused.content[0].text


@pytest.mark.anyio
async def test_each_mcp_server_accepts_only_its_own_tokens(db_engine, mcp_tokens) -> None:
    import httpx2

    from watchdog_backend.mcp_servers.analytics import build_app

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=build_app()), base_url="http://localhost:8101"
    ) as http:
        r = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {KNOWLEDGE_TOKEN}",
            },
        )
    assert r.status_code == 401


@pytest.mark.anyio
async def test_knowledge_mcp_search_and_document(db_engine, kb, mcp_tokens) -> None:
    hits = await _mcp(
        "knowledge", 8102, KNOWLEDGE_TOKEN, "search_policies", {"query": "QA rejection target"}
    )
    assert hits.structured_content["result"][0]["doc_key"] == "SOP-105"
    doc = await _mcp("knowledge", 8102, KNOWLEDGE_TOKEN, "get_document", {"doc_key": "SOP-105"})
    assert doc.structured_content["status"] == "current" and doc.structured_content["sections"]
    missing = await _mcp("knowledge", 8102, KNOWLEDGE_TOKEN, "get_document", {"doc_key": "NOPE"})
    assert missing.is_error


# --- automatic triage -----------------------------------------------------------------------


@pytest.fixture
def triage_env(db_engine, kb, monkeypatch):
    """Triage on, a scripted model, fresh alerts; restores the alerts afterwards."""
    from watchdog_backend.investigation import service
    from watchdog_backend.llm.gateway import ModelSpec
    from watchdog_backend.watch.engine import run_monitors

    model = _model()
    monkeypatch.setattr(
        service, "get_chat_model", lambda role: (model, ModelSpec("ollama", "scripted"))
    )
    s = get_settings()
    monkeypatch.setattr(s, "watch_auto_investigate", "critical")
    monkeypatch.setattr(s, "watch_auto_investigate_max_per_run", 1)
    reset = """UPDATE intelligence.alerts SET triage_status = NULL, triage_note = NULL,
               triaged_at = NULL, investigation_id = NULL, status = 'open'
               WHERE domain = 'insurance_claims' AND status <> 'resolved'"""
    with db_engine.begin() as conn:
        conn.execute(text(reset))
        conn.execute(text("DELETE FROM identity.usage_events"))
        # The test database outlives a session: earlier triage runs must not be reused.
        conn.execute(
            text("""UPDATE intelligence.investigations SET cache_key = NULL
                    WHERE user_id = 'watchdog-watch'""")
        )
    with db_engine.connect() as conn:
        run_monitors(conn, "manual")
    yield model
    with db_engine.begin() as conn:
        conn.execute(text(reset))
        conn.execute(text("DELETE FROM identity.usage_events"))


def _alerts(db_engine) -> list[dict]:
    with db_engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("""SELECT alert_id, severity, value, threshold, triage_status,
                               investigation_id FROM intelligence.alerts
                        WHERE domain = 'insurance_claims' AND status = 'open'""")
            ).mappings()
        ]


def test_triage_investigates_the_top_critical_alert_then_reuses(triage_env, db_engine) -> None:
    from watchdog_backend.watch.triage import triage

    criticals = [a for a in _alerts(db_engine) if a["severity"] == "critical"]
    assert len(criticals) >= 2, "seed-42 data should raise several critical alerts"
    with db_engine.connect() as conn:
        (first,) = triage(conn)
    assert first.status == "investigated" and first.investigation_id
    assert "Ranked 1 of" in first.note
    after = {str(a["alert_id"]): a for a in _alerts(db_engine)}
    assert str(after[first.alert_id]["investigation_id"]) == first.investigation_id
    assert all(a["triage_status"] is None for a in after.values() if a["severity"] == "warning")

    # Run again: one new alert per run, never the one already done.
    with db_engine.connect() as conn:
        (second,) = triage(conn)
    assert second.alert_id != first.alert_id

    # The same question on the same data is linked, not re-run.
    with db_engine.begin() as conn:
        conn.execute(
            text("""UPDATE intelligence.alerts SET triage_status = NULL,
                    investigation_id = NULL WHERE alert_id = :id"""),
            {"id": first.alert_id},
        )
    with db_engine.connect() as conn:
        outcomes = triage(conn)
    (again,) = [o for o in outcomes if o.alert_id == first.alert_id]
    assert again.status == "reused" and again.investigation_id == first.investigation_id
    # Linking is free, so it does not use up the run's one new investigation.
    assert [o.status for o in outcomes].count("investigated") <= 1


def test_triage_respects_the_daily_budget_and_off_switch(
    triage_env, db_engine, monkeypatch
) -> None:
    from watchdog_backend.watch.triage import triage

    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_investigations_per_day", 1)
    with db_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO identity.usage_events (user_id, action) VALUES ('x', 'investigate')")
        )
    with db_engine.connect() as conn:
        outcomes = triage(conn)
    assert outcomes and all(o.status in ("skipped", "reused") for o in outcomes)
    skipped = [o for o in outcomes if o.status == "skipped"]
    assert not skipped or "daily budget" in skipped[0].note

    # Skipped alerts are reconsidered once the budget allows.
    if skipped:
        monkeypatch.setattr(s, "rate_limit_investigations_per_day", 100)
        with db_engine.connect() as conn:
            retried = [o for o in triage(conn) if o.alert_id == skipped[0].alert_id]
        assert retried and retried[0].status in ("investigated", "reused")

    monkeypatch.setattr(s, "watch_auto_investigate", "off")
    with db_engine.connect() as conn:
        assert triage(conn) == []


def test_alerts_api_shows_triage(triage_env, client_as, db_engine) -> None:
    from watchdog_backend.watch.triage import triage

    with db_engine.connect() as conn:
        (done,) = triage(conn)
    alerts = client_as("s.iyer").get("/api/watch").json()["alerts"]
    shown = next(a for a in alerts if a["alert_id"] == done.alert_id)
    assert shown["triage_status"] == done.status and shown["triage_note"] == done.note


def test_failed_triage_is_not_linked_to_the_alert(triage_env, db_engine, monkeypatch) -> None:
    from watchdog_backend.watch import triage as t

    monkeypatch.setattr(t, "run_investigation", lambda *a, **k: ("some-id", "model unreachable"))
    with db_engine.connect() as conn:
        (failed,) = t.triage(conn)
    assert failed.status == "failed" and failed.investigation_id is None
    assert "model unreachable" in failed.note
    row = next(a for a in _alerts(db_engine) if str(a["alert_id"]) == failed.alert_id)
    assert row["investigation_id"] is None  # a person can still investigate it

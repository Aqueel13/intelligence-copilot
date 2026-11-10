"""Governance: who may propose, approve and execute actions, through every door.

Each rule is tested where it is enforced (the service), then through the API and the
Operations MCP server, so a forced click or a direct MCP call is refused too.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from watchdog_backend.config import get_settings
from watchdog_backend.enterprise_mock.app import app as enterprise_app
from watchdog_backend.governance import audit
from watchdog_backend.governance import service as gov
from watchdog_backend.governance.executor import http_executor

ENTERPRISE_KEY = "test-enterprise-key"
MCP_TOKEN = "test-mcp-token"


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "enterprise_api_key", ENTERPRISE_KEY)
    monkeypatch.setattr(s, "operations_mcp_tokens", {MCP_TOKEN: "test-agent"})


@pytest.fixture
def conn(db_engine):
    with db_engine.connect() as c:
        yield c


@pytest.fixture
def executor():
    return http_executor(TestClient(enterprise_app))


def analyst():
    return gov.user_actor("m.khan")


def head_of_claims():
    return gov.user_actor("a.rao")


def audit_events(conn, request_id) -> list[str]:
    return [e.event for e in reversed(audit.entries(conn, request_id))]


# --- proposing -----------------------------------------------------------------------


def test_anyone_can_propose_a_catalogue_action(conn) -> None:
    req = gov.propose(conn, analyst(), "delegate_mid_value_approvals", "queue is too long")
    assert req.status == "proposed"
    assert req.approver_roles == ["Head of Claims"]
    assert "POL-002 §4.3" in req.policy_refs
    assert audit_events(conn, req.request_id) == ["action.proposed"]


def test_unknown_action_is_refused_and_the_refusal_is_kept(conn, db_engine) -> None:
    with pytest.raises(gov.GovernanceError, match="Unknown action") as err:
        gov.propose(conn, analyst(), "fire_everyone", "x")
    assert err.value.code == "invalid"
    with db_engine.connect() as other:  # visible from another connection: it was committed
        last = audit.entries(other, limit=1)[0]
    assert last.event == "action.propose_denied" and last.details["action_id"] == "fire_everyone"


# --- deciding ------------------------------------------------------------------------


@pytest.fixture
def proposed(conn):
    return gov.propose(conn, analyst(), "delegate_mid_value_approvals", "test")


def test_wrong_role_cannot_approve(conn, proposed) -> None:
    with pytest.raises(gov.GovernanceError, match="needs: Head of Claims") as err:
        gov.decide(conn, gov.user_actor("s.iyer"), proposed.request_id, "approved")
    assert err.value.code == "forbidden"
    assert gov.get(conn, proposed.request_id).status == "proposed"
    assert audit_events(conn, proposed.request_id)[-1] == "action.decision_denied"


def test_agents_and_mcp_clients_can_never_approve(conn, proposed) -> None:
    agent = gov.Actor(id="some-agent", type="mcp_client", role="Head of Claims", via="mcp:x")
    with pytest.raises(gov.GovernanceError, match="Only a person"):
        gov.decide(conn, agent, proposed.request_id, "approved")


def test_separation_of_duties(conn) -> None:
    own = gov.propose(conn, head_of_claims(), "delegate_mid_value_approvals", "mine")
    with pytest.raises(gov.GovernanceError, match="Separation of duties"):
        gov.decide(conn, head_of_claims(), own.request_id, "approved")


def test_right_role_approves_once(conn, proposed) -> None:
    req = gov.decide(conn, head_of_claims(), proposed.request_id, "approved", "ok")
    assert (req.status, req.decided_by, req.decided_role) == ("approved", "a.rao", "Head of Claims")
    with pytest.raises(gov.GovernanceError, match="already approved") as err:
        gov.decide(conn, head_of_claims(), proposed.request_id, "rejected")
    assert err.value.code == "conflict"


# --- executing -----------------------------------------------------------------------


def test_cannot_execute_before_approval(conn, proposed, executor) -> None:
    with pytest.raises(gov.GovernanceError, match="needs a human approval") as err:
        gov.execute(conn, head_of_claims(), proposed.request_id, executor)
    assert err.value.code == "forbidden"
    assert audit_events(conn, proposed.request_id)[-1] == "action.execute_denied"


def test_rejected_actions_cannot_be_executed(conn, proposed, executor) -> None:
    gov.decide(conn, head_of_claims(), proposed.request_id, "rejected", "not now")
    with pytest.raises(gov.GovernanceError, match="rejected"):
        gov.execute(conn, head_of_claims(), proposed.request_id, executor)


def test_approved_action_executes_exactly_once(conn, db_engine, proposed, executor) -> None:
    gov.decide(conn, head_of_claims(), proposed.request_id, "approved")
    done = gov.execute(conn, gov.user_actor("s.iyer"), proposed.request_id, executor)
    assert done.status == "executed"
    assert done.result["resource"] == "approval-routing"
    assert done.result["payload"]["approver_role"] == "Team Lead"
    with pytest.raises(gov.GovernanceError, match="executed") as err:
        gov.execute(conn, head_of_claims(), proposed.request_id, executor)
    assert err.value.code == "conflict"
    with db_engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM mock_enterprise.records WHERE reference = :r"),
            {"r": str(proposed.request_id)},
        ).scalar_one()
    assert n == 1
    assert audit_events(conn, proposed.request_id)[-3:] == [
        "action.execution_started",
        "action.executed",
        "action.execute_denied",
    ]


def test_external_failure_is_recorded_not_retried(conn, proposed) -> None:
    gov.decide(conn, head_of_claims(), proposed.request_id, "approved")

    def broken(*_):
        raise RuntimeError("claims system down")

    failed = gov.execute(conn, head_of_claims(), proposed.request_id, broken)
    assert failed.status == "failed" and "claims system down" in failed.error
    with pytest.raises(gov.GovernanceError):
        gov.execute(conn, head_of_claims(), proposed.request_id, broken)


def test_enterprise_mock_is_idempotent_and_keyed() -> None:
    client = TestClient(enterprise_app)
    body = {"reference": f"idem-{uuid4()}", "requested_by": "t", "payload": {"x": 1}}
    assert client.post("/training-sessions", json=body).status_code == 401
    h = {"X-Api-Key": ENTERPRISE_KEY}
    first = client.post("/training-sessions", json=body, headers=h).json()
    again = client.post("/training-sessions", json=body, headers=h).json()
    assert first["created"] and not again["created"]
    assert first["record_id"] == again["record_id"]


# --- audit log -----------------------------------------------------------------------


def test_audit_chain_verifies(conn, proposed) -> None:
    assert audit.verify(conn).ok


def test_editing_an_entry_breaks_the_chain(db_engine, proposed) -> None:
    with db_engine.connect() as c:  # tamper inside a transaction we roll back
        entry = audit.entries(c, proposed.request_id)[0].entry_id
        c.execute(
            text("UPDATE governance.audit_log SET actor = 'someone-else' WHERE entry_id = :e"),
            {"e": entry},
        )
        result = audit.verify(c)
        c.rollback()
    assert not result.ok and result.first_broken_entry == entry
    assert "edited" in result.reason


def test_deleting_an_entry_breaks_the_chain(db_engine, proposed) -> None:
    with db_engine.connect() as c:
        first = c.execute(text("SELECT min(entry_id) FROM governance.audit_log")).scalar_one()
        c.execute(text("DELETE FROM governance.audit_log WHERE entry_id = :e"), {"e": first})
        result = audit.verify(c)
        c.rollback()
    assert not result.ok and "removed" in result.reason


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch, executor):
    from watchdog_backend.api import actions as actions_api
    from watchdog_backend.db import get_engine
    from watchdog_backend.main import app

    async def fake_mcp(tool, arguments):  # what the real MCP server would do
        from uuid import UUID

        with get_engine().connect() as c:
            agent = gov.Actor(id="watchdog-backend", type="mcp_client", via="mcp:test")
            return gov.execute(c, agent, UUID(arguments["request_id"]), executor).model_dump()

    monkeypatch.setattr(actions_api, "call_operations_tool", fake_mcp)
    return TestClient(app)


def test_api_full_flow(api) -> None:
    rid = api.post(
        "/api/actions",
        json={"action_id": "retrain_team_b", "user_id": "m.khan", "rationale": "rework"},
    ).json()["request_id"]
    assert api.post(f"/api/actions/{rid}/execute", json={"user_id": "p.nair"}).status_code == 403
    r = api.post(f"/api/actions/{rid}/decision", json={"user_id": "m.khan", "decision": "approved"})
    assert r.status_code == 403
    r = api.post(f"/api/actions/{rid}/decision", json={"user_id": "p.nair", "decision": "approved"})
    assert r.json()["status"] == "approved"
    r = api.post(f"/api/actions/{rid}/execute", json={"user_id": "p.nair"})
    assert r.json()["status"] == "executed"
    detail = api.get(f"/api/actions/{rid}").json()
    events = [e["event"] for e in detail["audit"]]
    assert (
        events.count("action.execute_denied") == 1 and events.count("action.decision_denied") == 1
    )
    assert detail["impact"]["breaches_avoided"] > 0  # snapshot frozen at proposal
    assert api.get("/api/audit/verify").json()["ok"]


def test_api_rejects_unknown_users(api) -> None:
    r = api.post("/api/actions", json={"action_id": "retrain_team_b", "user_id": "mallory"})
    assert r.status_code == 403


# --- Operations MCP server (in-process over ASGI, real bearer auth) -------------------


async def _mcp(token: str | None, tool: str, args: dict):
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from watchdog_backend.mcp_servers.operations import build_app

    mcp_app = build_app()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=mcp_app),
            headers=headers,
            base_url="http://localhost:8103",
        ) as http,
        streamable_http_client("http://localhost:8103/mcp", http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        if tool == "__list__":
            return [t.name for t in (await session.list_tools()).tools]
        return await session.call_tool(tool, args)


@pytest.mark.anyio
async def test_mcp_requires_a_valid_token(db_engine) -> None:
    import httpx2

    from watchdog_backend.mcp_servers.operations import build_app

    mcp_app = build_app()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=mcp_app), base_url="http://localhost:8103"
    ) as http:
        r = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    assert r.status_code == 401


@pytest.mark.anyio
async def test_mcp_has_no_approve_tool(db_engine) -> None:
    tools = await _mcp(MCP_TOKEN, "__list__", {})
    assert "execute_action" in tools and "propose_action" in tools
    assert not any("approve" in t or "decide" in t for t in tools)


@pytest.mark.anyio
async def test_mcp_client_can_propose_but_not_execute_unapproved(db_engine, kb) -> None:
    res = await _mcp(
        MCP_TOKEN,
        "propose_action",
        {"action_id": "enforce_broker_checklist", "rationale": "broker docs"},
    )
    assert not res.is_error
    proposal = res.structured_content
    assert proposal["requested_by"] == "test-agent"  # identity comes from the token
    assert proposal["requested_via"] == "mcp:test-agent"
    assert proposal["impact"]["breaches_avoided"] > 0  # same evidence as UI proposals

    res = await _mcp(MCP_TOKEN, "execute_action", {"request_id": proposal["request_id"]})
    assert res.is_error
    assert "needs a human approval" in res.content[0].text  # the refusal says why


@pytest.fixture
def anyio_backend():
    return "asyncio"

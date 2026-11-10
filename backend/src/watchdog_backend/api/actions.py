"""Action Centre API: propose, decide, execute, and inspect the audit trail."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from watchdog_backend.db import get_engine
from watchdog_backend.governance import audit
from watchdog_backend.governance import service as gov
from watchdog_backend.governance.config import User, get_governance
from watchdog_backend.governance.impact import impact_snapshot
from watchdog_backend.governance.mcp_client import MCPToolError, call_operations_tool

router = APIRouter(tags=["actions"])
_HTTP = {"not_found": 404, "forbidden": 403, "conflict": 409, "invalid": 422}


def _fail(exc: gov.GovernanceError) -> HTTPException:
    return HTTPException(status_code=_HTTP[exc.code], detail=str(exc))


@router.get("/governance/users", response_model=list[User])
def users() -> list[User]:
    """Demo identities until login exists (M8). Identity is self-asserted."""
    return get_governance().users


@router.get("/actions", response_model=list[gov.ActionRequest])
def list_actions(status: gov.Status | None = None) -> list[gov.ActionRequest]:
    with get_engine().connect() as conn:
        return gov.list_requests(conn, status)


@router.get("/actions/{request_id}")
def get_action(request_id: UUID) -> dict[str, Any]:
    with get_engine().connect() as conn:
        try:
            req = gov.get(conn, request_id)
        except gov.GovernanceError as exc:
            raise _fail(exc) from exc
        trail = audit.entries(conn, request_id)
    return {
        **req.model_dump(mode="json"),
        "audit": [e.model_dump(mode="json") for e in reversed(trail)],
    }


class ProposeIn(BaseModel):
    action_id: str
    user_id: str
    rationale: str | None = Field(None, max_length=1000)
    investigation_id: UUID | None = None


@router.post("/actions", response_model=gov.ActionRequest, status_code=201)
def propose(body: ProposeIn) -> gov.ActionRequest:
    with get_engine().connect() as conn:
        try:
            actor = gov.user_actor(body.user_id)
            impact = impact_snapshot(conn, body.action_id, body.investigation_id)
            return gov.propose(
                conn, actor, body.action_id, body.rationale, body.investigation_id, impact
            )
        except gov.GovernanceError as exc:
            raise _fail(exc) from exc


class DecisionIn(BaseModel):
    user_id: str
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=1000)


@router.post("/actions/{request_id}/decision", response_model=gov.ActionRequest)
def decide(request_id: UUID, body: DecisionIn) -> gov.ActionRequest:
    with get_engine().connect() as conn:
        try:
            actor = gov.user_actor(body.user_id)
            return gov.decide(conn, actor, request_id, body.decision, body.note)
        except gov.GovernanceError as exc:
            raise _fail(exc) from exc


class ExecuteIn(BaseModel):
    user_id: str


@router.post("/actions/{request_id}/execute", response_model=gov.ActionRequest)
async def execute(request_id: UUID, body: ExecuteIn) -> gov.ActionRequest:
    """Execute through the Operations MCP server. The backend checks first (fast, clear
    errors); the MCP server checks again before anything changes."""
    with get_engine().connect() as conn:
        try:
            gov.user_actor(body.user_id)
            req = gov.get(conn, request_id)
        except gov.GovernanceError as exc:
            raise _fail(exc) from exc
        if req.status != "approved":
            audit.append(
                conn,
                body.user_id,
                "user",
                "action.execute_denied",
                request_id,
                {
                    "status": req.status,
                    "via": "ui",
                    "reason": "only approved actions can be executed",
                },
            )
            conn.commit()
            raise HTTPException(
                status_code=403 if req.status == "proposed" else 409,
                detail=f"Action is {req.status}; only an approved action can be executed.",
            )
        audit.append(
            conn,
            body.user_id,
            "user",
            "action.execute_requested",
            request_id,
            {"via": "ui", "through": "operations-mcp"},
        )
        conn.commit()
    try:
        await call_operations_tool("execute_action", {"request_id": str(request_id)})
    except MCPToolError as exc:
        raise HTTPException(status_code=502, detail=f"Operations MCP: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Operations MCP unreachable: {exc}") from exc
    with get_engine().connect() as conn:
        return gov.get(conn, request_id)


@router.get("/audit", response_model=list[audit.AuditEntry])
def audit_log(limit: int = 200) -> list[audit.AuditEntry]:
    with get_engine().connect() as conn:
        return audit.entries(conn, limit=min(limit, 1000))


@router.get("/audit/verify", response_model=audit.Verification)
def verify() -> audit.Verification:
    with get_engine().connect() as conn:
        return audit.verify(conn)

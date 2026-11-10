"""Action governance: the single place that decides what may happen to an action.

Both the backend API and the Operations MCP server call these functions, so the rules are
enforced the same way whichever door a request comes through:

    proposed ──approve──▶ approved ──execute──▶ executing ──▶ executed | failed
        └──────reject───▶ rejected

- Anyone (user, agent, MCP client) may PROPOSE an action from the catalogue.
- Only a USER holding one of the action's approver roles may APPROVE or REJECT it, and not the
  person who proposed it (separation of duties). There is deliberately no way for an agent or
  MCP client to approve.
- Only an APPROVED action may be EXECUTED, exactly once (row lock + status transition).
- Every attempt, including every denied one, is written to the audit log. Functions commit
  their own work (and denial records) so a refused attempt is never rolled back out of the log.
  Pass a connection that is not managed by an ORM session.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection, text

from watchdog_backend.domain.pack import get_pack
from watchdog_backend.governance import audit
from watchdog_backend.governance.audit import ActorType
from watchdog_backend.governance.config import get_governance
from watchdog_backend.investigation.actions import Operation, get_catalogue

Status = Literal["proposed", "approved", "rejected", "executing", "executed", "failed"]
Executor = Callable[[UUID, Operation, str], dict[str, Any]]


class GovernanceError(Exception):
    """A rule was violated. `code` maps to an HTTP status / MCP error."""

    def __init__(self, code: Literal["not_found", "forbidden", "conflict", "invalid"], msg: str):
        self.code = code
        super().__init__(msg)


class Actor(BaseModel):
    id: str
    type: ActorType
    role: str | None = None  # users only
    via: str  # "ui", "api", "mcp:<client>"


class ActionRequest(BaseModel):
    request_id: UUID
    action_id: str
    title: str
    operation: dict[str, Any]
    impact: dict[str, Any] | None
    policy_refs: list[str]
    approver_roles: list[str]
    approval_basis: str | None = None
    investigation_id: UUID | None
    rationale: str | None
    status: Status
    requested_by: str
    requested_via: str
    created_at: datetime
    decision: str | None = None
    decided_by: str | None = None
    decided_role: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    executed_by: str | None
    executed_at: datetime | None
    result: dict[str, Any] | None
    error: str | None


_SELECT = """
    SELECT r.*, a.decision, a.decided_by, a.role AS decided_role, a.note AS decision_note,
           a.decided_at
    FROM operations.action_requests r
    LEFT JOIN operations.approvals a USING (request_id)
"""


def _deny(
    conn: Connection,
    actor: Actor,
    event: str,
    request_id: UUID | None,
    details: dict[str, Any],
    code: Literal["not_found", "forbidden", "conflict", "invalid"],
    message: str,
) -> GovernanceError:
    """Record a refused attempt durably, then return the error to raise."""
    conn.rollback()  # drop any partial work and release row locks
    audit.append(
        conn,
        actor.id,
        actor.type,
        event,
        request_id,
        {**details, "reason": message, "via": actor.via},
    )
    conn.commit()
    return GovernanceError(code, message)


def _row(row: Any) -> ActionRequest:
    data = dict(row)
    rule = get_governance().approvals.get(data["action_id"])
    data["approval_basis"] = rule.basis if rule else None
    return ActionRequest(**data)


def user_actor(user_id: str, via: str = "ui") -> Actor:
    user = get_governance().user(user_id)
    if user is None:
        raise GovernanceError("forbidden", f"Unknown user '{user_id}'")
    return Actor(id=user.id, type="user", role=user.role, via=via)


def get(conn: Connection, request_id: UUID) -> ActionRequest:
    row = (
        conn.execute(text(f"{_SELECT} WHERE r.request_id = :id"), {"id": request_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise GovernanceError("not_found", f"Action request {request_id} not found")
    return _row(row)


def list_requests(
    conn: Connection, status: Status | None = None, limit: int = 100
) -> list[ActionRequest]:
    where = "WHERE r.domain = :d" + (" AND r.status = :s" if status else "")
    rows = conn.execute(
        text(f"{_SELECT} {where} ORDER BY r.created_at DESC LIMIT :n"),
        {"d": get_pack().domain, "s": status, "n": limit},
    ).mappings()
    return [_row(r) for r in rows]


def propose(
    conn: Connection,
    actor: Actor,
    action_id: str,
    rationale: str | None = None,
    investigation_id: UUID | None = None,
    impact: dict[str, Any] | None = None,
) -> ActionRequest:
    catalogue = get_catalogue()
    action = catalogue.actions.get(action_id)
    if action is None:
        raise _deny(
            conn,
            actor,
            "action.propose_denied",
            None,
            {"action_id": action_id},
            "invalid",
            f"Unknown action '{action_id}'. Allowed: {', '.join(catalogue.actions)}",
        )
    rule = get_governance().approvals.get(action_id)
    if rule is None:
        raise GovernanceError("invalid", f"No approval rule configured for '{action_id}'")
    request_id = conn.execute(
        text("""
            INSERT INTO operations.action_requests
                (domain, action_id, title, operation, impact, policy_refs, approver_roles,
                 investigation_id, rationale, status, requested_by, requested_via)
            VALUES (:domain, :action_id, :title, CAST(:operation AS jsonb), CAST(:impact AS jsonb),
                    :policy_refs, :roles, :inv, :rationale, 'proposed', :by, :via)
            RETURNING request_id
        """),
        {
            "domain": get_pack().domain,
            "action_id": action_id,
            "title": action.title,
            "operation": action.operation.model_dump_json(),
            "impact": json.dumps(impact, default=str) if impact else None,
            "policy_refs": action.policy_refs,
            "roles": rule.roles,
            "inv": investigation_id,
            "rationale": rationale,
            "by": actor.id,
            "via": actor.via,
        },
    ).scalar_one()
    audit.append(
        conn,
        actor.id,
        actor.type,
        "action.proposed",
        request_id,
        {
            "action_id": action_id,
            "via": actor.via,
            "investigation_id": investigation_id,
            "approver_roles": rule.roles,
        },
    )
    conn.commit()
    return get(conn, request_id)


def decide(
    conn: Connection,
    actor: Actor,
    request_id: UUID,
    decision: Literal["approved", "rejected"],
    note: str | None = None,
) -> ActionRequest:
    req = _lock(conn, request_id)

    def deny(reason: str, code: Literal["forbidden", "conflict"] = "forbidden") -> GovernanceError:
        return _deny(
            conn, actor, "action.decision_denied", request_id, {"decision": decision}, code, reason
        )

    if actor.type != "user":
        raise deny("Only a person can approve or reject actions; agents and MCP clients cannot.")
    if req.status != "proposed":
        raise deny(f"Action is already {req.status}.", "conflict")
    if actor.role not in req.approver_roles:
        raise deny(
            f"{actor.id} ({actor.role}) may not decide this action; it needs: "
            f"{', '.join(req.approver_roles)}."
        )
    if get_governance().rules.separation_of_duties and actor.id == req.requested_by:
        raise deny("Separation of duties: the person who proposed an action cannot approve it.")

    conn.execute(
        text("""INSERT INTO operations.approvals (request_id, decision, decided_by, role, note)
                VALUES (:id, :d, :by, :role, :note)"""),
        {"id": request_id, "d": decision, "by": actor.id, "role": actor.role, "note": note},
    )
    conn.execute(
        text("UPDATE operations.action_requests SET status = :s WHERE request_id = :id"),
        {"s": decision, "id": request_id},
    )
    audit.append(
        conn,
        actor.id,
        actor.type,
        f"action.{decision}",
        request_id,
        {"role": actor.role, "note": note, "via": actor.via},
    )
    conn.commit()
    return get(conn, request_id)


def execute(conn: Connection, actor: Actor, request_id: UUID, executor: Executor) -> ActionRequest:
    """Execute an approved action exactly once. Commits the 'executing' state before calling
    the external system, so a crash mid-call leaves a visible, non-repeatable state."""
    req = _lock(conn, request_id)
    if req.status != "approved":
        raise _deny(
            conn,
            actor,
            "action.execute_denied",
            request_id,
            {"status": req.status},
            "forbidden" if req.status == "proposed" else "conflict",
            f"Action is {req.status}; only an approved action can be executed"
            + (" (it needs a human approval first)." if req.status == "proposed" else "."),
        )
    conn.execute(
        text("""UPDATE operations.action_requests SET status = 'executing', executed_by = :by
                WHERE request_id = :id"""),
        {"by": actor.id, "id": request_id},
    )
    audit.append(
        conn,
        actor.id,
        actor.type,
        "action.execution_started",
        request_id,
        {"operation": req.operation, "via": actor.via},
    )
    conn.commit()

    try:
        op = Operation.model_validate(req.operation)
        result = executor(request_id, op, actor.id)
        status, error = "executed", None
    except Exception as exc:  # the external system failed; record it, never retry blindly
        result, status, error = None, "failed", str(exc)[:500]
    conn.execute(
        text("""UPDATE operations.action_requests
                SET status = :s, executed_at = now(), result = CAST(:r AS jsonb), error = :e
                WHERE request_id = :id"""),
        {
            "s": status,
            "r": json.dumps(result, default=str) if result else None,
            "e": error,
            "id": request_id,
        },
    )
    audit.append(
        conn,
        actor.id,
        actor.type,
        f"action.{status}",
        request_id,
        {"result": result, "error": error, "via": actor.via},
    )
    conn.commit()
    return get(conn, request_id)


def _lock(conn: Connection, request_id: UUID) -> ActionRequest:
    found = conn.execute(
        text("SELECT 1 FROM operations.action_requests WHERE request_id = :id FOR UPDATE"),
        {"id": request_id},
    ).scalar_one_or_none()
    if found is None:
        conn.rollback()
        raise GovernanceError("not_found", f"Action request {request_id} not found")
    return get(conn, request_id)

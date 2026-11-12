"""Operations MCP server: lets MCP clients (the WatchDog backend, Claude Desktop, any agent)
work with corrective actions under the same governance as the web app.

Tools
- list_catalogue_actions   read   the actions this domain allows, with who must approve them
- list_action_requests     read   requests and their status
- get_action_request       read   one request with its audit trail
- propose_action           write  create a request; it does nothing until a person approves it
- execute_action           write  execute a request that a PERSON has already approved
- verify_audit_log         read   check the audit hash chain

There is deliberately no approve tool: approval is a human decision made in the web app.
Tools that work on a whole domain take an optional `domain` (a domain pack name; default: the
default pack); tools that take a request id work on that request's own domain.
Every client authenticates with a bearer token (OPERATIONS_MCP_TOKENS); the token's client
name is recorded in the audit log as the actor.

Run: uvicorn watchdog_backend.mcp_servers.operations:app --host 0.0.0.0 --port 8103
"""

from typing import Any
from uuid import UUID

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import UnknownDomainError, current_domain, use_domain
from watchdog_backend.governance import audit
from watchdog_backend.governance import service as gov
from watchdog_backend.governance.config import get_governance
from watchdog_backend.governance.executor import http_executor
from watchdog_backend.governance.impact import impact_snapshot
from watchdog_backend.investigation.actions import get_catalogue
from watchdog_backend.mcp_servers.common import READ, build_asgi, client_name, make_server

PORT = 8103


def _actor() -> gov.Actor:
    client = client_name()
    return gov.Actor(id=client, type="mcp_client", via=f"mcp:{client}")


async def _call(fn, *args, domain: str | None = None) -> Any:
    """Run a governance function on a fresh connection, with `domain` as the active pack. A
    refused or invalid request becomes a ToolError, so the client sees *why* (e.g. "needs a
    human approval first"); anything unexpected stays a generic error and is logged
    server-side."""

    def work():
        with use_domain(domain or current_domain()), get_engine().connect() as conn:
            return fn(conn, *args)

    try:
        return await anyio.to_thread.run_sync(work)
    except gov.GovernanceError as exc:
        raise ToolError(f"Refused ({exc.code}): {exc}") from exc
    except UnknownDomainError as exc:
        raise ToolError(str(exc)) from exc


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ToolError(f"'{value}' is not a valid request id") from exc


server = make_server(
    name="watchdog-operations",
    title="Intelligence WatchDog: Operations",
    instructions=(
        "Corrective actions for business operations (one domain pack per process, e.g. "
        "insurance_claims, procure_to_pay). You may list and propose actions and execute "
        "actions a person has approved. You cannot approve actions."
    ),
    port=PORT,
    scope="operations",
    tokens=lambda: get_settings().operations_mcp_tokens,
)


@server.tool(annotations=READ)
async def list_catalogue_actions(domain: str | None = None) -> list[dict[str, Any]]:
    """List the corrective actions allowed in a domain, with the policy that permits each
    and the roles that must approve it."""

    def actions(_conn) -> list[dict[str, Any]]:
        gov_cfg = get_governance()
        return [
            {
                "action_id": a.id,
                "title": a.title,
                "description": a.description,
                "policy_refs": a.policy_refs,
                "effort": a.effort,
                "approver_roles": gov_cfg.approvals[a.id].roles
                if a.id in gov_cfg.approvals
                else [],
            }
            for a in get_catalogue().actions.values()
        ]

    return await _call(actions, domain=domain)


@server.tool(annotations=READ)
async def list_action_requests(
    status: str | None = None, domain: str | None = None
) -> list[dict[str, Any]]:
    """List a domain's action requests, newest first. status: proposed, approved, rejected,
    executing, executed or failed."""
    rows = await _call(gov.list_requests, status, domain=domain)
    return [r.model_dump(mode="json", exclude={"operation", "impact"}) for r in rows]


@server.tool(annotations=READ)
async def get_action_request(request_id: str) -> dict[str, Any]:
    """Get one action request with its full audit trail."""
    rid = _uuid(request_id)
    req = await _call(gov.get, rid)
    trail = await _call(lambda c: audit.entries(c, rid))
    return {
        **req.model_dump(mode="json"),
        "audit": [e.model_dump(mode="json") for e in reversed(trail)],
    }


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def propose_action(
    action_id: str, rationale: str, domain: str | None = None
) -> dict[str, Any]:
    """Propose a corrective action from a domain's catalogue. Nothing changes until a person
    with the required role approves it in the web app."""
    actor = _actor()  # read the caller's identity in the request context, not the worker thread
    req = await _call(
        lambda c: gov.propose(c, actor, action_id, rationale, None, impact_snapshot(c, action_id)),
        domain=domain,
    )
    return req.model_dump(mode="json")


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
async def execute_action(request_id: str) -> dict[str, Any]:
    """Execute an action request that a person has approved. Fails (and is audited) if it has
    not been approved, was rejected, or was already executed."""
    actor = _actor()
    rid = _uuid(request_id)
    req = await _call(lambda c: gov.execute(c, actor, rid, http_executor()))
    return req.model_dump(mode="json")


@server.tool(annotations=READ)
async def verify_audit_log() -> dict[str, Any]:
    """Verify the audit log's hash chain (detects edited, inserted or deleted entries)."""
    return (await _call(audit.verify)).model_dump()


def build_app():
    return build_asgi(server, PORT, "operations-mcp")


app = build_app()

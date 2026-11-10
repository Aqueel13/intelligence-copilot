"""Turn a catalogue operation into a call on the enterprise system.

This is the only module that knows about the client's systems. Swapping the mock for a real
connector means changing the mapping and the HTTP client here, nothing else.
"""

from typing import Any
from uuid import UUID

import httpx2

from watchdog_backend.config import get_settings
from watchdog_backend.investigation.actions import Operation

# operation type -> enterprise resource
ROUTES = {
    "update_approval_routing": "approval-routing",
    "create_staffing_request": "staffing-requests",
    "create_change_request": "change-requests",
    "schedule_training": "training-sessions",
    "update_roster": "roster-shifts",
}


class ExecutionError(RuntimeError):
    pass


def http_executor(client: httpx2.Client | None = None):
    """Build an executor that POSTs to the enterprise API (idempotent per request id)."""

    def execute(request_id: UUID, op: Operation, actor: str) -> dict[str, Any]:
        resource = ROUTES.get(op.type)
        if resource is None:
            raise ExecutionError(f"No connector for operation '{op.type}'")
        s = get_settings()
        http = client or httpx2.Client(base_url=s.enterprise_api_url, timeout=15)
        try:
            r = http.post(
                f"/{resource}",
                headers={"X-Api-Key": s.enterprise_api_key},
                json={"reference": str(request_id), "requested_by": actor, "payload": op.params},
            )
        except httpx2.HTTPError as exc:
            raise ExecutionError(f"Enterprise system unreachable: {exc}") from exc
        finally:
            if client is None:
                http.close()
        if r.status_code >= 400:
            raise ExecutionError(f"Enterprise system returned {r.status_code}: {r.text[:200]}")
        record = r.json()
        return {"system": "claims-admin (mock)", "resource": resource, **record}

    return execute

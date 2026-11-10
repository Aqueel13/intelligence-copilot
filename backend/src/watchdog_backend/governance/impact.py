"""The what-if impact of an action, frozen when it is proposed, whatever door it came through,
so an approver always sees the evidence the proposal was based on."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.investigation.actions import evaluate_action, get_catalogue
from watchdog_backend.investigation.data import load_frames


def impact_snapshot(
    conn: Connection, action_id: str, investigation_id: UUID | None = None
) -> dict[str, Any] | None:
    action = get_catalogue().actions.get(action_id)
    if action is None:
        return None
    scope = ProcessQuery()
    if investigation_id:  # value it on the same slice the investigation looked at
        raw = conn.execute(
            text("SELECT scope FROM intelligence.investigations WHERE investigation_id = :id"),
            {"id": investigation_id},
        ).scalar_one_or_none()
        if raw:
            scope = ProcessQuery.model_validate(raw)
    frames = load_frames(conn, MetricsEngine(get_pack()), scope)
    impact = evaluate_action(frames, action, get_catalogue().economics)
    conn.rollback()  # reads only; leave the connection clean for the caller's transaction
    return {**impact.model_dump(), "scope": scope.model_dump(mode="json")}

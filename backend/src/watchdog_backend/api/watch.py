"""Watch API: monitor status, alerts, follow-ups, manual runs and the next-month simulator."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.identity.deps import require
from watchdog_backend.identity.service import Principal
from watchdog_backend.watch.engine import RunSummary, run_monitors
from watchdog_backend.watch.followups import FollowUp, follow_ups
from watchdog_backend.watch.simulate import SimulatedMonth, SimulationError, simulate_next_month

router = APIRouter(prefix="/watch", tags=["watch"])


class Alert(BaseModel):
    alert_id: UUID
    monitor_id: str
    segment: str
    severity: str
    status: str
    value: float
    threshold: float
    first_period: str
    last_period: str
    message: str
    opened_at: datetime
    updated_at: datetime
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    investigation_id: UUID | None


class WatchStatus(BaseModel):
    summary: RunSummary
    alerts: list[Alert]
    follow_ups: list[FollowUp]
    simulated_months: list[SimulatedMonth]
    last_run: dict[str, Any] | None


def _alerts(conn, include_resolved: bool = True) -> list[Alert]:
    rows = conn.execute(
        text(f"""SELECT * FROM intelligence.alerts WHERE domain = :d
                 {"" if include_resolved else "AND status <> 'resolved'"}
                 ORDER BY (status = 'resolved'), (severity = 'warning'), updated_at DESC
                 LIMIT 100"""),
        {"d": get_pack().domain},
    ).mappings()
    return [Alert(**r) for r in rows]


@router.get("", response_model=WatchStatus)
def status() -> WatchStatus:
    """Current evaluation of every monitor (computed now, read-only), alerts and follow-ups."""
    from watchdog_backend.analytics.metrics import MetricsEngine
    from watchdog_backend.watch.engine import evaluate, get_monitors, latest_period

    with get_engine().connect() as conn:
        engine = MetricsEngine(get_pack())
        period = latest_period(conn)
        evaluations = (
            [e for m in get_monitors() for e in evaluate(conn, engine, m, period)] if period else []
        )
        last = (
            conn.execute(
                text(
                    "SELECT * FROM intelligence.monitor_runs WHERE domain = :d "
                    "ORDER BY run_id DESC LIMIT 1"
                ),
                {"d": get_pack().domain},
            )
            .mappings()
            .one_or_none()
        )
        months = conn.execute(
            text(
                "SELECT month, claims, applied_actions, seed FROM intelligence.simulated_months "
                "WHERE domain = :d ORDER BY month"
            ),
            {"d": get_pack().domain},
        ).mappings()
        return WatchStatus(
            summary=RunSummary(
                period=period,
                evaluated=len(evaluations),
                opened=0,
                updated=0,
                resolved=0,
                duration_ms=0,
                evaluations=evaluations,
            ),
            alerts=_alerts(conn),
            follow_ups=follow_ups(conn),
            simulated_months=[SimulatedMonth(**m) for m in months],
            last_run=dict(last) if last else None,
        )


@router.post("/run", response_model=RunSummary, dependencies=[Depends(require("run_monitors"))])
def run_now() -> RunSummary:
    with get_engine().connect() as conn:
        return run_monitors(conn, "manual")


@router.post("/alerts/{alert_id}/acknowledge", response_model=Alert)
def acknowledge(
    alert_id: UUID, who: Annotated[Principal, Depends(require("acknowledge_alert"))]
) -> Alert:
    with get_engine().connect() as conn:
        row = (
            conn.execute(
                text("""UPDATE intelligence.alerts
                    SET status = 'acknowledged', acknowledged_by = :u, acknowledged_at = now(),
                        updated_at = now()
                    WHERE alert_id = :id AND status = 'open' RETURNING *"""),
                {"id": alert_id, "u": who.user.user_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Alert is not open")
        conn.commit()
        return Alert(**row)


class LinkIn(BaseModel):
    investigation_id: UUID


@router.post(
    "/alerts/{alert_id}/investigation",
    response_model=Alert,
    dependencies=[Depends(require("investigate"))],
)
def link_investigation(alert_id: UUID, body: LinkIn) -> Alert:
    with get_engine().connect() as conn:
        row = (
            conn.execute(
                text("""UPDATE intelligence.alerts SET investigation_id = :inv, updated_at = now()
                    WHERE alert_id = :id RETURNING *"""),
                {"id": alert_id, "inv": body.investigation_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        conn.commit()
        return Alert(**row)


class SimulationResult(BaseModel):
    month: SimulatedMonth
    run: RunSummary
    follow_ups: list[FollowUp]


@router.post(
    "/simulate-month",
    response_model=SimulationResult,
    dependencies=[Depends(require("simulate_month"))],
)
def simulate() -> SimulationResult:
    """DEMO ONLY: append one synthetic month with executed actions applied, then re-run the
    monitors so alerts and follow-ups reflect it."""
    with get_engine().connect() as conn:
        try:
            month = simulate_next_month(conn)
        except SimulationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        run = run_monitors(conn, "simulation")
        return SimulationResult(month=month, run=run, follow_ups=follow_ups(conn))

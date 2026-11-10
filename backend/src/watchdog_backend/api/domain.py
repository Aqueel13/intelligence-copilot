"""What the frontend needs to know about the active domain pack."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.api.metrics import get_engine
from watchdog_backend.db import get_session

router = APIRouter(tags=["domain"])


class FilterDimension(BaseModel):
    name: str
    label: str
    values: list[str] | None


class ActivityInfo(BaseModel):
    name: str
    label: str
    kind: str


class DomainInfo(BaseModel):
    domain: str
    display_name: str
    case_label: str
    currency: str
    timezone: str
    sla_name: str
    sla_hours: float
    senior_threshold: float
    filters: list[FilterDimension]
    activities: list[ActivityInfo]
    data_from: date | None
    data_to: date | None
    cases: int


@router.get("/domain", response_model=DomainInfo)
def domain_info(
    engine: Annotated[MetricsEngine, Depends(get_engine)],
    session: Annotated[Session, Depends(get_session)],
) -> DomainInfo:
    pack = engine.pack
    row = (
        session.execute(
            text(
                "SELECT min((opened_at AT TIME ZONE :tz)::date) AS data_from, "
                "max((opened_at AT TIME ZONE :tz)::date) AS data_to, count(*) AS cases "
                "FROM operational.cases WHERE domain = :d"
            ),
            {"tz": pack.case.timezone, "d": pack.domain},
        )
        .mappings()
        .one()
    )
    return DomainInfo(
        domain=pack.domain,
        display_name=pack.display_name,
        case_label=pack.case.label,
        currency=pack.case.currency,
        timezone=pack.case.timezone,
        sla_name=pack.sla.name,
        sla_hours=pack.sla.target_hours,
        senior_threshold=pack.approval.senior_threshold_inr,
        filters=[
            FilterDimension(name=d.name, label=d.label, values=list(d.values) if d.values else None)
            for d in engine.dimensions_for("cases")
            if d.name != "month"  # the period picker covers time
        ],
        activities=[
            ActivityInfo(name=a.name, label=a.label or a.name, kind=a.kind) for a in pack.activities
        ],
        **row,
    )

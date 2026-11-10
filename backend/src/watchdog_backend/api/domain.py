"""What the frontend needs to know about the domain packs and the active one."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.api.metrics import get_engine
from watchdog_backend.db import get_session
from watchdog_backend.domain.pack import OverviewConfig, available_domains, get_pack

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
    case_label_plural: str
    currency: str
    timezone: str
    sla_name: str
    sla_hours: float
    sla_start: str  # label of the activity that opens a case (e.g. "First Notice of Loss")
    sla_end: str
    senior_threshold: float | None
    system_of_record: str
    investigate_examples: list[str]
    knowledge_examples: list[str]
    overview: OverviewConfig
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
    labels = {a.name: a.label or a.name for a in pack.activities}
    return DomainInfo(
        domain=pack.domain,
        display_name=pack.display_name,
        case_label=pack.case.label,
        case_label_plural=pack.case.labels,
        currency=pack.case.currency,
        timezone=pack.case.timezone,
        sla_name=pack.sla.name,
        sla_hours=pack.sla.target_hours,
        sla_start=labels[pack.sla.start_activity],
        sla_end=labels[pack.sla.end_activity],
        senior_threshold=pack.approval.senior_threshold_inr if pack.approval else None,
        system_of_record=pack.ui.system_of_record,
        investigate_examples=pack.ui.investigate_examples,
        knowledge_examples=pack.ui.knowledge_examples,
        overview=pack.ui.overview,
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


class DomainSummary(BaseModel):
    domain: str
    display_name: str
    case_label_plural: str
    cases: int


@router.get("/domains", response_model=list[DomainSummary])
def domains(session: Annotated[Session, Depends(get_session)]) -> list[DomainSummary]:
    """Every enabled domain pack, default first (pick one with the X-Domain header)."""
    counts = dict(
        session.execute(
            text("SELECT domain, count(*) FROM operational.cases GROUP BY domain")
        ).all()
    )
    out = []
    for name in available_domains():
        pack = get_pack(name)
        out.append(
            DomainSummary(
                domain=name,
                display_name=pack.display_name,
                case_label_plural=pack.case.labels,
                cases=counts.get(name, 0),
            )
        )
    return out

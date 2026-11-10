"""Domain pack loading and validation.

A domain pack is trusted, developer-authored configuration. We still validate it strictly,
because metric expressions and dimension names end up inside SQL.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from watchdog_backend.config import get_settings

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseConfig(_Strict):
    label: str
    id_prefix: str
    currency: str
    timezone: str


class SlaConfig(_Strict):
    name: str
    target_hours: float = Field(gt=0)
    start_activity: str
    end_activity: str


class CalendarConfig(_Strict):
    workdays: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    start: str
    end: str


class AmountBand(_Strict):
    label: str
    max: float | None = None


class Dimension(_Strict):
    name: str
    label: str
    source: Literal["attribute", "amount_band", "opened_month"]
    values: list[str] | None = None
    bands: list[AmountBand] | None = None

    @field_validator("name")
    @classmethod
    def _identifier(cls, v: str) -> str:
        if not IDENTIFIER.match(v):
            raise ValueError(f"dimension name {v!r} must be a lowercase identifier")
        return v

    @model_validator(mode="after")
    def _bands_valid(self) -> "Dimension":
        if self.source == "amount_band":
            if not self.bands or self.bands[-1].max is not None:
                raise ValueError("amount_band needs bands ending with an open-ended band")
            maxes = [b.max for b in self.bands[:-1]]
            if any(m is None for m in maxes) or maxes != sorted(maxes):
                raise ValueError("amount bands must have increasing upper bounds")
        return self


class Activity(_Strict):
    name: str
    label: str | None = None
    kind: Literal["work", "customer_wait"] = "work"
    applies_to: dict[str, str] | None = None


class Delegation(_Strict):
    band_min_inr: float
    band_max_inr: float
    delegate_role: str
    status: Literal["enabled", "permitted_not_enabled", "not_permitted"]
    requires: str | None = None


class ApprovalConfig(_Strict):
    senior_threshold_inr: float
    senior_target_hours: float
    delegation: Delegation | None = None


class FeedbackConfig(_Strict):
    survey_delay_days: tuple[int, int]
    csat_scale: tuple[int, int]
    nps_scale: tuple[int, int]


class Metric(_Strict):
    name: str
    base: Literal["cases", "events", "feedback"]
    label: str
    description: str
    expression: str
    # SQL aggregate giving the number of rows the value is based on (for low-sample warnings).
    sample: str = "count(*)"
    unit: Literal["count", "ratio", "days", "hours", "inr", "score_1_5", "nps"]

    @field_validator("expression", "sample")
    @classmethod
    def _no_statement_chars(cls, v: str) -> str:
        # Expressions are trusted, but fail fast on anything that is clearly not an aggregate.
        if ";" in v or "--" in v or "/*" in v:
            raise ValueError("metric expression must be a single SQL aggregate expression")
        return v


class DomainPack(_Strict):
    domain: str
    display_name: str
    version: int
    case: CaseConfig
    sla: SlaConfig
    calendar: CalendarConfig
    dimensions: list[Dimension]
    activities: list[Activity]
    approval: ApprovalConfig
    feedback: FeedbackConfig
    metrics: dict[str, Metric]

    @model_validator(mode="after")
    def _cross_references(self) -> "DomainPack":
        names = {a.name for a in self.activities}
        for ref in (self.sla.start_activity, self.sla.end_activity):
            if ref not in names:
                raise ValueError(f"SLA activity {ref!r} is not a declared activity")
        dims = [d.name for d in self.dimensions]
        if len(dims) != len(set(dims)):
            raise ValueError("duplicate dimension names")
        return self

    def dimension(self, name: str) -> Dimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise KeyError(name)


def load_pack(path: Path) -> DomainPack:
    raw = yaml.safe_load((path / "pack.yaml").read_text(encoding="utf-8"))
    metrics_raw = yaml.safe_load((path / "metrics.yaml").read_text(encoding="utf-8"))["metrics"]
    raw["metrics"] = {name: {"name": name, **spec} for name, spec in metrics_raw.items()}
    return DomainPack.model_validate(raw)


@lru_cache
def get_pack(domain: str | None = None) -> DomainPack:
    settings = get_settings()
    return load_pack(Path(settings.domain_packs_dir) / (domain or settings.domain_pack))

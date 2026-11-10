"""Domain pack loading and validation.

A domain pack is trusted, developer-authored configuration. We still validate it strictly,
because metric expressions and dimension names end up inside SQL.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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
    label: str  # what one case is called ("claim", "invoice")
    plural: str | None = None  # defaults to label + "s"
    id_prefix: str
    currency: str
    timezone: str

    @property
    def labels(self) -> str:
        return self.plural or f"{self.label}s"


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


class Outcome(_Strict):
    """A case-level flag the investigation compares across segments (besides `breached`):
    a loop or detour, read from per-case activity counts."""

    label: str  # rate label, e.g. "additional-documents rate"
    mechanism: str  # noun phrase, e.g. "an additional-documents request"
    activity: str
    when: Literal["present", "repeated"]  # the activity occurs at all / more than once


class AnalysisConfig(_Strict):
    """What the investigation engine looks at. Everything domain-specific it needs is here."""

    dimensions: list[str]  # scanned for segment effects
    controls: list[str]  # confounders checked for every segment effect
    outcomes: dict[str, Outcome] = Field(default_factory=dict)
    wait_targets: dict[str, float] = Field(default_factory=dict)  # activity -> hours
    late_handoff_hour: int = Field(15, ge=0, le=23)  # "late" handoffs start at this hour

    @field_validator("outcomes")
    @classmethod
    def _outcome_names(cls, v: dict[str, Outcome]) -> dict[str, Outcome]:
        for name in v:
            if not IDENTIFIER.match(name) or name == "breached":
                raise ValueError(
                    f"outcome name {name!r} must be an identifier other than 'breached'"
                )
        return v


class Tile(_Strict):
    """A KPI tile on the Overview page. `note` may use {n} (the value's sample size) and
    {secondary} (the formatted value of `secondary`, another metric)."""

    metric: str
    label: str
    note: str | None = None
    secondary: str | None = None


class OverviewConfig(_Strict):
    spotlight: Tile | None = None  # the fourth tile of the headline row
    tiles: list[Tile] = Field(default_factory=list)  # the row under the headline
    breakdown_dimensions: dict[str, str] = Field(default_factory=dict)  # name -> short label
    breakdown_metrics: dict[str, str] = Field(default_factory=dict)  # metric -> short label


class UiConfig(_Strict):
    """Wording, examples and Overview layout for the frontend."""

    investigate_examples: list[str] = Field(default_factory=list)
    knowledge_examples: list[str] = Field(default_factory=list)
    system_of_record: str = "the system of record"  # what executed actions change
    overview: OverviewConfig = Field(default_factory=OverviewConfig)


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
    # Who and what, for LLM prompts: "an Indian general insurer's motor and health claims"
    subject: str
    version: int
    case: CaseConfig
    sla: SlaConfig
    calendar: CalendarConfig
    dimensions: list[Dimension]
    activities: list[Activity]
    analysis: AnalysisConfig
    ui: UiConfig = Field(default_factory=UiConfig)
    approval: ApprovalConfig | None = None
    feedback: FeedbackConfig | None = None
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
        a = self.analysis
        for ref in [*a.dimensions, *a.controls]:
            if ref not in dims:
                raise ValueError(f"analysis dimension {ref!r} is not a declared dimension")
        for ref in [*(o.activity for o in a.outcomes.values()), *a.wait_targets]:
            if ref not in names:
                raise ValueError(f"analysis activity {ref!r} is not a declared activity")
        o = self.ui.overview
        tiles = [*o.tiles, *([o.spotlight] if o.spotlight else [])]
        for ref in [
            *(t.metric for t in tiles),
            *(t.secondary for t in tiles if t.secondary),
            *o.breakdown_metrics,
        ]:
            if ref not in self.metrics:
                raise ValueError(f"ui.overview metric {ref!r} is not a declared metric")
        for ref in o.breakdown_dimensions:
            if ref not in dims:
                raise ValueError(f"ui.overview dimension {ref!r} is not a declared dimension")
        return self

    @property
    def outcome_labels(self) -> dict[str, str]:
        """Every outcome the investigation compares, with its rate label."""
        return {"breached": "SLA breach rate"} | {
            k: o.label for k, o in self.analysis.outcomes.items()
        }

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


# --------------------------------------------------------------- the active pack
#
# Several packs run side by side. The pack in use is per request (the API sets it from the
# X-Domain header) or per job (the watcher, the CLIs), via this context variable. Code that
# starts threads copies the context, so the pack follows the work.

_current: ContextVar[str | None] = ContextVar("domain_pack", default=None)


def available_domains() -> list[str]:
    """Enabled packs (settings.domain_packs) that exist on disk, default pack first."""
    s = get_settings()
    root = Path(s.domain_packs_dir)
    names = [s.domain_pack] + [d.strip() for d in s.domain_packs.split(",") if d.strip()]
    return [d for d in dict.fromkeys(names) if (root / d / "pack.yaml").is_file()]


def current_domain() -> str:
    return _current.get() or get_settings().domain_pack


@contextmanager
def use_domain(domain: str) -> Iterator[str]:
    """Make `domain` the active pack for the code inside the block."""
    if domain not in available_domains():
        raise UnknownDomainError(domain)
    token = _current.set(domain)
    try:
        yield domain
    finally:
        _current.reset(token)


class UnknownDomainError(ValueError):
    def __init__(self, domain: str) -> None:
        super().__init__(
            f"Unknown or disabled domain pack {domain!r}. "
            f"Available: {', '.join(available_domains())}"
        )


@lru_cache
def _load(domain: str) -> DomainPack:
    return load_pack(Path(get_settings().domain_packs_dir) / domain)


def get_pack(domain: str | None = None) -> DomainPack:
    return _load(domain or current_domain())


def pack_file(*parts: str, domain: str | None = None) -> Path:
    """A file inside a pack's directory (the active pack by default)."""
    return Path(get_settings().domain_packs_dir) / (domain or current_domain()) / Path(*parts)

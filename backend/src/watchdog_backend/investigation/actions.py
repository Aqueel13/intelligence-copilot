"""Action catalogue (from the domain pack) and the what-if engine that values each action.

The engine works on the scoped event log. For each claim it removes the time an action would
eliminate, recomputes the cycle time, and counts breaches avoided. It is an approximation:
removing hours does not re-run the working calendar (e.g. a saved Friday afternoon is counted
as saved hours, not as a skipped weekend). That limitation is stated with every result.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from watchdog_backend.domain.pack import current_domain, pack_file
from watchdog_backend.investigation.data import Frames

WEEKDAYS = {"Mon": 1, "Tue": 2, "Wed": 3, "Thu": 4, "Fri": 5, "Sat": 6, "Sun": 7}
METHOD_NOTE = (
    "Expected-value what-if on the observed event log: the time an action would remove is "
    "subtracted from each affected claim's cycle time and the SLA is re-checked. Calendar "
    "effects (e.g. weekends skipped) are not re-simulated, so impact may be understated."
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Lever(_Strict):
    kind: Literal["cap_wait", "remove_repeats", "cap_handoff_wait"]
    activity: str | None = None
    target_hours: float | None = None
    filters: dict[str, list[str]] = Field(default_factory=dict)
    always: list[str] = Field(default_factory=list)
    repeats: list[str] = Field(default_factory=list)
    fraction: Literal["all", "excess"] = "all"
    baseline_dimension: str | None = None
    # The loop outcome (pack analysis.outcomes) whose excess rate `fraction: excess` measures.
    outcome: str | None = None
    weekday: str | None = None
    from_hour: int | None = None

    @model_validator(mode="after")
    def _excess_needs_outcome(self) -> "Lever":
        if self.fraction == "excess" and not (self.outcome and self.baseline_dimension):
            raise ValueError("fraction: excess needs `outcome` and `baseline_dimension`")
        return self


class AnnualCost(_Strict):
    basis: str
    fixed_inr: float | None = None
    fixed_hours: float | None = None
    per_affected_claim_hours: float | None = None
    rate: str | None = None


class Operation(_Strict):
    type: str
    params: dict[str, object] = Field(default_factory=dict)


class FollowUp(_Strict):
    metric: str
    expect: Literal["below", "above"]
    target: float
    filters: dict[str, list[str]] = Field(default_factory=dict)


class Action(_Strict):
    id: str
    title: str
    description: str
    policy_refs: list[str]
    effort: Literal["low", "medium", "high"]
    lever: Lever
    annual_cost: AnnualCost
    follow_up: FollowUp | None = None
    operation: Operation


class Economics(BaseModel):
    """`cost_per_breach_inr` plus any number of hourly rates (`<name>_per_hour_inr`) that
    action costs refer to by name."""

    model_config = ConfigDict(extra="allow", frozen=True)
    cost_per_breach_inr: float

    @model_validator(mode="after")
    def _rates(self) -> "Economics":
        for k, v in (self.model_extra or {}).items():
            if not k.endswith("_per_hour_inr") or not isinstance(v, int | float):
                raise ValueError(f"economics: {k!r} must be a number named *_per_hour_inr")
        return self

    @property
    def rates(self) -> dict[str, float]:
        return {k: float(v) for k, v in (self.model_extra or {}).items()}


class ActionCatalogue(_Strict):
    economics: Economics
    actions: dict[str, Action]


@lru_cache
def _catalogue(domain: str) -> ActionCatalogue:
    raw = yaml.safe_load(pack_file("actions.yaml", domain=domain).read_text("utf-8"))
    raw["actions"] = {k: {"id": k, **v} for k, v in raw["actions"].items()}
    return ActionCatalogue.model_validate(raw)


def get_catalogue() -> ActionCatalogue:
    """The active pack's action catalogue (cached per pack)."""
    return _catalogue(current_domain())


# ----------------------------------------------------------------------------- what-if


class ActionImpact(BaseModel):
    action_id: str
    title: str
    affected_claims: float
    hours_removed: float
    breaches_now: int
    breaches_avoided: float
    breach_rate_now: float
    breach_rate_after: float
    annual_breaches_avoided: float
    annual_benefit_inr: float
    annual_cost_inr: float
    annual_net_inr: float
    cost_basis: str
    assumptions: dict[str, float]
    annual_basis: str = ""  # which months the annual figures are scaled from, and why
    method: str = METHOD_NOTE


def _case_mask(cases: pd.DataFrame, filters: dict[str, list[str]]) -> pd.Series:
    mask = pd.Series(True, index=cases.index)
    for dim, values in filters.items():
        mask &= cases[dim].isin(values)
    return mask


def _excess_fraction(
    frames: Frames, lever: Lever, outcome: str, population: Frames | None = None
) -> float:
    """Share of the segment's loops above the rate seen in comparable claims.

    If the scope IS the segment (e.g. a broker-only investigation valuing a broker action),
    there are no comparable claims in scope; the baseline then comes from the population.
    Without one, the excess is unknown and reported as 0 rather than guessed."""
    if lever.fraction == "all" or not lever.baseline_dimension or not outcome:
        return 1.0
    cases = frames.cases
    seg = _case_mask(cases, lever.filters)
    rate_in = cases.loc[seg, outcome].mean()
    if not seg.all():
        rate_base = cases.loc[~seg, outcome].mean()
    elif population is not None:
        pop = population.cases
        rate_base = pop.loc[~_case_mask(pop, lever.filters), outcome].mean()
    else:
        return 0.0
    if not rate_in or pd.isna(rate_in) or pd.isna(rate_base):
        return 0.0
    return float(max(0.0, (rate_in - rate_base) / rate_in))


def removed_hours(
    frames: Frames, lever: Lever, population: Frames | None = None
) -> tuple[pd.Series, float]:
    """Hours removed per case (index = case_id), and the fraction applied."""
    ev, cases = frames.events, frames.cases
    in_scope = set(cases.loc[_case_mask(cases, lever.filters), "case_id"])
    ev = ev[ev["case_id"].isin(in_scope)]

    if lever.kind == "cap_wait":
        sel = ev[ev["activity"] == lever.activity]
        cut = (sel["wait_hours"] - (lever.target_hours or 0)).clip(lower=0)
        return cut.groupby(sel["case_id"]).sum(), 1.0

    if lever.kind == "remove_repeats":
        sel = ev[
            ev["activity"].isin(lever.always)
            | (ev["activity"].isin(lever.repeats) & (ev["occurrence"] > 1))
        ]
        hours = (sel["wait_hours"] + sel["work_hours"]).groupby(sel["case_id"]).sum()
        return hours, _excess_fraction(frames, lever, lever.outcome or "", population)

    # cap_handoff_wait: a late handoff on `weekday` still waits until the next working morning
    # (no weekend work is assumed), but then only for a typical queue: the backlog that builds
    # up behind late-week handoffs is what the action removes, not the weekend itself.
    day = WEEKDAYS[lever.weekday or "Fri"]
    late = (ev["handoff_isodow"] == day) & (ev["handoff_hour"] >= (lever.from_hour or 15))
    typical = ev[(ev["handoff_isodow"] != day) & ev["handoff_isodow"].between(1, 5)]
    median = typical.groupby("activity")["wait_hours"].median()
    sel = ev[late]
    local = sel["handoff_at"].dt.tz_convert(frames.timezone)
    days_to_next_workday = (8 - sel["handoff_isodow"]).where(sel["handoff_isodow"] >= 5, 1)
    next_start = (
        local.dt.normalize() + pd.to_timedelta(days_to_next_workday, "D") + pd.Timedelta(hours=9)
    )
    allowed = (next_start - local).dt.total_seconds() / 3600 + sel["activity"].map(median).fillna(0)
    cut = (sel["wait_hours"] - allowed).clip(lower=0)
    return cut.groupby(sel["case_id"]).sum(), 1.0


ACTIVE_SHARE = 0.25  # a month counts as affected when it avoids ≥ this share of the peak month


@dataclass(frozen=True)
class AnnualBasis:
    months: list[str]  # the months the annual figures are scaled from
    kind: str  # whole_window | trailing_year | since_onset
    note: str


def annual_basis(per_month: pd.Series, all_months: list[str], whole_months: float) -> AnnualBasis:
    """Which months to annualise an action's effect from.

    Spreading the period's total over the whole window is right for a problem that runs
    through it, and for a seasonal one seen over a full year; it understates a problem that
    began recently and is still running (three weeks of a new problem averaged over 18 months
    looks six times smaller than it is). So: find the run of consecutive affected months at
    the end of the window. If it covers the window → the whole window. If the same calendar
    months a year earlier were affected too → a season → the latest 12 months (one cycle).
    Otherwise → a change that began at the start of that run → its current run-rate.
    """
    whole = AnnualBasis(all_months, "whole_window", f"{whole_months:.0f} months of data annualised")
    counts = per_month.reindex(all_months, fill_value=0.0)
    peak = float(counts.max()) if len(counts) else 0.0
    if peak <= 0 or len(all_months) < 2:
        return whole
    active = counts >= ACTIVE_SHARE * peak
    run: list[str] = []
    for month in reversed(all_months):
        if not active.loc[month]:
            break
        run.insert(0, month)
    if not run or len(run) == len(all_months):
        return whole

    def year_before(m: str) -> str:
        return f"{int(m[:4]) - 1}{m[4:]}"

    earlier = [year_before(m) for m in run if year_before(m) in active.index]
    if earlier and any(active.loc[m] for m in earlier):
        last12 = all_months[-12:]
        return AnnualBasis(
            last12,
            "trailing_year",
            f"seen a year earlier too: annualised from the latest {len(last12)} months",
        )
    return AnnualBasis(
        run,
        "since_onset",
        f"began in {run[0]}: annualised from the {len(run)} months since (current run-rate)",
    )


def evaluate_action(
    frames: Frames, action: Action, economics: Economics, population: Frames | None = None
) -> ActionImpact:
    cases = frames.cases.set_index("case_id")
    hours, fraction = removed_hours(frames, action.lever, population)
    hours = hours.reindex(cases.index, fill_value=0.0)
    breached = cases["cycle_hours"] > frames.sla_hours
    fixed = breached & (cases["cycle_hours"] - hours <= frames.sla_hours)
    affected = int((hours > 0).sum())
    avoided = float(fixed.sum()) * fraction
    n = len(cases) or 1

    # Annualise from the right months (see annual_basis): whole window, a season, or a
    # change still running.
    month = cases["month"]
    all_months = sorted(month.dropna().unique())
    basis = annual_basis(fixed.groupby(month).sum().astype(float), all_months, frames.months)
    if basis.kind == "whole_window":
        annualise = 12 / frames.months
        avoided_basis, affected_basis = avoided, affected * fraction
    else:
        in_basis = month.isin(basis.months)
        annualise = 12 / len(basis.months)
        avoided_basis = float((fixed & in_basis).sum()) * fraction
        affected_basis = float(((hours > 0) & in_basis).sum()) * fraction

    rates = economics.rates
    c = action.annual_cost
    cost = c.fixed_inr or 0.0
    if c.fixed_hours and c.rate:
        cost += c.fixed_hours * rates[c.rate]
    if c.per_affected_claim_hours and c.rate:
        cost += c.per_affected_claim_hours * affected_basis * annualise * rates[c.rate]

    benefit = avoided_basis * annualise * economics.cost_per_breach_inr
    return ActionImpact(
        action_id=action.id,
        title=action.title,
        affected_claims=affected * fraction,
        hours_removed=float(hours.sum()) * fraction,
        breaches_now=int(breached.sum()),
        breaches_avoided=avoided,
        breach_rate_now=float(breached.mean()) if len(cases) else 0.0,
        breach_rate_after=float((breached.sum() - avoided) / n),
        annual_breaches_avoided=avoided_basis * annualise,
        annual_benefit_inr=benefit,
        annual_cost_inr=cost,
        annual_net_inr=benefit - cost,
        cost_basis=c.basis,
        assumptions={
            "cost_per_breach_inr": economics.cost_per_breach_inr,
            "months_of_data": round(frames.months, 1),
            "fraction_of_loops_removed": round(fraction, 3),
            "annualised_from_months": float(len(basis.months)),
        },
        annual_basis=basis.note,
    )

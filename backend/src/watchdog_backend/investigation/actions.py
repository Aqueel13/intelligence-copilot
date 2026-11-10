"""Action catalogue (from the domain pack) and the what-if engine that values each action.

The engine works on the scoped event log. For each claim it removes the time an action would
eliminate, recomputes the cycle time, and counts breaches avoided. It is an approximation:
removing hours does not re-run the working calendar (e.g. a saved Friday afternoon is counted
as saved hours, not as a skipped weekend). That limitation is stated with every result.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import get_pack
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
    weekday: str | None = None
    from_hour: int | None = None


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


class Economics(_Strict):
    cost_per_breach_inr: float
    staff_cost_per_hour_inr: float
    team_lead_cost_per_hour_inr: float


class ActionCatalogue(_Strict):
    economics: Economics
    actions: dict[str, Action]


@lru_cache
def get_catalogue() -> ActionCatalogue:
    pack = get_pack()
    raw = yaml.safe_load(
        (Path(get_settings().domain_packs_dir) / pack.domain / "actions.yaml").read_text("utf-8")
    )
    raw["actions"] = {k: {"id": k, **v} for k, v in raw["actions"].items()}
    return ActionCatalogue.model_validate(raw)


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
    if lever.fraction == "all" or not lever.baseline_dimension:
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
        outcome = "doc_requested" if lever.always else "rework"
        return hours, _excess_fraction(frames, lever, outcome, population)

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
    annualise = 12 / frames.months

    rates = {
        "staff_cost_per_hour_inr": economics.staff_cost_per_hour_inr,
        "team_lead_cost_per_hour_inr": economics.team_lead_cost_per_hour_inr,
    }
    c = action.annual_cost
    cost = c.fixed_inr or 0.0
    if c.fixed_hours and c.rate:
        cost += c.fixed_hours * rates[c.rate]
    if c.per_affected_claim_hours and c.rate:
        cost += c.per_affected_claim_hours * affected * fraction * annualise * rates[c.rate]

    benefit = avoided * annualise * economics.cost_per_breach_inr
    return ActionImpact(
        action_id=action.id,
        title=action.title,
        affected_claims=affected * fraction,
        hours_removed=float(hours.sum()) * fraction,
        breaches_now=int(breached.sum()),
        breaches_avoided=avoided,
        breach_rate_now=float(breached.mean()) if len(cases) else 0.0,
        breach_rate_after=float((breached.sum() - avoided) / n),
        annual_breaches_avoided=avoided * annualise,
        annual_benefit_inr=benefit,
        annual_cost_inr=cost,
        annual_net_inr=benefit - cost,
        cost_basis=c.basis,
        assumptions={
            "cost_per_breach_inr": economics.cost_per_breach_inr,
            "months_of_data": round(frames.months, 1),
            "fraction_of_loops_removed": round(fraction, 3),
        },
    )

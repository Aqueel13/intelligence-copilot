"""Typed checks the planner may request, and their deterministic execution.

The LLM chooses checks from a fixed menu; code runs them and writes the summary text the LLM
then reads. Segment checks automatically get confounder (stratified) checks against the
other main dimensions, whether or not the planner asked for them.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection

from watchdog_backend.analytics.process import ActivityAnalysis
from watchdog_backend.investigation.data import Frames
from watchdog_backend.investigation.scan import OUTCOMES, WEEKDAY_NAMES
from watchdog_backend.investigation.stats import (
    StratifiedComparison,
    compare_proportions,
    stratified_difference,
)
from watchdog_backend.knowledge.retrieval import Retriever

# Dimensions used as controls when a segment effect is tested.
CONTROLS = ("amount_band", "line_of_business", "channel")


class SegmentCheck(BaseModel):
    type: Literal["segment"] = "segment"
    dimension: str
    value: str
    outcome: Literal["breached", "doc_requested", "rework"] = "breached"


class ActivityWaitCheck(BaseModel):
    type: Literal["activity_wait"] = "activity_wait"
    activity: str


class WeekdayCheck(BaseModel):
    type: Literal["weekday_handoff"] = "weekday_handoff"
    weekday: Literal["Mon", "Tue", "Wed", "Thu", "Fri"] = "Fri"


class PolicyCheck(BaseModel):
    type: Literal["policy"] = "policy"
    query: str


Check = Annotated[
    SegmentCheck | ActivityWaitCheck | WeekdayCheck | PolicyCheck, Field(discriminator="type")
]


class PolicyExcerpt(BaseModel):
    doc_key: str
    title: str
    version: str
    section: str
    content: str


class EvidenceItem(BaseModel):
    check: Check
    ok: bool
    summary: str  # deterministic plain-language result shown to the LLM and the user
    data: dict[str, object] = Field(default_factory=dict)
    confounders: list[StratifiedComparison] = Field(default_factory=list)
    policy: list[PolicyExcerpt] = Field(default_factory=list)
    auto: bool = False  # added by the engine, not requested by the planner

    @property
    def explained_by(self) -> list[str]:
        return [c.control for c in self.confounders if c.explained_by_control]


class EvidenceContext:
    def __init__(
        self,
        conn: Connection,
        frames: Frames,
        activities: ActivityAnalysis,
        retriever: Retriever,
        dimension_values: dict[str, list[str]],
        targets: dict[str, float],
    ) -> None:
        self.conn = conn
        self.frames = frames
        self.activities = activities
        self.retriever = retriever
        self.dimension_values = dimension_values
        self.targets = targets  # activity -> wait target (hours), from the domain pack


def run_check(ctx: EvidenceContext, check: Check, auto: bool = False) -> EvidenceItem:
    try:
        if isinstance(check, SegmentCheck):
            return _segment(ctx, check, auto)
        if isinstance(check, ActivityWaitCheck):
            return _activity(ctx, check, auto)
        if isinstance(check, WeekdayCheck):
            return _weekday(ctx, check, auto)
        return _policy(ctx, check, auto)
    except Exception as exc:  # a bad check must not sink the investigation
        return EvidenceItem(check=check, ok=False, summary=f"Check failed: {exc}", auto=auto)


def _segment(ctx: EvidenceContext, c: SegmentCheck, auto: bool) -> EvidenceItem:
    allowed = ctx.dimension_values.get(c.dimension)
    if allowed is None:
        return EvidenceItem(
            check=c,
            ok=False,
            auto=auto,
            summary=(
                f"Unknown dimension '{c.dimension}'. Allowed: {', '.join(ctx.dimension_values)}"
            ),
        )
    if c.value not in allowed:
        return EvidenceItem(
            check=c,
            ok=False,
            auto=auto,
            summary=f"Unknown value '{c.value}' for {c.dimension}. Allowed: {', '.join(allowed)}",
        )
    df = ctx.frames.cases.assign(_y=ctx.frames.cases[c.outcome].astype(float))
    mask = df[c.dimension] == c.value
    cmp = compare_proportions(mask, df["_y"], f"{c.dimension}={c.value}")
    controls = [
        stratified_difference(df, mask, "_y", ctl, f"{c.dimension}={c.value}")
        for ctl in CONTROLS
        if ctl != c.dimension
    ]
    label = OUTCOMES[c.outcome]
    sig = "statistically significant" if cmp.significant else "NOT statistically significant"
    sample = f" Small sample: only {cmp.n_in} cases." if cmp.low_sample else ""
    parts = [
        f"{label[0].upper()}{label[1:]}: {cmp.rate_in:.1%} for {c.dimension}='{c.value}' "
        f"(n={cmp.n_in}) vs {cmp.rate_out:.1%} for the rest (n={cmp.n_out}); difference "
        f"{cmp.difference:+.1%}, {sig} (p={cmp.p_value:.3g}).{sample}"
    ]
    parts += [ctl.note for ctl in controls]
    data: dict[str, object] = cmp.model_dump()
    if c.outcome != "breached":  # mechanism: does this loop go with more breaches?
        mechanism = _loop_mechanism(ctx, c.outcome)
        parts.append(mechanism["text"])
        data["mechanism"] = mechanism
    return EvidenceItem(
        check=c,
        ok=True,
        auto=auto,
        summary=" ".join(parts),
        data=data,
        confounders=controls,
    )


def _loop_mechanism(ctx: EvidenceContext, outcome: str) -> dict[str, object]:
    cases = ctx.frames.cases
    has = cases[outcome].astype(bool)
    cmp = compare_proportions(has, cases["breached"].astype(float), outcome)
    extra_days = (
        float(cases.loc[has, "cycle_hours"].mean() - cases.loc[~has, "cycle_hours"].mean()) / 24
    )
    label = {"doc_requested": "an additional-documents request", "rework": "verification rework"}
    text = (
        f"Mechanism: claims with {label[outcome]} breach the SLA {cmp.rate_in:.0%} of the time "
        f"vs {cmp.rate_out:.0%} without (p={cmp.p_value:.2g}) and take {extra_days:.1f} days "
        f"longer on average."
    )
    return {
        "breach_with": cmp.rate_in,
        "breach_without": cmp.rate_out,
        "p_value": cmp.p_value,
        "extra_days": extra_days,
        "text": text,
    }


def _activity(ctx: EvidenceContext, c: ActivityWaitCheck, auto: bool) -> EvidenceItem:
    stats = next((a for a in ctx.activities.internal if a.activity == c.activity), None)
    if stats is None:
        names = ", ".join(a.activity for a in ctx.activities.internal)
        return EvidenceItem(
            check=c,
            ok=False,
            auto=auto,
            summary=(
                f"Unknown or non-internal activity '{c.activity}'. Internal activities: {names}"
            ),
        )
    target = ctx.targets.get(c.activity)
    over = ""
    if target is not None:
        ev = ctx.frames.events
        waits = ev.loc[ev["activity"] == c.activity, "wait_hours"]
        over = (
            f" Target is {target:g} hours; {(waits > target).mean():.0%} of instances wait longer."
        )
    without = f"{stats.breach_rate_without:.0%}" if stats.breach_rate_without is not None else "n/a"
    summary = (
        f"'{c.activity}': mean wait {stats.mean_wait_hours:.1f}h, median "
        f"{stats.median_wait_hours:.1f}h, 90th percentile {stats.p90_wait_hours:.1f}h; "
        f"{stats.share_of_internal_wait:.0%} of all internal waiting; repeated in "
        f"{stats.repeat_rate:.1%} of its claims. Claims including it breach "
        f"{stats.breach_rate_with:.0%} vs {without} without. "
        f"{'It is flagged as a bottleneck.' if stats.is_bottleneck else 'Not a bottleneck.'}{over}"
    )
    return EvidenceItem(check=c, ok=True, auto=auto, summary=summary, data=stats.model_dump())


def _weekday(ctx: EvidenceContext, c: WeekdayCheck, auto: bool) -> EvidenceItem:
    ev = ctx.frames.events.dropna(subset=["handoff_isodow"])
    ev = ev[ev["handoff_isodow"].between(1, 5)]
    day = {v: k for k, v in WEEKDAY_NAMES.items()}[c.weekday]
    on_day = ev[ev["handoff_isodow"] == day]
    late = on_day[on_day["handoff_hour"] >= 15]
    others = ev[ev["handoff_isodow"] != day]
    cases = ctx.frames.cases
    hit = cases["case_id"].isin(set(late["case_id"]))
    cmp = compare_proportions(hit, cases["breached"].astype(float), "late handoff")
    extra_days = (
        float(cases.loc[hit, "cycle_hours"].mean() - cases.loc[~hit, "cycle_hours"].mean()) / 24
    )
    summary = (
        f"Handoffs on {c.weekday}: mean wait {on_day['wait_hours'].mean():.1f}h "
        f"(n={len(on_day)}); from 15:00 {late['wait_hours'].mean():.1f}h (n={len(late)}); "
        f"other weekdays {others['wait_hours'].mean():.1f}h. Late handoffs affect "
        f"{late['case_id'].nunique()} claims. Mechanism: claims with a late {c.weekday} "
        f"handoff breach the SLA {cmp.rate_in:.0%} of the time vs {cmp.rate_out:.0%} without "
        f"(p={cmp.p_value:.2g}) and take {extra_days:.1f} days longer on average."
    )
    return EvidenceItem(
        check=c,
        ok=True,
        auto=auto,
        summary=summary,
        data={
            "mean_wait": float(on_day["wait_hours"].mean()),
            "late_mean_wait": float(late["wait_hours"].mean()),
            "other_days_mean_wait": float(others["wait_hours"].mean()),
            "late_claims": int(late["case_id"].nunique()),
        },
    )


def _policy(ctx: EvidenceContext, c: PolicyCheck, auto: bool) -> EvidenceItem:
    hits = ctx.retriever.search(ctx.conn, c.query, k=3, method="hybrid")
    excerpts = [
        PolicyExcerpt(
            doc_key=h.doc_key,
            title=h.title,
            version=h.version,
            section=h.section,
            content=h.content,
        )
        for h in hits
    ]
    summary = " | ".join(
        f"{h.doc_key} §{h.section}: {' '.join(h.content.split())[:400]}" for h in hits
    )
    return EvidenceItem(
        check=c,
        ok=bool(hits),
        auto=auto,
        summary=summary or "No matching policy text.",
        policy=excerpts,
    )


def describe_check(check: Check) -> str:
    if isinstance(check, SegmentCheck):
        return f"Compare {OUTCOMES[check.outcome]} for {check.dimension} = {check.value}"
    if isinstance(check, ActivityWaitCheck):
        return f"Waiting time before {check.activity}"
    if isinstance(check, WeekdayCheck):
        return f"Waiting time after {check.weekday} handoffs"
    return f"Policy: {check.query}"

"""Deterministic signal scan: everything worth investigating, before any LLM is involved.

The scan sweeps the scoped data and returns *signals*, each with the numbers behind it and a
plain-language statement. The planner turns signals into hypotheses; it does not have to
discover patterns on its own.

Signal kinds
- segment:    a dimension value whose rate (breach, documents requested, rework) differs
              significantly from the rest (two-proportion z-test, p < 0.01, |diff| ≥ 5 points),
              plus small segments with large differences flagged as low-sample
- bottleneck: an activity flagged by the process analysis
- weekday:    waiting time after handoffs on one weekday far above the others
- trend:      the breach rate moving over the months in scope
"""

from typing import Literal

import pandas as pd
from pydantic import BaseModel
from scipy import stats

from watchdog_backend.analytics.process import ActivityAnalysis
from watchdog_backend.investigation.data import Frames
from watchdog_backend.investigation.stats import compare_proportions

MIN_DIFF = 0.05
OUTCOMES = {
    "breached": "SLA breach rate",
    "doc_requested": "additional-documents rate",
    "rework": "verification rework rate",
}
WEEKDAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


class Signal(BaseModel):
    id: str
    kind: Literal["segment", "bottleneck", "weekday", "trend"]
    statement: str
    strength: float  # for ordering: larger = more important
    data: dict[str, object]


class Overview(BaseModel):
    cases: int
    breach_rate: float
    breaches: int
    mean_cycle_days: float
    sla_days: float
    months: float


class ScanResult(BaseModel):
    overview: Overview
    signals: list[Signal]


def _segment_signals(frames: Frames, dimensions: list[str]) -> list[Signal]:
    cases = frames.cases
    out: list[Signal] = []
    for outcome, label in OUTCOMES.items():
        y = cases[outcome].astype(float)
        for dim in dimensions:
            for value in sorted(cases[dim].dropna().unique(), key=str):
                mask = cases[dim] == value
                cmp = compare_proportions(mask, y, f"{dim}={value}")
                big = abs(cmp.difference) >= MIN_DIFF
                if not big or not (cmp.significant or cmp.low_sample):
                    continue
                if cmp.difference < 0:
                    continue  # report the worse side only: "health higher" == "motor lower"
                direction = "higher" if cmp.difference > 0 else "lower"
                caveat = (
                    f" Only {cmp.n_in} cases, and the difference is "
                    f"{'not ' if not cmp.significant else ''}statistically significant."
                    if cmp.low_sample
                    else ""
                )
                out.append(
                    Signal(
                        id=f"seg:{outcome}:{dim}:{value}",
                        kind="segment",
                        statement=(
                            f"{label[0].upper()}{label[1:]} for "
                            f"{dim.replace('_', ' ')} '{value}' is "
                            f"{cmp.rate_in:.1%} vs {cmp.rate_out:.1%} for the rest "
                            f"({direction} by {abs(cmp.difference):.1%}, n={cmp.n_in}).{caveat}"
                        ),
                        strength=abs(cmp.difference)
                        * (0.3 if cmp.low_sample else 1.0)
                        * (1.0 if outcome == "breached" else 0.8),
                        data={
                            "outcome": outcome,
                            "dimension": dim,
                            "value": str(value),
                            **cmp.model_dump(),
                        },
                    )
                )
    return out


def _bottleneck_signals(activities: ActivityAnalysis) -> list[Signal]:
    out = []
    for a in activities.internal:
        if not a.is_bottleneck:
            continue
        without = (
            f" vs {a.breach_rate_without:.0%} for claims without it"
            if a.breach_rate_without is not None
            else ""
        )
        out.append(
            Signal(
                id=f"bottleneck:{a.activity}",
                kind="bottleneck",
                statement=(
                    f"'{a.activity}' is a bottleneck: claims wait {a.mean_wait_hours:.0f} hours on "
                    f"average before it (median {a.median_wait_hours:.0f}h, 90th percentile "
                    f"{a.p90_wait_hours:.0f}h), {a.share_of_internal_wait:.0%} of all internal "
                    f"waiting. Claims that pass through it breach "
                    f"{a.breach_rate_with:.0%}{without}."
                ),
                strength=a.share_of_internal_wait + 0.5,
                data=a.model_dump(),
            )
        )
    return out


def _weekday_signals(frames: Frames) -> list[Signal]:
    ev = frames.events.dropna(subset=["handoff_isodow"])
    ev = ev[ev["handoff_isodow"].between(1, 5)]
    if ev.empty:
        return []
    by_day = ev.groupby("handoff_isodow")["wait_hours"].mean()
    out = []
    for day, mean in by_day.items():
        others = by_day.drop(day)
        if len(others) and mean > 2 * others.median():
            late = ev[(ev["handoff_isodow"] == day) & (ev["handoff_hour"] >= 15)]["wait_hours"]
            name = WEEKDAY_NAMES[int(day)]
            out.append(
                Signal(
                    id=f"weekday:{name}",
                    kind="weekday",
                    statement=(
                        f"Work handed over on {name} waits {mean:.0f} hours on average before the "
                        f"next activity starts, vs {others.median():.0f} hours on other weekdays; "
                        f"handoffs on {name} from 15:00 wait {late.mean():.0f} hours."
                    ),
                    strength=min(mean / others.median(), 5) / 10,
                    data={
                        "weekday": name,
                        "mean_wait_hours": float(mean),
                        "other_days_median_wait_hours": float(others.median()),
                        "late_handoff_mean_wait_hours": float(late.mean()),
                    },
                )
            )
    return out


def _trend_signal(frames: Frames) -> list[Signal]:
    monthly = frames.cases.groupby("month")["breached"].agg(["mean", "size"])
    if len(monthly) < 4:
        return []
    fit = stats.linregress(range(len(monthly)), monthly["mean"].to_numpy())
    if fit.pvalue >= 0.1:
        return []
    direction = "rising" if fit.slope > 0 else "falling"
    first, last = monthly.index[0], monthly.index[-1]
    return [
        Signal(
            id="trend:breach",
            kind="trend",
            statement=(
                f"The SLA breach rate is {direction} by about {abs(fit.slope):.1%} per month "
                f"({monthly['mean'].iloc[0]:.0%} in {first} to {monthly['mean'].iloc[-1]:.0%} in "
                f"{last}; p={fit.pvalue:.2f})."
            ),
            strength=abs(fit.slope) * 3,
            data={
                "slope_per_month": float(fit.slope),
                "p_value": float(fit.pvalue),
                "monthly": {k: float(v) for k, v in monthly["mean"].items()},
            },
        )
    ]


def scan(frames: Frames, activities: ActivityAnalysis, dimensions: list[str]) -> ScanResult:
    cases = frames.cases
    signals = (
        _bottleneck_signals(activities)
        + _segment_signals(frames, dimensions)
        + _weekday_signals(frames)
        + _trend_signal(frames)
    )
    signals.sort(key=lambda s: s.strength, reverse=True)
    return ScanResult(
        overview=Overview(
            cases=len(cases),
            breach_rate=float(cases["breached"].mean()) if len(cases) else 0.0,
            breaches=int(cases["breached"].sum()),
            mean_cycle_days=float(cases["cycle_hours"].mean() / 24) if len(cases) else 0.0,
            sla_days=frames.sla_hours / 24,
            months=frames.months,
        ),
        signals=signals,
    )


def describe_dimension_values(cases: pd.DataFrame, dimensions: list[str]) -> dict[str, list[str]]:
    return {d: sorted(map(str, cases[d].dropna().unique())) for d in dimensions}

"""Small, explicit statistics: proportion tests and stratified (confounder) comparisons."""

import math

import pandas as pd
from pydantic import BaseModel
from scipy import stats

MIN_STRATUM = 30  # both sides of a stratum need this many cases to be compared
LOW_SAMPLE = 100


class ProportionComparison(BaseModel):
    segment: str
    rate_in: float
    rate_out: float
    difference: float  # rate_in - rate_out
    n_in: int
    n_out: int
    p_value: float
    significant: bool  # p < 0.01
    low_sample: bool


def compare_proportions(
    mask: pd.Series, outcome: pd.Series, segment: str, alpha: float = 0.01
) -> ProportionComparison:
    """Two-proportion z-test of `outcome` between rows where `mask` is true and false."""
    inside, outside = outcome[mask], outcome[~mask]
    n1, n2 = len(inside), len(outside)
    p1 = float(inside.mean()) if n1 else 0.0
    p2 = float(outside.mean()) if n2 else 0.0
    if n1 == 0 or n2 == 0:
        p_value = 1.0
    else:
        pooled = (inside.sum() + outside.sum()) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        p_value = 1.0 if se == 0 else float(2 * stats.norm.sf(abs((p1 - p2) / se)))
    return ProportionComparison(
        segment=segment,
        rate_in=p1,
        rate_out=p2,
        difference=p1 - p2,
        n_in=n1,
        n_out=n2,
        p_value=p_value,
        significant=p_value < alpha,
        low_sample=n1 < LOW_SAMPLE,
    )


class StratifiedComparison(BaseModel):
    segment: str
    control: str
    raw_difference: float
    adjusted_difference: float | None  # weighted within-stratum difference
    strata_used: list[str]
    explained_by_control: bool  # the difference largely disappears within strata
    note: str


def stratified_difference(
    df: pd.DataFrame, mask: pd.Series, outcome: str, control: str, segment: str
) -> StratifiedComparison:
    """Compare the segment with the rest *within* each level of a control variable.

    If the difference shrinks to less than a third of the raw difference (or reverses), the
    raw difference is mostly explained by the control (a confounder), not the segment.
    """
    raw = float(df.loc[mask, outcome].mean() - df.loc[~mask, outcome].mean())
    diffs, weights, used = [], [], []
    for level, part in df.groupby(control, observed=True):
        m = mask.loc[part.index]
        if m.sum() < MIN_STRATUM or (~m).sum() < MIN_STRATUM:
            continue
        diffs.append(part.loc[m, outcome].mean() - part.loc[~m, outcome].mean())
        weights.append(int(m.sum()))
        used.append(str(level))
    if not weights:
        return StratifiedComparison(
            segment=segment,
            control=control,
            raw_difference=raw,
            adjusted_difference=None,
            strata_used=[],
            explained_by_control=False,
            note=f"Not enough cases in comparable {control} groups to control for it.",
        )
    adjusted = float(sum(d * w for d, w in zip(diffs, weights, strict=True)) / sum(weights))
    explained = abs(raw) >= 0.02 and (adjusted * raw <= 0 or abs(adjusted) < abs(raw) / 3)
    note = (
        f"Within the same {control}, the difference is {adjusted:+.1%} (vs {raw:+.1%} overall)"
        + (f": it is mostly explained by {control}." if explained else ": it persists.")
    )
    return StratifiedComparison(
        segment=segment,
        control=control,
        raw_difference=raw,
        adjusted_difference=adjusted,
        strata_used=used,
        explained_by_control=explained,
        note=note,
    )

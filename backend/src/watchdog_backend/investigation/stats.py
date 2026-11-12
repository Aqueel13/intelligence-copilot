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
    adjusted_p_value: float | None = None  # Mantel-Haenszel test within the strata


def family_alpha(comparisons: int, alpha: float = 0.01) -> float:
    """Bonferroni: the per-comparison threshold that keeps the chance of ANY false positive
    among `comparisons` tests at `alpha`. A scan makes dozens of segment comparisons; at 1%
    each, one of them is "significant" by chance every few scans."""
    return alpha / max(1, comparisons)


def mantel_haenszel_p(df: pd.DataFrame, mask: pd.Series, outcome: str, strata: list) -> float:
    """Cochran-Mantel-Haenszel test of a binary outcome: segment vs rest, within strata."""
    num = var = 0.0
    for part in strata:
        m = mask.loc[part.index]
        n, n1 = len(part), int(m.sum())
        if n < 2 or n1 in (0, n):
            continue
        k = float(part[outcome].sum())
        num += float(part.loc[m, outcome].sum()) - n1 * k / n
        var += n1 * (n - n1) * k * (n - k) / (n * n * (n - 1))
    if var <= 0:
        return 1.0
    return float(stats.chi2.sf(num * num / var, 1))


def stratified_difference(
    df: pd.DataFrame,
    mask: pd.Series,
    outcome: str,
    control: str,
    segment: str,
    alpha: float | None = None,
) -> StratifiedComparison:
    """Compare the segment with the rest *within* each level of a control variable.

    If the difference shrinks to less than a third of the raw difference (or reverses), the
    raw difference is mostly explained by the control (a confounder), not the segment. With
    `alpha`, what remains must also be significant within the strata (Mantel-Haenszel):
    a difference partly explained by the control, with a remainder that chance can explain,
    is not evidence of a cause.
    """
    raw = float(df.loc[mask, outcome].mean() - df.loc[~mask, outcome].mean())
    diffs, weights, used, parts = [], [], [], []
    for level, part in df.groupby(control, observed=True):
        m = mask.loc[part.index]
        if m.sum() < MIN_STRATUM or (~m).sum() < MIN_STRATUM:
            continue
        diffs.append(part.loc[m, outcome].mean() - part.loc[~m, outcome].mean())
        weights.append(int(m.sum()))
        used.append(str(level))
        parts.append(part)
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
    p_adj = mantel_haenszel_p(df, mask, outcome, parts)
    chance = (
        alpha is not None
        and not explained
        and abs(raw) >= 0.02
        and abs(adjusted) <= 0.8 * abs(raw)  # the control explains a real part of it…
        and p_adj >= alpha  # …and chance can explain the rest
    )
    if explained:
        verdict = f": it is mostly explained by {control}."
    elif chance:
        verdict = (
            f": part of it is explained by {control}, and the remainder is not significant "
            f"(p={p_adj:.2g}), so it may be chance."
        )
    else:
        verdict = ": it persists."
    note = (
        f"Within the same {control}, the difference is {adjusted:+.1%} (vs {raw:+.1%} overall)"
        + verdict
    )
    return StratifiedComparison(
        segment=segment,
        control=control,
        raw_difference=raw,
        adjusted_difference=adjusted,
        strata_used=used,
        explained_by_control=explained or chance,
        note=note,
        adjusted_p_value=p_adj,
    )

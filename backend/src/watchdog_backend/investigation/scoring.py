"""Score an investigation against the planted ground truth (Insurance Claims pack).

A planted cause counts as found if a *supported* hypothesis carries evidence that targets it.
A decoy counts as accepted if a *supported* hypothesis rests only on the decoy's segment.
This is what M7's evaluation aggregates across runs and models.
"""

from pydantic import BaseModel

from watchdog_backend.investigation.evidence import (
    ActivityWaitCheck,
    EvidenceItem,
    SegmentCheck,
    WeekdayCheck,
)

HIGH_BANDS = {"₹2L–₹5L", "> ₹5L"}


class Score(BaseModel):
    found: dict[str, bool]  # RC1..RC4
    decoys_accepted: dict[str, bool]  # DC1, DC2
    recall: float
    decoy_errors: int


def _targets(e: EvidenceItem) -> set[str]:
    c, out = e.check, set()
    if isinstance(c, ActivityWaitCheck) and c.activity == "Senior Approval":
        out.add("RC1")
    if isinstance(c, SegmentCheck):
        if c.dimension == "amount_band" and c.value in HIGH_BANDS:
            out.add("RC1")
        if c.dimension == "channel" and c.value == "broker":
            out.add("RC2")
        if c.dimension == "team" and c.value == "Team B":
            out.add("RC3")
        if c.dimension == "line_of_business" and c.value == "health" and c.outcome == "breached":
            out.add("DC1")
        if c.dimension == "region" and c.value == "Pune":
            out.add("DC2")
    if isinstance(c, WeekdayCheck) and c.weekday == "Fri":
        out.add("RC4")
    return out


def score(hypotheses: list) -> Score:
    found = dict.fromkeys(("RC1", "RC2", "RC3", "RC4"), False)
    decoys = dict.fromkeys(("DC1", "DC2"), False)
    for h in hypotheses:
        if h.verdict != "supported":
            continue
        targets = set().union(*(_targets(e) for e in h.evidence if e.ok)) if h.evidence else set()
        for rc in found:
            found[rc] |= rc in targets
        real = targets & set(found)
        for dc in decoys:
            # Accepting a decoy = supporting a hypothesis whose only target is the decoy.
            decoys[dc] |= dc in targets and not real
    return Score(
        found=found,
        decoys_accepted=decoys,
        recall=sum(found.values()) / len(found),
        decoy_errors=sum(decoys.values()),
    )

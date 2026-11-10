"""Score an investigation against a pack's planted ground truth.

A planted cause counts as found if a *supported* hypothesis carries evidence that targets it.
A decoy counts as accepted if a *supported* hypothesis rests only on the decoy's segment.
What "targets" means is declared per pack in evaluation/investigations.yaml (`ground_truth`):
ids starting RC are planted causes, ids starting DC are decoys.
"""

from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from watchdog_backend.domain.pack import pack_file
from watchdog_backend.investigation.evidence import (
    ActivityWaitCheck,
    EvidenceItem,
    SegmentCheck,
    WeekdayCheck,
)


class Target(BaseModel):
    """One kind of evidence that points at a planted cause or decoy."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    check: Literal["segment", "activity_wait", "weekday_handoff"]
    dimension: str | None = None
    values: list[str] = Field(default_factory=list)
    outcome: str | None = None  # segment checks: only this outcome (default: any)
    activity: str | None = None
    weekday: str | None = None

    def matches(self, e: EvidenceItem) -> bool:
        c = e.check
        if self.check == "segment" and isinstance(c, SegmentCheck):
            return (
                c.dimension == self.dimension
                and c.value in self.values
                and (self.outcome is None or c.outcome == self.outcome)
            )
        if self.check == "activity_wait" and isinstance(c, ActivityWaitCheck):
            return c.activity == self.activity
        if self.check == "weekday_handoff" and isinstance(c, WeekdayCheck):
            return c.weekday == self.weekday
        return False


class TruthItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str
    targets: list[Target]


def parse_ground_truth(raw: dict[str, Any]) -> dict[str, TruthItem]:
    return {k: TruthItem.model_validate(v) for k, v in raw.items()}


def evaluation_spec(domain: str | None = None) -> dict[str, Any]:
    """The pack's investigation benchmark (evaluation/investigations.yaml)."""
    path = pack_file("evaluation", "investigations.yaml", domain=domain)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def pack_ground_truth(domain: str | None = None) -> dict[str, TruthItem]:
    return parse_ground_truth(evaluation_spec(domain)["ground_truth"])


class Score(BaseModel):
    found: dict[str, bool]  # RC… → found
    decoys_accepted: dict[str, bool]  # DC… → accepted
    recall: float
    decoy_errors: int


def _targets(e: EvidenceItem, truth: dict[str, TruthItem]) -> set[str]:
    return {key for key, item in truth.items() if any(t.matches(e) for t in item.targets)}


def score(hypotheses: list, truth: dict[str, TruthItem]) -> Score:
    found = {k: False for k in truth if k.startswith("RC")}
    decoys = {k: False for k in truth if k.startswith("DC")}
    for h in hypotheses:
        if h.verdict != "supported":
            continue
        targets = set().union(*(_targets(e, truth) for e in h.evidence if e.ok))
        for rc in found:
            found[rc] |= rc in targets
        real = targets & set(found)
        for dc in decoys:
            # Accepting a decoy = supporting a hypothesis whose only target is the decoy.
            decoys[dc] |= dc in targets and not real
    return Score(
        found=found,
        decoys_accepted=decoys,
        recall=sum(found.values()) / len(found) if found else 0.0,
        decoy_errors=sum(decoys.values()),
    )

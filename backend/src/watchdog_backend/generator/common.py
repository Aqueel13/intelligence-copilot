"""Building blocks shared by the synthetic-data generators.

Every generator follows the same design: each case draws ALL of its random numbers up front,
so it can be re-simulated with one planted cause switched off using identical randomness. The
difference is an exact counterfactual ("this case breached *because of* RC1"). Durations follow
the pack's working calendar, so nights and weekends show up as waiting time exactly as they
would in a real event log. Ground truth never reaches the database the copilot can see.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from watchdog_backend.domain.pack import DomainPack

FEEDBACK_COLUMNS = ("case_id", "sent_at", "responded_at", "csat", "nps", "comment")


def lognormal(median: float, sigma: float, z: float) -> float:
    return median * math.exp(sigma * z)


def choose(weights: dict[str, float], u: float) -> str:
    total = sum(weights.values())
    acc = 0.0
    for key, w in weights.items():
        acc += w / total
        if u < acc:
            return key
    return next(reversed(weights))


def hours(td: timedelta) -> float:
    return td.total_seconds() / 3600


@dataclass(frozen=True)
class SimEvent:
    activity: str
    resource: str
    start: datetime
    end: datetime
    wait_hours: float  # calendar hours since the previous activity ended


@dataclass
class SimResult:
    events: list[SimEvent]
    triggered: set[str]

    @property
    def closed_at(self) -> datetime:
        return self.events[-1].end

    @property
    def cycle_hours(self) -> float:
        return (self.closed_at - self.events[0].start).total_seconds() / 3600

    def count(self, activity: str) -> int:
        return sum(e.activity == activity for e in self.events)


@dataclass
class GeneratedDataset:
    """A generated dataset: what gets loaded (cases, events, feedback) and what never does
    (truth: per-case counterfactuals). Subclasses add the domain's ground-truth summary."""

    pack: DomainPack
    config: object
    cases: pd.DataFrame
    events: pd.DataFrame
    feedback: pd.DataFrame  # may include private _true_* columns; never load those
    truth: pd.DataFrame
    causes: tuple[str, ...] = ()

    def public_feedback(self) -> pd.DataFrame:
        if self.feedback.empty:
            return pd.DataFrame(columns=list(FEEDBACK_COLUMNS))
        return self.feedback.drop(columns=[c for c in self.feedback if c.startswith("_")])

    def joined_truth(self) -> pd.DataFrame:
        """Truth joined with the cases, attributes as columns."""
        t = self.truth.merge(self.cases, on="case_id")
        attrs = pd.json_normalize(t["attributes"].tolist())
        return pd.concat([t.drop(columns="attributes"), attrs], axis=1)

    def root_causes(self, t: pd.DataFrame) -> dict[str, dict[str, object]]:
        n_breached = int(t["breached"].sum())
        out = {}
        for cause in self.causes:
            affected = t[t[f"{cause}_triggered"]]
            attributable = int(t[f"{cause}_breach_attributable"].sum())
            out[cause] = {
                "cases_affected": len(affected),
                "mean_delay_hours_when_affected": round(
                    float(affected[f"{cause}_delay_hours"].mean()), 1
                )
                if len(affected)
                else 0.0,
                "breaches_attributable": attributable,
                "share_of_breaches": round(attributable / n_breached, 3) if n_breached else 0.0,
            }
        return out

    def summary(self) -> dict[str, object]:
        raise NotImplementedError

    def write(self, out_dir: str | Path) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        cases = self.cases.assign(attributes=self.cases["attributes"].map(json.dumps))
        cases.to_csv(out / "cases.csv", index=False)
        self.events.to_csv(out / "events.csv", index=False)
        self.public_feedback().to_csv(out / "feedback.csv", index=False)
        self.truth.to_csv(out / "ground_truth_cases.csv", index=False)
        (out / "ground_truth.json").write_text(
            json.dumps(self.summary(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )

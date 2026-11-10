"""Checks on LLM prose: every number in the summary must appear in the computed facts."""

import re

from pydantic import BaseModel

# 31.0% · 1,548 · ₹12.3L · 96 hours · 0.83 — captures the number and an optional unit marker
_NUMBER = re.compile(r"(₹)?\s?(\d[\d,]*(?:\.\d+)?)\s?(%|L\b|lakh|Cr\b|crore)?", re.IGNORECASE)
TRIVIAL = {0, 1, 2, 3, 4, 5, 6, 10, 12, 24, 100}  # small counts, "5-day SLA", "24 hours", etc.


class NumberCheck(BaseModel):
    numbers_found: int
    unverified: list[str]

    @property
    def ok(self) -> bool:
        return not self.unverified


def _values(text: str) -> list[tuple[str, float]]:
    out = []
    for m in _NUMBER.finditer(text):
        raw = m.group(0).strip()
        try:
            value = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(3) or "").lower()
        if unit in ("l", "lakh"):
            value *= 1e5
        elif unit in ("cr", "crore"):
            value *= 1e7
        out.append((raw, value))
    return out


def verify_numbers(summary: str, facts: str) -> NumberCheck:
    """A number is verified if the facts contain the same value (±1% or ±0.15 absolute)."""
    known = [v for _, v in _values(facts)]
    found = _values(summary)
    unverified = []
    for raw, value in found:
        if value in TRIVIAL or (1990 <= value <= 2100):  # years
            continue
        if not any(abs(value - k) <= max(0.15, 0.01 * abs(k)) for k in known):
            unverified.append(raw)
    return NumberCheck(numbers_found=len(found), unverified=unverified)

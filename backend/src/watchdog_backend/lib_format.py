"""Plain-text formatting of metric values (mirrors the frontend's formatting)."""


def format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "ratio":
        return f"{value:.1%}"
    if unit in ("hours",):
        return f"{value:.1f} h"
    if unit == "days":
        return f"{value:.1f} days"
    if unit == "inr":
        return f"₹{value / 1e5:.1f}L" if value >= 1e5 else f"₹{value:,.0f}"
    if unit == "score_1_5":
        return f"{value:.2f}"
    if unit == "nps":
        return f"{value:.0f}"
    return f"{value:,.0f}"

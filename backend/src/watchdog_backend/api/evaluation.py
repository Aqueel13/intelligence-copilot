"""Model comparison from the saved evaluation runs (all packs; updated as runs are added)."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from watchdog_backend.config import get_settings
from watchdog_backend.evaluation.summary import comparison

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/comparison")
def model_comparison() -> dict[str, Any]:
    """Per pack and model: investigation quality against planted truth, grounded Q&A, speed
    and token use, merged across every saved run (later re-runs replace earlier results)."""
    return comparison(Path(get_settings().evaluation_results_dir))

"""Model comparison as data: the saved evaluation runs, merged and aggregated per pack and model.

The same records and definitions as docs/evaluation_report.md (`report._load`): later runs
replace earlier results for the same (pack, suite, model, seed, question). Read at request time,
so a new run directory shows up without a restart.
"""

from pathlib import Path
from typing import Any

from watchdog_backend.evaluation.report import _cause_labels, _failure_kind, _load, _mean


def run_dirs(root: Path) -> list[Path]:
    """Saved runs in chronological order (directories are named by date)."""
    if not root.is_dir():
        return []
    return sorted(
        d
        for d in root.iterdir()
        if d.is_dir()
        and (d / "results.jsonl").is_file()
        and (d / "meta.json").is_file()
        and not d.name.startswith("smoke")
    )


def _investigations(rs: list[dict]) -> dict[str, Any]:
    ok = [r for r in rs if r["ok"]]
    limited = sum(_failure_kind(r).startswith("rate") for r in rs if not r["ok"])
    decoy_runs = [r for r in ok if r["decoys"]]
    ovs = [o for r in ok for o in r["overrides"]]
    found_cells: dict[str, list[bool]] = {}
    for r in ok:
        for rc in r["expected"]:
            found_cells.setdefault(rc, []).append(bool(r["found"].get(rc)))
    remedied = [v for r in ok for v in r["remedied"].values()]
    return {
        "runs": len(rs),
        "completed": len(ok),
        "rate_limited": limited,
        "failed": len(rs) - len(ok) - limited,
        "mean_recall": _mean([r["recall"] for r in ok]),
        "all_found": sum(r["recall"] == 1 for r in ok),
        "decoy_runs": len(decoy_runs),
        "decoys_accepted": sum(bool(r["decoys_accepted"]) for r in decoy_runs),
        "remedy_rate": sum(remedied) / len(remedied) if remedied else None,
        "downgrades": sum(o["model_said"] == "supported" for o in ovs),
        "coverage_added": sum(r["coverage_added"] for r in ok),
        "unverified_numbers": sum(len(r["numbers_unverified"]) for r in ok),
        "mean_duration_s": _mean([r["duration_s"] for r in ok]),
        "mean_llm_calls": _mean([r["llm_calls"] for r in ok]),
        "mean_tokens": _mean([r["input_tokens"] + r["output_tokens"] for r in ok]),
        "causes": {rc: {"found": sum(v), "of": len(v)} for rc, v in sorted(found_cells.items())},
        "seeds": sorted({r["seed"] for r in rs}),
    }


def _qa(rs: list[dict]) -> dict[str, Any] | None:
    if not rs:
        return None
    ok = [r for r in rs if r["ok"]]
    ans = [r for r in ok if r["answerable"]]
    una = [r for r in ok if not r["answerable"]]
    found = [r for r in ans if r["found"]]
    return {
        "answerable": len(ans),
        "answered_rate": len(found) / len(ans) if ans else None,
        "cites_relevant": _mean([float(r["cites_relevant"]) for r in found]),
        "grounded": _mean([float(r["grounded"]) for r in found]),
        "model_citation_accuracy": _mean([r["model_citation_accuracy"] for r in found]),
        "declined": sum(not r["found"] for r in una),
        "unanswerable": len(una),
        "errors": len(rs) - len(ok),
        "mean_generation_s": _mean([r["generation_ms"] / 1000 for r in ok]),
    }


def comparison(root: Path) -> dict[str, Any]:
    dirs = run_dirs(root)
    if not dirs:
        return {"runs": [], "domains": []}
    records, metas, superseded = _load(dirs)
    domains = []
    for domain in sorted({r["domain"] for r in records}):
        recs = [r for r in records if r["domain"] == domain]
        models = sorted({r["model"] for r in recs if r["suite"] in ("investigation", "qa")})
        rows = []
        for m in models:
            inv = [r for r in recs if r["suite"] == "investigation" and r["model"] == m]
            qa = [r for r in recs if r["suite"] == "qa" and r["model"] == m]
            last = max((r.get("_run", "") for r in inv + qa), default="")
            rows.append(
                {
                    "model": m,
                    "provider": m.split(":", 1)[0],
                    "investigations": _investigations(inv) if inv else None,
                    "qa": _qa(qa),
                    "last_run": last,
                }
            )
        domains.append(
            {
                "domain": domain,
                "cause_labels": _cause_labels(domain),
                "models": rows,
                "questions": sorted(
                    {r["question_id"] for r in recs if r["suite"] == "investigation"}
                ),
            }
        )
    return {
        "runs": [
            {
                "name": d.name,
                "started": m.get("started"),
                "finished": m.get("finished"),
                "domain": m.get("domain"),
                "models": m.get("models", []),
                "seeds": m.get("seeds", []),
                "suites": m.get("suites", []),
            }
            for d, m in zip(dirs, metas, strict=True)
        ],
        "superseded": len(superseded),
        "domains": domains,
    }

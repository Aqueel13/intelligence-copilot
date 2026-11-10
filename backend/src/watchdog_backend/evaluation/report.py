"""Build docs/evaluation_report.md from one or more results directories."""

import json
import statistics
from collections import defaultdict
from pathlib import Path


def _key(r: dict) -> tuple:
    if r["suite"] == "investigation":
        return ("investigation", r["model"], r["seed"], r["question_id"])
    if r["suite"] == "qa":
        return ("qa", r["model"], r["question"])
    if r["suite"] == "whatif":
        return ("whatif", r["seed"], r["action"])
    return ("retrieval", r["method"])


def _load(dirs: list[Path]) -> tuple[list[dict], list[dict], list[dict]]:
    """Merge runs in the order given: a later run replaces an earlier result for the same
    (suite, model, seed, question). Replaced results are returned so the report lists them."""
    merged: dict[tuple, dict] = {}
    superseded: list[dict] = []
    metas = []
    for d in dirs:
        metas.append(json.loads((d / "meta.json").read_text()))
        for line in (d / "results.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if _key(r) in merged:
                    superseded.append(merged[_key(r)])
                merged[_key(r)] = r
    return list(merged.values()), metas, superseded


def _failure_kind(r: dict) -> str:
    err = r.get("error", "")
    if "429" in err or "RateLimit" in err:
        return "rate limit (provider quota)"
    if "did not finish within" in err or "Timeout" in err:
        return "timeout"
    return "model or system error"


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def _num(x: float | None, digits: int = 1) -> str:
    return "–" if x is None else f"{x:,.{digits}f}"


def build_report(dirs: list[Path]) -> str:
    records, metas, superseded = _load(dirs)
    inv = [r for r in records if r["suite"] == "investigation"]
    qa = [r for r in records if r["suite"] == "qa"]
    retrieval = [r for r in records if r["suite"] == "retrieval"]
    whatif = [r for r in records if r["suite"] == "whatif"]
    models = sorted({r["model"] for r in inv + qa})
    seeds = sorted({r["seed"] for r in inv + whatif})
    lines: list[str] = []
    w = lines.append

    w("# Evaluation report\n")
    w(
        f"Generated from {len(dirs)} run(s): "
        + ", ".join(f"`{m['started']}`" for m in metas)
        + ". "
        f"Models: {', '.join(f'`{m}`' for m in models) or '–'}. Generator seeds: {seeds}.\n"
    )
    w(
        "All results are measured, not targets. Failed runs are reported, not dropped. "
        "Every investigation is scored against the generator's planted ground truth "
        "(`investigation/scoring.py`): a planted cause counts as found only if a hypothesis "
        "that targets it is *supported*; a decoy counts as accepted if a supported hypothesis "
        "rests only on it.\n"
    )

    # ---- investigation summary per model
    w("## 1. Investigations\n")
    if inv:
        w(
            "Quality columns cover completed runs only. *Rate-limited* runs never reached the "
            "model's reasoning (the provider refused the request), so they are counted apart "
            "from runs the model itself failed.\n"
        )
        w(
            "| Model | Runs | Completed | Rate-limited | Other failures | Mean recall "
            "| All expected causes found | Decoys accepted "
            "| Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |"
        )
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for m in models:
            rs = [r for r in inv if r["model"] == m]
            ok = [r for r in rs if r["ok"]]
            decoy_runs = [r for r in ok if r["decoys"]]
            limited = sum(_failure_kind(r).startswith("rate") for r in rs if not r["ok"])
            w(
                f"| `{m}` | {len(rs)} | {len(ok)} | {limited} | {len(rs) - len(ok) - limited} "
                f"| {_pct(_mean([r['recall'] for r in ok]))} "
                f"| {sum(r['recall'] == 1 for r in ok)}/{len(ok)} "
                f"| {sum(bool(r['decoys_accepted']) for r in decoy_runs)}/{len(decoy_runs)} runs "
                f"| {sum(len(r['overrides']) for r in ok)} "
                f"| {_num(_mean([len(r['numbers_unverified']) for r in ok]), 2)} "
                f"| {_num(_mean([r['duration_s'] for r in ok]), 0)} s "
                f"| {_num(_mean([r['llm_calls'] for r in ok]), 1)} "
                f"| {_num(_mean([r['input_tokens'] + r['output_tokens'] for r in ok]), 0)} |"
            )
        w("")
        w("### By question\n")
        w(
            "| Question | Model | Recall by seed | Decoys accepted | Remedy recommended for each cause found |"
        )
        w("|---|---|---|---|---|")
        for qid in sorted({r["question_id"] for r in inv}):
            for m in models:
                rs = sorted(
                    [r for r in inv if r["question_id"] == qid and r["model"] == m],
                    key=lambda r: r["seed"],
                )
                if not rs:
                    continue
                recall = ", ".join(
                    f"{r['seed']}: {_pct(r['recall'])}" if r["ok"] else f"{r['seed']}: error"
                    for r in rs
                )
                decoys = sum(bool(r.get("decoys_accepted")) for r in rs if r["ok"])
                remedied = [v for r in rs if r["ok"] for v in r["remedied"].values()]
                w(
                    f"| `{qid}` | `{m}` | {recall} | {decoys}/{sum(r['ok'] for r in rs)} "
                    f"| {sum(remedied)}/{len(remedied)} |"
                )
        w("")
        w("### Planted causes found (all questions that expect them)\n")
        w(
            "| Model | RC1 senior approval | RC2 broker documents | RC3 Team B rework | RC4 Friday backlog |"
        )
        w("|---|---|---|---|---|")
        for m in models:
            ok = [r for r in inv if r["model"] == m and r["ok"]]
            cells = []
            for rc in ("RC1", "RC2", "RC3", "RC4"):
                rel = [r for r in ok if rc in r["expected"]]
                cells.append(f"{sum(r['found'][rc] for r in rel)}/{len(rel)}" if rel else "–")
            w(f"| `{m}` | " + " | ".join(cells) + " |")
        w("")
        w("### Safeguards at work\n")
        w("How often the deterministic safeguards changed the outcome:\n")
        w(
            "| Model | Hypotheses added by coverage rule | Verdicts overridden (confounder / small sample) "
            "| Runs whose summary needed a rewrite | Negative-value actions recommended |"
        )
        w("|---|---|---|---|---|")
        for m in models:
            ok = [r for r in inv if r["model"] == m and r["ok"]]
            rewrites = sum(any("rewritten" in n for n in r["notes"]) for r in ok)
            w(
                f"| `{m}` | {sum(r['coverage_added'] for r in ok)} | {sum(len(r['overrides']) for r in ok)} "
                f"| {rewrites}/{len(ok)} | {sum(bool(r['negative_value_recommended']) for r in ok)}/{len(ok)} |"
            )
        w("")

    w(
        "*Negative-value actions recommended* counts runs that recommended an action whose "
        "estimated net value is negative. The recommender may do so only when no positive "
        "action addresses a supported cause (here: the Saturday rota is the only catalogue "
        'remedy for the Friday backlog); the UI marks such actions "Not cost-effective".\n'
    )

    # ---- changes during the evaluation
    notes = dirs[0].parent / "NOTES.md"
    if notes.exists() or superseded:
        w("## Changes made during the evaluation\n")
        if notes.exists():
            w(notes.read_text(encoding="utf-8").strip() + "\n")
        if superseded:
            w(f"{len(superseded)} earlier result(s) were re-run after a fix and replaced:\n")
            w("| Suite | Model | Seed | Question | Earlier result |")
            w("|---|---|---|---|---|")
            for r in sorted(superseded, key=lambda r: (r.get("model", ""), r.get("seed", 0))):
                if r["suite"] != "investigation":
                    continue
                earlier = (
                    f"recall {_pct(r['recall'])}, remedy recommended "
                    f"{sum(r['remedied'].values())}/{len(r['remedied'])}"
                    if r["ok"]
                    else f"failed: {r['error'][:80]}"
                )
                w(
                    f"| investigation | `{r['model']}` | {r['seed']} | `{r['question_id']}` | {earlier} |"
                )
            w("")

    # ---- failures
    w("## 2. Failures and misses (every one)\n")
    misses = [r for r in inv if not r["ok"] or r["recall"] < 1 or r["decoys_accepted"]]
    if not misses:
        w("None.\n")
    for r in sorted(misses, key=lambda r: (r["model"], r["question_id"], r["seed"])):
        head = f"**`{r['model']}` · `{r['question_id']}` · seed {r['seed']}**"
        if not r["ok"]:
            w(f"- {head}: **{_failure_kind(r)}**: `{r['error'][:200]}`")
            continue
        missed = [rc for rc in r["expected"] if not r["found"][rc]]
        parts = []
        if missed:
            parts.append(f"missed {', '.join(missed)}")
        if r["decoys_accepted"]:
            parts.append(f"accepted decoy {', '.join(r['decoys_accepted'])}")
        w(
            f"- {head}: {'; '.join(parts)}. Hypotheses: "
            + "; ".join(
                f"{h['id']} [{h['verdict']}{', coverage' if h['auto'] else ''}] {h['statement'][:110]}"
                for h in r["hypothesis_detail"]
            )
        )
    w("")

    # ---- QA
    w("## 3. Grounded answers (policy Q&A)\n")
    if qa:
        w(
            "| Model | Answerable questions | Answered (not refused) | Cited a relevant passage "
            "| Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined "
            "| Errors | Mean generation |"
        )
        w("|---|---|---|---|---|---|---|---|---|")
        for m in models:
            rs = [r for r in qa if r["model"] == m]
            ok = [r for r in rs if r["ok"]]
            ans = [r for r in ok if r["answerable"]]
            una = [r for r in ok if not r["answerable"]]
            found = [r for r in ans if r["found"]]
            w(
                f"| `{m}` | {len(ans)} | {_pct(len(found) / len(ans) if ans else None)} "
                f"| {_pct(_mean([float(r['cites_relevant']) for r in found]))} "
                f"| {_pct(_mean([float(r['grounded']) for r in found]))} "
                f"| {_pct(_mean([r['model_citation_accuracy'] for r in found]))} "
                f"| {sum(not r['found'] for r in una)}/{len(una)} | {len(rs) - len(ok)} "
                f"| {_num(_mean([r['generation_ms'] / 1000 for r in ok]), 1)} s |"
            )
        w("")
        w(
            "*Model's own citation accuracy* = share of answer sentences whose citation the model got "
            "right before the verifier corrected anything (M3, decision D20).\n"
        )

    # ---- retrieval
    w("## 4. Retrieval (no LLM)\n")
    if retrieval:
        w("| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |")
        w("|---|---|---|---|---|")
        for r in retrieval:
            w(
                f"| {r['method']} | {r['hit_at_1']:.2f} | {r['hit_at_3']:.2f} | {r['hit_at_5']:.2f} "
                f"| {r['mrr_at_10']:.2f} |"
            )
        w("")

    # ---- what-if
    w("## 5. What-if engine vs exact counterfactuals (no LLM)\n")
    if whatif:
        by_action = defaultdict(list)
        for r in whatif:
            by_action[r["action"]].append(r)
        w(
            "| Action | "
            + " | ".join(f"seed {s}: estimate / truth" for s in seeds)
            + " | Mean ratio |"
        )
        w("|---|" + "---|" * len(seeds) + "---|")
        for action, rs in by_action.items():
            cells = {r["seed"]: f"{r['estimate']:.0f} / {r['truth']}" for r in rs}
            w(
                f"| `{action}` | "
                + " | ".join(cells.get(s, "–") for s in seeds)
                + f" | {_num(_mean([r['ratio'] for r in rs]), 2)} |"
            )
        w("")
        w(
            "A ratio below 1 means the what-if understates the benefit (it does not re-run the "
            "working calendar); it never overstates by more than the ratio shown.\n"
        )

    w("## 6. Method and limitations\n")
    w(
        "- **Synthetic data.** Ground truth is known because the generator planted it. Results "
        "show the system recovers planted patterns and resists planted decoys; they do not prove "
        "performance on real operational data."
    )
    w(
        "- **Author-written benchmarks.** The documents, retrieval questions and investigation "
        "questions were written by the same author, which flatters retrieval in particular."
    )
    w(
        "- **Small samples.** A few seeds and questions per model: differences of one or two runs "
        "are not significant."
    )
    w(
        "- **Free tiers.** Cloud models ran on free tiers; rate limits can cause failed runs, "
        "which are reported as failures."
    )
    w(
        "- **Scoring is structural.** A cause counts as found from the evidence a supported "
        "hypothesis targets, not from reading its prose."
    )
    return "\n".join(lines) + "\n"

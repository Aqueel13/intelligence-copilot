"""Run the evaluation, or build the report from saved results.

    uv run python -m watchdog_backend.evaluation run \\
        --models ollama:qwen2.5:7b,groq:openai/gpt-oss-120b --seeds 42,7,1234
    uv run python -m watchdog_backend.evaluation report ../evaluation/results/<run> [<run> …]

Runs use an isolated database (<db>_eval), reloaded per seed. Each result is appended to
<out>/results.jsonl as soon as it exists, so a long run can be watched and survives failures.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # repository root
RESULTS = ROOT / "evaluation" / "results"
SUITES = ("investigation", "qa", "retrieval", "whatif")


def cmd_run(args: argparse.Namespace) -> None:
    from watchdog_backend.evaluation.environment import load_seed, use_eval_database

    db = use_eval_database(args.db_suffix)  # before other app imports read settings
    from watchdog_backend.config import get_settings
    from watchdog_backend.domain.pack import use_domain

    domain = args.domain or get_settings().domain_pack
    with use_domain(domain):
        _run(args, db, domain, load_seed)


def _run(args: argparse.Namespace, db: str, domain: str, load_seed) -> None:
    from watchdog_backend.config import get_settings
    from watchdog_backend.evaluation import suites
    from watchdog_backend.generator.registry import generator_spec

    # Free tiers cap tokens per minute; the SDKs wait for Retry-After, so allow more attempts.
    get_settings().llm_max_retries = args.max_retries

    out = Path(args.out) if args.out else RESULTS / datetime.now().strftime("%Y-%m-%d-%H%M")
    out.mkdir(parents=True, exist_ok=True)
    models = [m for m in args.models.split(",") if m]
    seeds = [int(s) for s in args.seeds.split(",") if s]
    chosen = set(args.suites.split(","))
    spec = suites.load_spec()
    wanted = {x for x in args.questions.split(",") if x}
    questions = [q for q in spec["questions"] if not wanted or q["id"] in wanted]
    meta_path, results_path = out / "meta.json", out / "results.jsonl"
    previous = _load_previous(results_path) if args.resume else []
    resuming = args.resume and meta_path.exists()
    meta = (
        json.loads(meta_path.read_text())
        if resuming
        else {
            "started": datetime.now().isoformat(timespec="seconds"),
            "database": db,
            "domain": domain,
            "models": models,
            "seeds": seeds,
            "suites": sorted(chosen),
            "dataset": generator_spec(domain).dataset_label,
        }
    )
    if resuming:
        meta.pop("finished", None)
        meta.setdefault("passes", []).append(datetime.now().isoformat(timespec="seconds"))
    meta_path.write_text(json.dumps(meta, indent=2))
    sink = results_path.open("a", encoding="utf-8")

    # --resume: skip what already succeeded, give up on an item after --max-attempts failures
    # that were not a daily quota, and stop calling a model once its daily quota is spent.
    done = {_resume_key(r) for r in previous if r.get("ok")}
    attempts: dict[tuple, int] = {}
    for r in previous:
        if not r.get("ok") and not _is_daily_quota(r.get("error", "")):
            attempts[_resume_key(r)] = attempts.get(_resume_key(r), 0) + 1
    quota_spent: set[str] = set()

    def pending(key: tuple) -> bool:
        return key not in done and attempts.get(key, 0) < args.max_attempts

    def emit(rec: dict) -> None:
        sink.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        sink.flush()
        if not rec.get("ok") and _is_daily_quota(rec.get("error", "")) and "model" in rec:
            if rec["model"] not in quota_spent:
                log(f"  {rec['model']}: daily token quota spent, stopping it for this pass")
            quota_spent.add(rec["model"])

    def log(msg: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

    def inv_todo(model: str, seed: int) -> list[dict]:
        return [q for q in questions if pending(("investigation", model, seed, q["id"]))]

    def qa_todo(model: str) -> set[str]:
        return {t for t in suites.qa_questions(spec) if pending(("qa", model, t))}

    for i, seed in enumerate(seeds):
        needs_data = (
            "whatif" in chosen
            or ("retrieval" in chosen and i == 0)
            or ("investigation" in chosen and any(inv_todo(m, seed) for m in models))
            or ("qa" in chosen and i == 0 and any(qa_todo(m) for m in models))
        )
        if args.resume and not needs_data:
            log(f"seed {seed}: nothing left to run")
            continue
        if args.resume and models and all(m in quota_spent for m in models):
            break
        log(f"seed {seed}: loading data")
        dataset = load_seed(seed)
        if "whatif" in chosen:
            for rec in suites.whatif_suite(seed, dataset, spec):
                emit(rec)
        if "retrieval" in chosen and i == 0:  # documents do not depend on the seed
            for rec in suites.retrieval_suite():
                emit(rec)
        if "investigation" in chosen:
            for model in models:
                for q in inv_todo(model, seed):
                    if model in quota_spent:
                        break
                    rec = suites.investigation_run(model, seed, q, spec)
                    emit(rec)
                    status = (
                        f"recall {rec['recall']:.2f}, decoys {rec['decoys_accepted'] or '-'}"
                        if rec["ok"]
                        else f"ERROR {rec['error'][:80]}"
                    )
                    log(f"  {model} · {q['id']} · {rec['duration_s']}s · {status}")
                    if args.pause:
                        time.sleep(args.pause)
        if "qa" in chosen and i == 0:
            for model in models:
                if model in quota_spent:
                    continue
                log(f"  qa · {model}")
                only = qa_todo(model) if args.resume else None
                suites.qa_suite(
                    model,
                    spec,
                    pause_s=args.pause / 10,
                    only=only,
                    stop=lambda m=model: m in quota_spent,
                    emit=emit,
                )
    sink.close()

    remaining = 0
    if args.resume:
        now = _load_previous(results_path)
        done = {_resume_key(r) for r in now if r.get("ok")}
        attempts = {}
        for r in now:
            if not r.get("ok") and not _is_daily_quota(r.get("error", "")):
                attempts[_resume_key(r)] = attempts.get(_resume_key(r), 0) + 1
        if "investigation" in chosen:
            remaining += sum(len(inv_todo(m, s)) for m in models for s in seeds)
        if "qa" in chosen:
            remaining += sum(len(qa_todo(m)) for m in models)
    if remaining:
        log(f"{remaining} item(s) left for the next pass → {out}")
        sys.exit(EXIT_INCOMPLETE)
    meta["finished"] = datetime.now().isoformat(timespec="seconds")
    meta_path.write_text(json.dumps(meta, indent=2))
    log(f"done → {out}")


EXIT_INCOMPLETE = 3  # --resume: work remains (quota spent); run again later


def _load_previous(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _resume_key(r: dict) -> tuple:
    if r["suite"] == "investigation":
        return ("investigation", r["model"], r["seed"], r["question_id"])
    if r["suite"] == "qa":
        return ("qa", r["model"], r["question"])
    return (r["suite"],)


def _is_daily_quota(error: str) -> bool:
    """Groq's tokens-per-day limit: it recovers with time, so it is not counted as a failure."""
    return "tokens per day" in error or "(TPD)" in error


def cmd_report(args: argparse.Namespace) -> None:
    from watchdog_backend.evaluation.report import build_report

    dirs = [Path(d) for d in args.dirs]
    target = Path(args.output)
    target.write_text(build_report(dirs), encoding="utf-8")
    print(f"wrote {target}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--domain", default=None, help="domain pack (default: DOMAIN_PACK)")
    r.add_argument("--models", default="ollama:qwen2.5:7b")
    r.add_argument("--seeds", default="42,7,1234")
    r.add_argument("--suites", default=",".join(SUITES))
    r.add_argument("--pause", type=float, default=0.0, help="seconds between runs (rate limits)")
    r.add_argument("--out", default=None)
    r.add_argument("--max-retries", type=int, default=8, help="provider retries per call")
    r.add_argument("--questions", default="", help="only these investigation question ids")
    r.add_argument(
        "--resume",
        action="store_true",
        help="continue the run in --out: skip results that succeeded, stop a model when its\n"
        f"daily quota is spent, exit {EXIT_INCOMPLETE} while work remains",
    )
    r.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="--resume: give up on an item after this many failures (daily quota excluded)",
    )
    r.add_argument(
        "--db-suffix",
        default="eval",
        help="database <db>_<suffix>; use a different one for concurrent runs",
    )
    rp = sub.add_parser("report")
    rp.add_argument("dirs", nargs="+")
    rp.add_argument("--output", default=str(ROOT / "docs" / "evaluation_report.md"))
    args = p.parse_args()
    {"run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

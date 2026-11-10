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

    # Free tiers cap tokens per minute; the SDKs wait for Retry-After, so allow more attempts.
    get_settings().llm_max_retries = args.max_retries

    out = Path(args.out) if args.out else RESULTS / datetime.now().strftime("%Y-%m-%d-%H%M")
    out.mkdir(parents=True, exist_ok=True)
    models = [m for m in args.models.split(",") if m]
    seeds = [int(s) for s in args.seeds.split(",") if s]
    chosen = set(args.suites.split(","))
    spec = suites.load_spec()
    meta = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "database": db,
        "domain": domain,
        "models": models,
        "seeds": seeds,
        "suites": sorted(chosen),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    sink = (out / "results.jsonl").open("a", encoding="utf-8")

    def emit(rec: dict) -> None:
        sink.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        sink.flush()

    def log(msg: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

    for i, seed in enumerate(seeds):
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
                wanted = {x for x in args.questions.split(",") if x}
                for q in [q for q in spec["questions"] if not wanted or q["id"] in wanted]:
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
                log(f"  qa · {model}")
                for rec in suites.qa_suite(model, spec, pause_s=args.pause / 10):
                    emit(rec)
    sink.close()
    meta["finished"] = datetime.now().isoformat(timespec="seconds")
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    log(f"done → {out}")


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

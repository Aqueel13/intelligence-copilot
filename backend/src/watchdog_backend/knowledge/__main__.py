"""Knowledge base commands.

uv run python -m watchdog_backend.knowledge ingest      # (re)ingest every enabled pack's documents
uv run python -m watchdog_backend.knowledge evaluate    # retrieval benchmark (no LLM involved)
    --domain <pack>                                     # one pack only
"""

import argparse
import json
import time

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import available_domains, use_domain
from watchdog_backend.knowledge.evaluation import evaluate, load_benchmark
from watchdog_backend.knowledge.ingest import ingest_directory
from watchdog_backend.knowledge.models import get_embedder
from watchdog_backend.knowledge.service import benchmark_path, documents_dir, get_retriever


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["ingest", "evaluate"])
    parser.add_argument("--json", action="store_true", help="print evaluation results as JSON")
    parser.add_argument("--domain", default="all", help="a pack name, or all (default)")
    args = parser.parse_args()
    for domain in available_domains() if args.domain == "all" else [args.domain]:
        with use_domain(domain):
            if not args.json:
                print(f"[{domain}]")
            (ingest if args.command == "ingest" else benchmark)(domain, args.json)


def ingest(domain: str, _json: bool) -> None:
    started = time.perf_counter()
    with get_engine().begin() as conn:
        results = ingest_directory(conn, domain, documents_dir(), get_embedder())
    for r in results:
        print(f"  {r.status:9} {r.doc_key:8} v{r.version:5} {r.chunks:3} chunks  {r.title}")
    print(f"{len(results)} documents in {time.perf_counter() - started:.1f}s")


def benchmark(domain: str, as_json: bool) -> None:
    if not benchmark_path().is_file():
        print("  no retrieval benchmark")
        return
    questions = load_benchmark(benchmark_path())
    with get_engine().connect() as conn:
        results = evaluate(conn, get_retriever(), questions)
    if as_json:
        print(json.dumps([r.model_dump() for r in results], indent=2))
        return
    print(f"Retrieval benchmark: {len(questions)} questions\n")
    print(f"{'method':15} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'MRR@10':>7}")
    for r in results:
        scores = f"{r.hit_at_1:6.2f} {r.hit_at_3:6.2f} {r.hit_at_5:6.2f} {r.mrr_at_10:7.2f}"
        print(f"{r.method:15} {scores}")
    for r in results:
        for m in r.misses:
            print(f"  miss [{r.method}] rank {m.first_relevant_rank}: {m.q}")


if __name__ == "__main__":
    main()

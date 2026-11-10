"""Knowledge base commands.

uv run python -m watchdog_backend.knowledge ingest      # (re)ingest the domain pack's documents
uv run python -m watchdog_backend.knowledge evaluate    # retrieval benchmark (no LLM involved)
"""

import argparse
import json
import time

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
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
    args = parser.parse_args()

    if args.command == "ingest":
        started = time.perf_counter()
        with get_engine().begin() as conn:
            results = ingest_directory(conn, get_pack().domain, documents_dir(), get_embedder())
        for r in results:
            print(f"  {r.status:9} {r.doc_key:8} v{r.version:5} {r.chunks:3} chunks  {r.title}")
        print(f"{len(results)} documents in {time.perf_counter() - started:.1f}s")
        return

    questions = load_benchmark(benchmark_path())
    with get_engine().connect() as conn:
        results = evaluate(conn, get_retriever(), questions)
    if args.json:
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

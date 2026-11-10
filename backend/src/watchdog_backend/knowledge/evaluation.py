"""Retrieval benchmark: measure retrieval on its own, before any LLM is involved.

Metrics per method:
- Hit@1, Hit@3, Hit@5: share of questions with at least one relevant chunk in the top k
  (each question has one or two acceptable passages, so this is the usual "Recall@k" here).
- MRR@10: mean reciprocal rank of the first relevant chunk.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import Connection

from watchdog_backend.knowledge.retrieval import Method, RetrievedChunk, Retriever

METHODS: tuple[Method, ...] = ("vector", "keyword", "hybrid", "hybrid_rerank")


class Relevant(BaseModel):
    doc: str
    section: str


class BenchmarkQuestion(BaseModel):
    q: str
    relevant: list[Relevant]


class QuestionResult(BaseModel):
    q: str
    first_relevant_rank: int | None
    top: list[str]


class MethodResult(BaseModel):
    method: str
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    mrr_at_10: float
    misses: list[QuestionResult]


def load_benchmark(path: Path) -> list[BenchmarkQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [BenchmarkQuestion.model_validate(q) for q in raw["questions"]]


def is_relevant(chunk: RetrievedChunk, question: BenchmarkQuestion) -> bool:
    return any(
        chunk.doc_key == r.doc and r.section.lower() in chunk.section.lower()
        for r in question.relevant
    )


def evaluate(
    conn: Connection, retriever: Retriever, questions: list[BenchmarkQuestion]
) -> list[MethodResult]:
    results = []
    for method in METHODS:
        ranks: list[int | None] = []
        misses = []
        for question in questions:
            hits = retriever.search(conn, question.q, k=10, method=method)
            rank = next((i + 1 for i, h in enumerate(hits) if is_relevant(h, question)), None)
            ranks.append(rank)
            if rank is None or rank > 5:
                misses.append(
                    QuestionResult(
                        q=question.q,
                        first_relevant_rank=rank,
                        top=[f"{h.doc_key} § {h.section}" for h in hits[:3]],
                    )
                )
        n = len(questions)
        results.append(
            MethodResult(
                method=method,
                hit_at_1=sum(r == 1 for r in ranks) / n,
                hit_at_3=sum(r is not None and r <= 3 for r in ranks) / n,
                hit_at_5=sum(r is not None and r <= 5 for r in ranks) / n,
                mrr_at_10=sum(1 / r for r in ranks if r is not None) / n,
                misses=misses,
            )
        )
    return results

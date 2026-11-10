"""Wiring for the knowledge base: the active domain's retriever and documents directory."""

from functools import lru_cache
from pathlib import Path

from watchdog_backend.domain.pack import current_domain, pack_file
from watchdog_backend.knowledge.models import get_embedder, get_reranker
from watchdog_backend.knowledge.retrieval import Retriever


@lru_cache
def _retriever(domain: str) -> Retriever:
    return Retriever(domain, get_embedder(), get_reranker())


def get_retriever() -> Retriever:
    """The active pack's hybrid retriever; the reranker is attached so `hybrid_rerank` stays
    available."""
    return _retriever(current_domain())


def documents_dir() -> Path:
    return pack_file("documents")


def benchmark_path() -> Path:
    return pack_file("evaluation", "retrieval.yaml")

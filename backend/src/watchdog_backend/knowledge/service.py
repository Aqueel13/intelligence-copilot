"""Wiring for the knowledge base: the active domain's retriever and documents directory."""

from functools import lru_cache
from pathlib import Path

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.knowledge.models import get_embedder, get_reranker
from watchdog_backend.knowledge.retrieval import Retriever


@lru_cache
def get_retriever() -> Retriever:
    """Hybrid retriever; the reranker is attached so `hybrid_rerank` stays available."""
    return Retriever(get_pack().domain, get_embedder(), get_reranker())


def documents_dir() -> Path:
    s = get_settings()
    return Path(s.domain_packs_dir) / get_pack().domain / "documents"


def benchmark_path() -> Path:
    s = get_settings()
    return Path(s.domain_packs_dir) / get_pack().domain / "evaluation" / "retrieval.yaml"

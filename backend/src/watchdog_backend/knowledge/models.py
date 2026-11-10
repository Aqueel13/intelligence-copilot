"""Local embedding and reranking models (ONNX via fastembed; no GPU, no PyTorch).

Behind small protocols so another provider (e.g. Ollama embeddings) can be swapped in.
Model files are cached in `settings.models_cache_dir`.
"""

from functools import lru_cache
from typing import Protocol

from watchdog_backend.config import get_settings


class Embedder(Protocol):
    model_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    model_id: str

    def score(self, query: str, texts: list[str]) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self.model_id = model
        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # query_embed applies the model's query instruction (BGE uses one).
        return next(iter(self._model.query_embed(text))).tolist()


class FastEmbedReranker:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_id = model
        self._model = TextCrossEncoder(model_name=model, cache_dir=cache_dir)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, texts)]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return FastEmbedEmbedder(s.embedding_model, s.models_cache_dir)


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    return FastEmbedReranker(s.reranker_model, s.models_cache_dir)

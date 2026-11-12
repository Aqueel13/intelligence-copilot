"""Policy Q&A as the app serves it: cache first, then the light or standard model."""

from collections.abc import Callable

from sqlalchemy import Connection

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import current_domain
from watchdog_backend.knowledge import cache
from watchdog_backend.knowledge.answer import Answer, answer_question
from watchdog_backend.knowledge.models import get_embedder, get_reranker
from watchdog_backend.knowledge.retrieval import Method, SearchFilters
from watchdog_backend.knowledge.service import get_retriever
from watchdog_backend.llm.gateway import get_chat_model, get_light_model
from watchdog_backend.observability.context import usage_scope


def ask(
    conn: Connection,
    question: str,
    k: int = 5,
    method: Method = "hybrid",
    filters: SearchFilters | None = None,
    use_cache: bool = True,
    before_model: Callable[[], None] | None = None,
) -> Answer:
    """`before_model` runs only when the answer is not cached, before any model call (the API
    uses it for rate limits, so cached answers stay free)."""
    domain = current_domain()
    embedder = get_embedder()
    key = cache.params_key(k=k, method=method, filters=filters.model_dump() if filters else None)
    use_cache = use_cache and get_settings().knowledge_cache
    if use_cache and (hit := cache.lookup(conn, domain, question, key, embedder)):
        return hit[0]

    if before_model is not None:
        before_model()
    model, spec = get_chat_model("answer")
    light = get_light_model("answer")
    with usage_scope() as usage:
        answer = answer_question(
            conn,
            get_retriever(),
            model,
            spec.id,
            question,
            get_reranker(),
            k=k,
            method=method,
            filters=filters,
            light=(light[0], light[1].id) if light else None,
        )
    if use_cache and answer.sources:  # "no documents matched" is not worth caching
        cache.store(conn, domain, question, key, answer, sum(usage), embedder)
    return answer

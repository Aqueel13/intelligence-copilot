"""Knowledge base: ingestion, retrieval quality, citation checking and the API.

Uses the real local embedding and reranker models (downloaded once to the models cache) and
a fake chat model, so no LLM server is needed.
"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import text

from watchdog_backend.knowledge.answer import (
    NOT_FOUND,
    answer_question,
    check_support,
    validate_citations,
)
from watchdog_backend.knowledge.evaluation import evaluate, load_benchmark
from watchdog_backend.knowledge.ingest import ingest_directory
from watchdog_backend.knowledge.models import get_embedder, get_reranker
from watchdog_backend.knowledge.retrieval import Retriever, SearchFilters
from watchdog_backend.knowledge.service import benchmark_path, documents_dir


@pytest.fixture(scope="module")
def retriever(pack, kb) -> Retriever:
    return Retriever(pack.domain, get_embedder(), get_reranker())


@pytest.fixture
def conn(db_engine):
    with db_engine.connect() as c:
        yield c


# --- Ingestion ---------------------------------------------------------------------


def test_all_documents_ingested_with_versions(kb) -> None:
    keys = {(r.doc_key, r.version) for r in kb}
    assert ("POL-002", "2.1") in keys and ("POL-002", "1.0") in keys
    assert all(r.chunks > 0 for r in kb)


def test_reingest_is_idempotent(db_engine, pack, kb) -> None:
    with db_engine.begin() as c:
        again = ingest_directory(c, pack.domain, documents_dir(), get_embedder())
        n = c.execute(
            text(
                "SELECT count(*) FROM knowledge.chunks "
                "JOIN knowledge.documents USING (document_id) WHERE doc_key = ANY(:keys)"
            ),
            {"keys": [r.doc_key for r in kb]},
        ).scalar_one()
    assert {r.status for r in again} == {"unchanged"}
    assert n == sum(r.chunks for r in kb)


# --- Retrieval ---------------------------------------------------------------------


def test_benchmark_meets_recall_target(conn, retriever) -> None:
    results = {r.method: r for r in evaluate(conn, retriever, load_benchmark(benchmark_path()))}
    assert results["hybrid"].hit_at_5 >= 0.85
    assert results["hybrid"].hit_at_3 >= results["keyword"].hit_at_3


def test_superseded_versions_excluded_by_default(conn, retriever) -> None:
    q = "senior adjuster approval threshold five lakh"
    default = retriever.search(conn, q, k=10)
    with_history = retriever.search(conn, q, k=10, filters=SearchFilters(include_superseded=True))
    assert all(c.status == "current" for c in default)
    assert any(c.doc_key == "POL-002" and c.version == "1.0" for c in with_history)


def test_doc_type_filter(conn, retriever) -> None:
    hits = retriever.search(conn, "documents", k=10, filters=SearchFilters(doc_types=["reference"]))
    assert hits and {h.doc_type for h in hits} == {"reference"}


def test_results_explain_their_ranks(conn, retriever) -> None:
    top = retriever.search(conn, "What happens to work handed over late on Friday?", k=1)[0]
    assert top.doc_key == "POL-003"
    assert top.vector_rank is not None and top.keyword_rank is not None


# --- Citations ---------------------------------------------------------------------


def test_invalid_citation_numbers_are_removed() -> None:
    cleaned, valid, invalid = validate_citations("Fact one [1]. Fact two [2, 9]. Bad [7].", 3)
    assert cleaned == "Fact one [1]. Fact two [2]. Bad."
    assert valid == [1, 2] and invalid == [9, 7]


class StubReranker:
    model_id = "stub"

    def __init__(self, best: int) -> None:
        self.best = best

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [8.0 if i == self.best else -2.0 for i in range(len(texts))]


def test_wrong_citation_is_corrected_to_the_supporting_source(conn, retriever) -> None:
    chunks = retriever.search(conn, "delegation to team leads", k=3)
    checks = check_support("Delegation is allowed [3].", chunks, StubReranker(best=0))
    assert checks[0].status == "corrected"
    assert checks[0].model_cited == [3] and checks[0].cited == [1]


def test_unsupported_sentence_is_flagged_not_corrected(conn, retriever) -> None:
    chunks = retriever.search(conn, "delegation to team leads", k=3)

    class Weak(StubReranker):
        def score(self, query: str, texts: list[str]) -> list[float]:
            return [0.5] * len(texts)

    checks = check_support("The moon is made of cheese [1].", chunks, Weak(0))
    assert checks[0].status == "unsupported"


def _ask(conn, retriever, reply: str, question: str):
    return answer_question(
        conn,
        retriever,
        FakeListChatModel(responses=[reply]),
        "fake:model",
        question,
        get_reranker(),
    )


def test_answer_with_wrong_model_citations_is_repaired(conn, retriever) -> None:
    a = _ask(
        conn,
        retriever,
        "Work handed over after 15:00 on Friday is not allocated until the next working day [4].",
        "What happens to work handed over late on Friday?",
    )
    assert a.grounded
    assert a.checks[0].status == "corrected"
    assert a.citations[0].doc_key == "POL-003"
    assert a.model_citation_accuracy == 0.0


def test_not_found_is_a_grounded_refusal(conn, retriever) -> None:
    a = _ask(conn, retriever, NOT_FOUND, "What is the policy on cyber insurance claims?")
    assert not a.found and a.grounded and a.citations == []


def test_hallucinated_answer_is_not_grounded(conn, retriever) -> None:
    a = _ask(
        conn,
        retriever,
        "Claims are approved by the Chief Astronaut within 9 minutes.",
        "Who approves claims?",
    )
    assert not a.grounded


# --- API ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(kb) -> TestClient:
    from watchdog_backend.main import app

    return TestClient(app)


def test_documents_endpoint(client) -> None:
    docs = client.get("/api/knowledge/documents").json()
    assert {d["status"] for d in docs} == {"current", "superseded"}


def test_search_endpoint(client) -> None:
    hits = client.post("/api/knowledge/search", json={"query": "QA rejection target"}).json()
    assert hits[0]["doc_key"] == "SOP-105"


def test_ask_endpoint_with_fake_model(client, monkeypatch) -> None:
    from watchdog_backend.api import knowledge as api
    from watchdog_backend.llm.gateway import ModelSpec

    fake = FakeListChatModel(responses=["The QA rejection target is 5% or lower per team [1]."])
    monkeypatch.setattr(api, "get_chat_model", lambda role: (fake, ModelSpec("ollama", "fake")))
    body = client.post("/api/knowledge/ask", json={"question": "What is the QA target?"}).json()
    assert body["grounded"] and body["citations"][0]["doc_key"] == "SOP-105"


@pytest.fixture
def cleanup_memo(db_engine):
    yield
    with db_engine.begin() as c:
        c.execute(text("DELETE FROM knowledge.documents WHERE doc_key = 'MEMO-1'"))


def test_upload_markdown_document(client, cleanup_memo) -> None:
    content = b"# Pilot memo\n\n## Scope\n\nThe Saturday rota pilot starts in Pune.\n"
    r = client.post(
        "/api/knowledge/documents",
        files={"file": ("pilot.md", content, "text/markdown")},
        data={"doc_key": "MEMO-1", "doc_type": "other"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["chunks"] == 1
    hits = client.post("/api/knowledge/search", json={"query": "Saturday rota pilot Pune"}).json()
    assert hits[0]["doc_key"] == "MEMO-1"


class _ProviderError(Exception):
    status_code = 401


class _FailingModel(FakeListChatModel):
    def invoke(self, *args, **kwargs):
        raise _ProviderError("Invalid API Key")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "rejected the API key"), (429, "rate limit"), (404, "model was not found")],
)
def test_provider_errors_become_clear_502s(client, monkeypatch, status, expected) -> None:
    from watchdog_backend.api import knowledge as api
    from watchdog_backend.llm.gateway import ModelSpec

    _ProviderError.status_code = status
    model = _FailingModel(responses=["unused"])
    monkeypatch.setattr(api, "get_chat_model", lambda role: (model, ModelSpec("groq", "x")))
    r = client.post("/api/knowledge/ask", json={"question": "What is the QA target?"})
    assert r.status_code == 502
    assert "groq:x" in r.json()["detail"] and expected in r.json()["detail"]


def test_upload_rejects_unsupported_type(client) -> None:
    r = client.post("/api/knowledge/documents", files={"file": ("x.exe", b"MZ", "application/x")})
    assert r.status_code == 422

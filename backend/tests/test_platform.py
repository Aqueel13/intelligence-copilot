"""Platform features: model comparison data, observability, knowledge cache, light-model routing."""

import json
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import text

from watchdog_backend.evaluation.summary import comparison
from watchdog_backend.knowledge import cache
from watchdog_backend.knowledge.answer import Answer
from watchdog_backend.knowledge.models import get_embedder
from watchdog_backend.knowledge.retrieval import RetrievedChunk
from watchdog_backend.knowledge.routing import classify
from watchdog_backend.observability import queries
from watchdog_backend.observability.context import current_trace, traced, usage_scope
from watchdog_backend.observability.llm import LLMTracer
from watchdog_backend.observability.recorder import flush

# --- model comparison ------------------------------------------------------------------------


def _run(root: Path, name: str, domain: str, records: list[dict]) -> None:
    d = root / name
    d.mkdir()
    (d / "meta.json").write_text(
        json.dumps(
            {
                "started": f"{name}T10:00:00",
                "domain": domain,
                "models": ["m:a"],
                "seeds": [1],
                "suites": ["investigation"],
            }
        )
    )
    (d / "results.jsonl").write_text("\n".join(json.dumps(r) for r in records))


def _inv(model: str, seed: int, recall: float, ok: bool = True, error: str = "") -> dict:
    base = {"suite": "investigation", "model": model, "seed": seed, "question_id": "q1", "ok": ok}
    if not ok:
        return base | {"error": error}
    return base | {
        "recall": recall,
        "expected": ["RC1"],
        "found": {"RC1": recall == 1},
        "decoys": ["DC1"],
        "decoys_accepted": [],
        "remedied": {"RC1": True},
        "overrides": [],
        "coverage_added": 1,
        "numbers_unverified": [],
        "duration_s": 10,
        "llm_calls": 5,
        "input_tokens": 100,
        "output_tokens": 20,
        "notes": [],
        "negative_value_recommended": [],
        "hypothesis_detail": [],
    }


def test_comparison_merges_runs_and_separates_rate_limits(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "2026-01-01-a",
        "insurance_claims",
        [_inv("groq:x", 1, 0.0), _inv("groq:x", 2, 0, ok=False, error="429 RateLimit")],
    )
    _run(tmp_path, "2026-01-02-b", "insurance_claims", [_inv("groq:x", 1, 1.0)])  # re-run
    c = comparison(tmp_path)
    assert [r["name"] for r in c["runs"]] == ["2026-01-01-a", "2026-01-02-b"]
    assert c["superseded"] == 1
    row = c["domains"][0]["models"][0]
    inv = row["investigations"]
    assert (inv["runs"], inv["completed"], inv["rate_limited"], inv["failed"]) == (2, 1, 1, 0)
    assert inv["mean_recall"] == 1.0  # the later run replaced the earlier miss
    assert row["last_run"] == "2026-01-02-b"


def test_comparison_of_nothing(tmp_path: Path) -> None:
    assert comparison(tmp_path / "missing") == {"runs": [], "domains": []}


# --- light-model routing ----------------------------------------------------------------------


def _chunk(doc: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        doc_key=doc,
        title="t",
        version="1",
        status="current",
        doc_type="policy",
        section="1. x",
        content="c",
        score=1.0,
    )


@pytest.mark.parametrize(
    ("question", "docs", "expected"),
    [
        ("Who approves a claim of ₹3,00,000?", ["POL-002", "POL-002"], "simple"),
        ("Why are payments only made on Fridays now?", ["TRS-401"], "complex"),
        ("Compare the SLA for motor and health claims", ["POL-001"], "complex"),
        ("What is the SLA? Who escalates?", ["POL-001"], "complex"),
        ("What is the target?", ["A", "B", "C"], "complex"),
    ],
)
def test_classify_questions(question: str, docs: list[str], expected: str) -> None:
    assert classify(question, [_chunk(d) for d in docs])[0] == expected


# --- observability ----------------------------------------------------------------------------


def _llm_result(inp: int, out: int) -> LLMResult:
    msg = AIMessage(
        "ok", usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    )
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def test_tracer_records_calls_and_usage_scope_counts_tokens(db_engine) -> None:
    inv = str(uuid.uuid4())
    tracer = LLMTracer("planner", "ollama:test-model")
    with traced(purpose="investigation", investigation_id=inv), usage_scope() as usage:
        run = uuid.uuid4()
        tracer.on_chat_model_start({}, [], run_id=run)
        tracer.on_llm_end(_llm_result(120, 30), run_id=run)
        run2 = uuid.uuid4()
        tracer.on_chat_model_start({}, [], run_id=run2)
        tracer.on_llm_error(RuntimeError("boom org_abcdefghijklmnop"), run_id=run2)
    assert usage == [120, 30]
    assert current_trace().investigation_id is None  # restored after the block
    flush()
    with db_engine.connect() as c:
        calls = queries.investigation_calls(c, inv)
        assert [x["status"] for x in calls] == ["ok", "error"]
        assert calls[0]["input_tokens"] == 120 and calls[0]["role"] == "planner"
        assert "org_<redacted>" in calls[1]["error"]  # account ids never stored
        s = queries.summary(c, hours=1)
        assert s["llm"]["calls"] >= 2 and s["llm"]["errors"] >= 1
        assert any(r["key"] == "ollama:test-model" for r in s["by"]["model"])


def test_api_requests_are_recorded(db_engine, client_as) -> None:
    client_as("guest").get("/api/domain", headers={"X-Domain": "insurance_claims"})
    flush()
    with db_engine.connect() as c:
        routes = {r["key"] for r in queries.summary(c, hours=1)["api"]}
    assert any(r.startswith("GET ") and "domain" in r for r in routes)


# --- knowledge cache --------------------------------------------------------------------------


def _answer(question: str) -> Answer:
    return Answer(
        question=question,
        answer="A Senior Adjuster approves it [1].",
        found=True,
        grounded=True,
        citations=[],
        invalid_citations=[],
        checks=[],
        model_citation_accuracy=1.0,
        sources=[],
        model="ollama:test",
        retrieval_ms=1,
        generation_ms=1500,
    )


@pytest.fixture
def conn(db_engine, kb):
    with db_engine.connect() as c:
        c.execute(text("DELETE FROM knowledge.answer_cache"))
        c.commit()
        yield c


def test_cache_exact_normalised_and_near_duplicate_hits(conn) -> None:
    e, key, d = get_embedder(), cache.params_key(k=5), "insurance_claims"
    q = "Who approves a claim of 3,00,000 rupees?"
    assert cache.lookup(conn, d, q, key, e) is None
    cache.store(conn, d, q, key, _answer(q), tokens=700, embedder=e)

    hit, meta = cache.lookup(conn, d, "  who approves a claim of 3,00,000 rupees ", key, e)
    assert hit.cached and meta["cache_similarity"] == 1.0
    hit, meta = cache.lookup(conn, d, "Who has to approve a claim of 3,00,000 rupees?", key, e)
    assert hit.cached and 0.97 <= meta["cache_similarity"] < 1.0


def test_cache_misses_on_other_numbers_params_or_pack(conn) -> None:
    e, key, d = get_embedder(), cache.params_key(k=5), "insurance_claims"
    q = "Who approves a claim of 3,00,000 rupees?"
    cache.store(conn, d, q, key, _answer(q), tokens=700, embedder=e)
    assert cache.lookup(conn, d, "Who approves a claim of 30,00,000 rupees?", key, e) is None
    assert cache.lookup(conn, d, q, cache.params_key(k=3), e) is None
    assert cache.lookup(conn, "procure_to_pay", q, key, e) is None


def test_document_change_invalidates_the_cache(conn) -> None:
    e, key, d = get_embedder(), cache.params_key(k=5), "insurance_claims"
    q = "Who approves a claim of 3,00,000 rupees?"
    cache.store(conn, d, q, key, _answer(q), tokens=700, embedder=e)
    conn.execute(text("UPDATE knowledge.answer_cache SET corpus_version = 'old'"))
    conn.commit()
    assert cache.lookup(conn, d, q, key, e) is None


def test_cache_hit_is_recorded_with_tokens_saved(conn) -> None:
    e, key, d = get_embedder(), cache.params_key(k=5), "insurance_claims"
    q = "What is the SLA for health claims?"
    cache.store(conn, d, q, key, _answer(q), tokens=812, embedder=e)
    purpose = f"qa-cache-test-{uuid.uuid4()}"  # the test database persists between runs
    with traced(purpose=purpose):
        assert cache.lookup(conn, d, q, key, e) is not None
    flush()
    saved = (
        conn.execute(
            text("""SELECT tokens_saved FROM observability.llm_calls
                WHERE status = 'cache_hit' AND purpose = :p"""),
            {"p": purpose},
        )
        .scalars()
        .all()
    )
    assert saved == [812]

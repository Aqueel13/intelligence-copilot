"""Answer cache for policy questions.

A cached answer is reused when the question is the same after normalisation, or nearly
identical by meaning (embedding similarity ≥ NEAR_DUPLICATE) AND mentions exactly the same
numbers ("₹3,00,000" and "₹30,00,000" embed almost identically but are different questions).
Entries are keyed by the pack's document versions, so changing a document invalidates every
answer made from the old corpus; retrieval settings are part of the key too.
"""

import json
import re
from typing import Any

from sqlalchemy import Connection, text

from watchdog_backend.knowledge.answer import Answer
from watchdog_backend.knowledge.models import Embedder
from watchdog_backend.observability.context import current_trace
from watchdog_backend.observability.recorder import record

NEAR_DUPLICATE = 0.97
_NUMBER = re.compile(r"\d[\d,.]*")


def normalise(question: str) -> str:
    q = " ".join(question.lower().split())
    return q.rstrip("?.! ")


def _numbers(question: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(question)}


def corpus_version(conn: Connection, domain: str) -> str:
    return conn.execute(
        text("""SELECT coalesce(md5(string_agg(doc_key || ':' || version || ':' || status
                                                || ':' || content_hash, ','
                                                ORDER BY doc_key, version)), 'empty')
                FROM knowledge.documents WHERE domain = :d"""),
        {"d": domain},
    ).scalar_one()


def params_key(**params: Any) -> str:
    return json.dumps(params, sort_keys=True, default=str)


def lookup(
    conn: Connection, domain: str, question: str, key: str, embedder: Embedder
) -> tuple[Answer, dict[str, Any]] | None:
    version = corpus_version(conn, domain)
    base = {"d": domain, "v": version, "k": key, "m": embedder.model_id}
    row = (
        conn.execute(
            text("""SELECT cache_id, question, answer, model, tokens, created_at,
                           1.0 AS similarity
                    FROM knowledge.answer_cache
                    WHERE domain = :d AND corpus_version = :v AND params_key = :k
                      AND embedding_model = :m AND question_norm = :q
                    ORDER BY created_at DESC LIMIT 1"""),
            {**base, "q": normalise(question)},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        vec = str(embedder.embed_query(question))
        row = (
            conn.execute(
                text("""SELECT cache_id, question, answer, model, tokens, created_at,
                               1 - (embedding <=> CAST(:e AS vector)) AS similarity
                        FROM knowledge.answer_cache
                        WHERE domain = :d AND corpus_version = :v AND params_key = :k
                          AND embedding_model = :m
                        ORDER BY embedding <=> CAST(:e AS vector) LIMIT 1"""),
                {**base, "e": vec},
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["similarity"] < NEAR_DUPLICATE:
            return None
        if _numbers(row["question"]) != _numbers(question):
            return None
    conn.execute(
        text("""UPDATE knowledge.answer_cache SET hits = hits + 1, last_hit_at = now()
                WHERE cache_id = :id"""),
        {"id": row["cache_id"]},
    )
    conn.commit()
    trace = current_trace()
    record(
        "llm_calls",
        {
            "domain": domain,
            "role": "answer",
            "model": row["model"],
            "provider": row["model"].split(":", 1)[0],
            "tier": "cache",
            "purpose": trace.purpose,
            "investigation_id": trace.investigation_id,
            "user_id": trace.user_id,
            "duration_ms": 0,
            "status": "cache_hit",
            "tokens_saved": row["tokens"],
        },
    )
    meta = {
        "cached": True,
        "cached_question": row["question"],
        "cached_at": row["created_at"].isoformat(),
        "cache_similarity": float(row["similarity"]),
    }
    return Answer.model_validate({**row["answer"], **meta}), meta


def store(
    conn: Connection,
    domain: str,
    question: str,
    key: str,
    answer: Answer,
    tokens: int,
    embedder: Embedder,
) -> None:
    conn.execute(
        text("""INSERT INTO knowledge.answer_cache
                  (domain, question, question_norm, embedding, embedding_model,
                   corpus_version, params_key, answer, model, tokens)
                VALUES (:d, :q, :n, CAST(:e AS vector), :m, :v, :k, CAST(:a AS jsonb),
                        :model, :t)"""),
        {
            "d": domain,
            "q": question,
            "n": normalise(question),
            "e": str(embedder.embed_query(question)),
            "m": embedder.model_id,
            "v": corpus_version(conn, domain),
            "k": key,
            "a": answer.model_dump_json(
                exclude={"cached", "cached_question", "cached_at", "cache_similarity"}
            ),
            "model": answer.model,
            "t": tokens,
        },
    )
    conn.commit()

"""Grounded question answering over the knowledge base.

The model sees numbered sources and must cite them as [n]. Citations are then checked in
code, in two steps:
1. Validity: markers pointing at sources that were not retrieved are removed and reported.
2. Support: each cited sentence is scored against every retrieved source with the
   cross-encoder. A citation is supported if a cited source scores close to the best source
   for that sentence. Small models often cite the wrong number for a correct statement; this
   catches it and suggests the source that actually supports the sentence.
The model may say the sources do not contain the answer; that is a valid, grounded outcome.
"""

import re
import time
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import Connection

from watchdog_backend.knowledge.models import Reranker
from watchdog_backend.knowledge.retrieval import (
    Method,
    RetrievedChunk,
    Retriever,
    SearchFilters,
)
from watchdog_backend.llm.gateway import LLMCallError

NOT_FOUND = "NOT_IN_SOURCES"
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# A sentence ends at . ! ? — but a citation right after the full stop stays with it.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[)")
SUPPORT_MARGIN = 3.0  # a cited source may score at most this far below the best source
SUPPORT_FLOOR = 1.0  # …and must clear this absolute cross-encoder score
ATTRIBUTION_MIN = 3.0  # the verifier only re-attributes a sentence to a source this strong

SYSTEM_PROMPT = f"""You answer questions about an insurance company's claims policies and \
procedures, using ONLY the numbered sources provided.

Rules:
- Every factual sentence must end with the source number(s) it comes from, like [1] or [2, 3].
- Use only facts stated in the sources. Do not use outside knowledge. Do not guess numbers.
- If the sources do not contain the answer, reply with exactly: {NOT_FOUND}
- Be concise: at most 5 sentences. Quote amounts, times and section numbers exactly."""


class Citation(BaseModel):
    number: int
    chunk_id: int
    doc_key: str
    title: str
    version: str
    section: str
    content: str


CheckStatus = Literal["supported", "corrected", "unsupported"]


class SentenceCheck(BaseModel):
    sentence: str
    model_cited: list[int]  # what the model wrote
    cited: list[int]  # final citation after verification
    status: CheckStatus
    best_source: int
    best_score: float
    cited_score: float | None


class Answer(BaseModel):
    question: str
    answer: str
    found: bool
    grounded: bool
    citations: list[Citation]
    invalid_citations: list[int]
    checks: list[SentenceCheck]
    model_citation_accuracy: float | None  # sentences the model cited correctly / sentences
    sources: list[RetrievedChunk]
    model: str
    retrieval_ms: float
    generation_ms: float


def format_sources(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{i}] {c.title} (version {c.version}) — {c.section}\n{c.content}"
        for i, c in enumerate(chunks, start=1)
    )


def validate_citations(text: str, n_sources: int) -> tuple[str, list[int], list[int]]:
    """Return (cleaned text, valid source numbers in order of first use, invalid numbers)."""
    valid: list[int] = []
    invalid: list[int] = []

    def fix(match: re.Match[str]) -> str:
        nums = [int(x) for x in match.group(1).split(",")]
        keep = [n for n in nums if 1 <= n <= n_sources]
        invalid.extend(n for n in nums if n not in keep)
        valid.extend(n for n in keep if n not in valid)
        return f"[{', '.join(map(str, keep))}]" if keep else ""

    cleaned = _CITATION.sub(fix, text)
    return re.sub(r"\s+([.,;])", r"\1", cleaned).strip(), valid, invalid


def check_support(
    text: str, chunks: list[RetrievedChunk], reranker: Reranker
) -> list[SentenceCheck]:
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    passages = [f"{c.section}\n{c.content}" for c in chunks]
    checks = []
    for sentence in sentences:
        model_cited = sorted({int(n) for m in _CITATION.findall(sentence) for n in m.split(",")})
        claim = re.sub(r"\s+([.,;:!?])", r"\1", _CITATION.sub("", sentence)).strip()
        scores = reranker.score(claim, passages)
        best = max(range(len(scores)), key=lambda i: scores[i])
        cited_score = max((scores[n - 1] for n in model_cited), default=None)
        if cited_score is not None and cited_score >= max(
            SUPPORT_FLOOR, scores[best] - SUPPORT_MARGIN
        ):
            status: CheckStatus = "supported"
            cited = model_cited
        elif scores[best] >= ATTRIBUTION_MIN:
            status, cited = "corrected", [best + 1]
        else:
            status, cited = "unsupported", model_cited
        checks.append(
            SentenceCheck(
                sentence=claim,
                model_cited=model_cited,
                cited=cited,
                status=status,
                best_source=best + 1,
                best_score=scores[best],
                cited_score=cited_score,
            )
        )
    return checks


def render(checks: list[SentenceCheck]) -> str:
    """Rebuild the answer with final citations placed before the sentence's full stop."""
    parts = []
    for c in checks:
        text = c.sentence.rstrip()
        if c.cited:
            marker = f" [{', '.join(map(str, c.cited))}]"
            text = f"{text[:-1]}{marker}{text[-1]}" if text[-1:] in ".!?" else text + marker
        parts.append(text)
    return " ".join(parts)


def answer_question(
    conn: Connection,
    retriever: Retriever,
    model: BaseChatModel,
    model_id: str,
    question: str,
    reranker: Reranker,
    k: int = 5,
    method: Method = "hybrid",
    filters: SearchFilters | None = None,
) -> Answer:
    started = time.perf_counter()
    chunks = retriever.search(conn, question, k=k, method=method, filters=filters)
    retrieval_ms = (time.perf_counter() - started) * 1000

    if not chunks:
        return Answer(
            question=question,
            answer="No documents matched this question.",
            found=False,
            grounded=True,
            citations=[],
            invalid_citations=[],
            checks=[],
            model_citation_accuracy=None,
            sources=[],
            model=model_id,
            retrieval_ms=retrieval_ms,
            generation_ms=0.0,
        )

    started = time.perf_counter()
    try:
        reply = model.invoke(
            [
                SystemMessage(SYSTEM_PROMPT),
                HumanMessage(f"Sources:\n\n{format_sources(chunks)}\n\nQuestion: {question}"),
            ]
        )
    except Exception as exc:  # any provider/SDK failure becomes one well-described error
        raise LLMCallError(model_id, exc) from exc
    generation_ms = (time.perf_counter() - started) * 1000
    raw = reply.content if isinstance(reply.content, str) else str(reply.content)

    if NOT_FOUND in raw:
        return Answer(
            question=question,
            answer="The policy documents don't answer this question.",
            found=False,
            grounded=True,
            citations=[],
            invalid_citations=[],
            checks=[],
            model_citation_accuracy=None,
            sources=chunks,
            model=model_id,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
        )

    text, _, invalid = validate_citations(raw, len(chunks))
    checks = check_support(text, chunks, reranker)
    accuracy = sum(c.status == "supported" for c in checks) / len(checks) if checks else None
    valid = list(dict.fromkeys(n for c in checks for n in c.cited))
    citations = [
        Citation(
            number=n,
            chunk_id=chunks[n - 1].chunk_id,
            doc_key=chunks[n - 1].doc_key,
            title=chunks[n - 1].title,
            version=chunks[n - 1].version,
            section=chunks[n - 1].section,
            content=chunks[n - 1].content,
        )
        for n in valid
    ]
    return Answer(
        question=question,
        answer=render(checks),
        found=True,
        # Grounded = every sentence ends up with a citation that supports it.
        grounded=bool(checks) and all(c.status != "unsupported" for c in checks),
        citations=citations,
        invalid_citations=invalid,
        checks=checks,
        model_citation_accuracy=accuracy,
        sources=chunks,
        model=model_id,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
    )

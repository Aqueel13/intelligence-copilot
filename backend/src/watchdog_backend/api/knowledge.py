from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from watchdog_backend.db import get_session
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.identity import limits
from watchdog_backend.identity.deps import principal, require
from watchdog_backend.identity.service import Principal
from watchdog_backend.knowledge import qa
from watchdog_backend.knowledge.answer import Answer
from watchdog_backend.knowledge.ingest import IngestResult, ingest_document
from watchdog_backend.knowledge.models import get_embedder
from watchdog_backend.knowledge.parsing import UnsupportedDocument, parse_document
from watchdog_backend.knowledge.retrieval import Method, RetrievedChunk, SearchFilters
from watchdog_backend.knowledge.service import get_retriever
from watchdog_backend.llm.gateway import (
    LLMCallError,
    LLMConfigError,
    get_chat_model,
    get_light_model,
)
from watchdog_backend.observability.context import traced

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DbSession = Annotated[Session, Depends(get_session)]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class DocumentInfo(BaseModel):
    document_id: int
    doc_key: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: date | None
    owner: str | None
    source_name: str
    chunks: int


@router.get("/documents", response_model=list[DocumentInfo])
def list_documents(session: DbSession) -> list[DocumentInfo]:
    rows = session.execute(
        text("""
            SELECT d.document_id, d.doc_key, d.title, d.doc_type, d.version, d.status,
                   d.effective_date, d.owner, d.source_name, count(c.chunk_id) AS chunks
            FROM knowledge.documents d
            LEFT JOIN knowledge.chunks c USING (document_id)
            WHERE d.domain = :d
            GROUP BY d.document_id
            ORDER BY d.doc_key, d.effective_date DESC NULLS LAST
        """),
        {"d": get_pack().domain},
    ).mappings()
    return [DocumentInfo(**r) for r in rows]


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(5, ge=1, le=20)
    method: Method = "hybrid"
    filters: SearchFilters = Field(default_factory=SearchFilters)


@router.post("/search", response_model=list[RetrievedChunk])
def search(req: SearchRequest, session: DbSession) -> list[RetrievedChunk]:
    return get_retriever().search(session.connection(), req.query, req.k, req.method, req.filters)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    k: int = Field(5, ge=1, le=10)
    method: Method = "hybrid"
    filters: SearchFilters = Field(default_factory=SearchFilters)
    use_cache: bool = True  # False forces a fresh answer (and does not store one)


@router.post("/ask", response_model=Answer)
def ask(
    req: AskRequest, session: DbSession, who: Annotated[Principal, Depends(principal)]
) -> Answer:
    try:
        get_chat_model("answer")
        get_light_model("answer")
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    conn = session.connection()

    def spend() -> None:  # only when the answer is not cached
        limits.check(conn, who, "ask")
        limits.charge(conn, who, "ask")
        conn.commit()

    try:
        with traced(purpose="qa"):
            return qa.ask(
                conn,
                req.question,
                k=req.k,
                method=req.method,
                filters=req.filters,
                use_cache=req.use_cache,
                before_model=spend,
            )
    except limits.RateLimited as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    except LLMCallError as exc:
        # 502: the upstream model provider failed, not this service.
        raise HTTPException(
            status_code=502, detail=f"The language model ({exc.model_id}) failed: {exc.reason}"
        ) from exc


@router.post(
    "/documents",
    response_model=IngestResult,
    status_code=201,
    dependencies=[Depends(require("manage_documents"))],
)
async def upload_document(
    session: DbSession,
    file: UploadFile,
    doc_key: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    doc_type: Annotated[str | None, Form()] = None,
    version: Annotated[str | None, Form()] = None,
    status: Annotated[str | None, Form()] = None,
) -> IngestResult:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")
    if status not in (None, "", "current", "superseded", "draft"):
        raise HTTPException(status_code=422, detail="status must be current, superseded or draft")
    try:
        doc = parse_document(
            file.filename or "upload",
            data,
            {
                "id": doc_key,
                "title": title,
                "doc_type": doc_type,
                "version": version,
                "status": status,
            },
        )
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = ingest_document(session.connection(), get_pack().domain, doc, get_embedder())
    session.commit()
    return result

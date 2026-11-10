"""Hybrid retrieval: vector + full-text, fused with Reciprocal Rank Fusion, then reranked.

Each result carries its rank/score from every stage, so the UI and evaluation can show *why*
a chunk was retrieved, and retrieval quality can be measured separately from answering.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from watchdog_backend.knowledge.models import Embedder, Reranker

Method = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]
RRF_K = 60  # standard constant from the RRF paper
CANDIDATES = 20  # per first-stage retriever


class SearchFilters(BaseModel):
    doc_types: list[str] | None = None
    include_superseded: bool = Field(
        False, description="Superseded document versions are excluded unless asked for"
    )


class RetrievedChunk(BaseModel):
    chunk_id: int
    doc_key: str
    title: str
    version: str
    status: str
    doc_type: str
    section: str
    content: str
    score: float = Field(description="Final score for the method used (higher is better)")
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_similarity: float | None = None
    rerank_score: float | None = None


_SELECT = """
    SELECT c.chunk_id, d.doc_key, d.title, d.version, d.status, d.doc_type,
           c.section, c.content, {score} AS score
    FROM knowledge.chunks c
    JOIN knowledge.documents d USING (document_id)
    WHERE d.domain = :domain AND c.embedding_model = :model {where}
"""


class Retriever:
    def __init__(self, domain: str, embedder: Embedder, reranker: Reranker | None) -> None:
        self.domain = domain
        self.embedder = embedder
        self.reranker = reranker

    def _where(self, filters: SearchFilters) -> tuple[str, dict[str, object]]:
        clauses, params = [], {}
        if not filters.include_superseded:
            clauses.append("d.status = 'current'")
        if filters.doc_types:
            clauses.append("d.doc_type = ANY(:doc_types)")
            params["doc_types"] = filters.doc_types
        return "".join(f" AND {c}" for c in clauses), params

    def _vector(self, conn: Connection, query: str, filters: SearchFilters) -> list[dict]:
        where, params = self._where(filters)
        vec = str(self.embedder.embed_query(query))
        sql = _SELECT.format(score="1 - (c.embedding <=> CAST(:q AS vector))", where=where)
        sql += " ORDER BY c.embedding <=> CAST(:q AS vector) LIMIT :n"
        params |= {"domain": self.domain, "model": self.embedder.model_id, "q": vec}
        return [dict(r) for r in conn.execute(text(sql), {**params, "n": CANDIDATES}).mappings()]

    def _keyword(self, conn: Connection, query: str, filters: SearchFilters) -> list[dict]:
        where, params = self._where(filters)
        # OR the query's lexemes: natural questions rarely contain *all* terms of a passage.
        tsq = "to_tsquery('english', replace(plainto_tsquery('english', :q)::text, '&', '|'))"
        sql = _SELECT.format(score=f"ts_rank_cd(c.search_tsv, {tsq})", where=where)
        sql += f" AND c.search_tsv @@ {tsq} ORDER BY score DESC, c.chunk_id LIMIT :n"
        params |= {"domain": self.domain, "model": self.embedder.model_id, "q": query}
        return [dict(r) for r in conn.execute(text(sql), {**params, "n": CANDIDATES}).mappings()]

    def search(
        self,
        conn: Connection,
        query: str,
        k: int = 5,
        method: Method = "hybrid_rerank",
        filters: SearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        filters = filters or SearchFilters()
        vector = self._vector(conn, query, filters) if method != "keyword" else []
        keyword = self._keyword(conn, query, filters) if method != "vector" else []

        if method == "vector":
            return [_to_chunk(r, r["score"], vector_rank=i + 1) for i, r in enumerate(vector[:k])]
        if method == "keyword":
            return [_to_chunk(r, r["score"], keyword_rank=i + 1) for i, r in enumerate(keyword[:k])]

        # Reciprocal Rank Fusion
        fused: dict[int, dict] = {}
        for name, rows in (("vector", vector), ("keyword", keyword)):
            for rank, r in enumerate(rows, start=1):
                entry = fused.setdefault(r["chunk_id"], {"row": r, "rrf": 0.0})
                entry["rrf"] += 1.0 / (RRF_K + rank)
                entry[f"{name}_rank"] = rank
                if name == "vector":
                    entry["similarity"] = r["score"]
        ranked = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)

        if method == "hybrid" or self.reranker is None:
            return [_fused_chunk(e, e["rrf"]) for e in ranked[:k]]

        candidates = ranked[:CANDIDATES]
        scores = self.reranker.score(
            query, [f"{e['row']['section']}\n{e['row']['content']}" for e in candidates]
        )
        for e, s in zip(candidates, scores, strict=True):
            e["rerank"] = s
        candidates.sort(key=lambda e: e["rerank"], reverse=True)
        return [_fused_chunk(e, e["rerank"]) for e in candidates[:k]]


def _to_chunk(row: dict, score: float, **ranks: int) -> RetrievedChunk:
    fields = {k: row[k] for k in RetrievedChunk.model_fields if k in row and k != "score"}
    return RetrievedChunk(**fields, score=float(score), **ranks)


def _fused_chunk(entry: dict, score: float) -> RetrievedChunk:
    chunk = _to_chunk(
        entry["row"],
        score,
        **{k: entry[k] for k in ("vector_rank", "keyword_rank") if k in entry},
    )
    chunk.vector_similarity = entry.get("similarity")
    chunk.rerank_score = entry.get("rerank")
    return chunk

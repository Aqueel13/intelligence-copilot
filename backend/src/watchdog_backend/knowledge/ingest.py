"""Ingest parsed documents: chunk, embed and store. Idempotent per (domain, doc_key, version)."""

from dataclasses import dataclass
from pathlib import Path

from pgvector.psycopg import register_vector
from sqlalchemy import Connection, text

from watchdog_backend.knowledge.chunking import chunk_markdown
from watchdog_backend.knowledge.models import Embedder
from watchdog_backend.knowledge.parsing import SUPPORTED, ParsedDocument, parse_document


@dataclass
class IngestResult:
    doc_key: str
    version: str
    title: str
    chunks: int
    status: str  # "ingested" | "unchanged" | "replaced"


def embedding_text(doc: ParsedDocument, section: str, content: str) -> str:
    """What gets embedded: the chunk plus the context a reader would have (title, section)."""
    return f"{doc.title}\n{section}\n\n{content}"


def ingest_document(
    conn: Connection, domain: str, doc: ParsedDocument, embedder: Embedder
) -> IngestResult:
    existing = conn.execute(
        text(
            "SELECT document_id, content_hash FROM knowledge.documents "
            "WHERE domain = :d AND doc_key = :k AND version = :v"
        ),
        {"d": domain, "k": doc.doc_key, "v": doc.version},
    ).one_or_none()
    if existing and existing.content_hash == doc.content_hash:
        model_ok = conn.execute(
            text(
                "SELECT bool_and(embedding_model = :m) FROM knowledge.chunks "
                "WHERE document_id = :id"
            ),
            {"m": embedder.model_id, "id": existing.document_id},
        ).scalar()
        if model_ok:
            n = conn.execute(
                text("SELECT count(*) FROM knowledge.chunks WHERE document_id = :id"),
                {"id": existing.document_id},
            ).scalar_one()
            return IngestResult(doc.doc_key, doc.version, doc.title, n, "unchanged")
    if existing:
        conn.execute(
            text("DELETE FROM knowledge.documents WHERE document_id = :id"),
            {"id": existing.document_id},
        )

    import json

    document_id = conn.execute(
        text("""
            INSERT INTO knowledge.documents
                (domain, doc_key, title, doc_type, version, effective_date, status, owner,
                 source_name, content_hash, metadata)
            VALUES (:domain, :doc_key, :title, :doc_type, :version, :effective_date, :status,
                    :owner, :source_name, :content_hash, CAST(:metadata AS jsonb))
            RETURNING document_id
        """),
        {
            "domain": domain,
            "doc_key": doc.doc_key,
            "title": doc.title,
            "doc_type": doc.doc_type,
            "version": doc.version,
            "effective_date": doc.effective_date,
            "status": doc.status,
            "owner": doc.owner,
            "source_name": doc.source_name,
            "content_hash": doc.content_hash,
            "metadata": json.dumps(doc.metadata, default=str),
        },
    ).scalar_one()

    chunks = chunk_markdown(doc.markdown)
    vectors = embedder.embed_documents([embedding_text(doc, c.section, c.content) for c in chunks])
    raw = conn.connection.driver_connection
    register_vector(raw)
    with raw.cursor() as cur:
        cur.executemany(
            "INSERT INTO knowledge.chunks "
            "(document_id, chunk_index, section, content, embedding, embedding_model) "
            "VALUES (%s, %s, %s, %s, %s::vector, %s)",
            [
                (document_id, c.index, c.section, c.content, str(v), embedder.model_id)
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
    return IngestResult(
        doc.doc_key, doc.version, doc.title, len(chunks), "replaced" if existing else "ingested"
    )


def ingest_directory(
    conn: Connection, domain: str, directory: Path, embedder: Embedder
) -> list[IngestResult]:
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED)
    return [
        ingest_document(conn, domain, parse_document(p.name, p.read_bytes()), embedder)
        for p in files
    ]

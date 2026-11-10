"""Knowledge base: documents and chunks with embeddings and full-text search.

Embeddings use an untyped `vector` column tagged with the model that produced them, so the
embedding model can change without a schema change (re-embed instead). At this corpus size
(hundreds of chunks) an exact scan is fast; add an HNSW index per model if it grows.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge.documents (
            document_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain          text NOT NULL,
            doc_key         text NOT NULL,           -- e.g. POL-002 (stable across versions)
            title           text NOT NULL,
            doc_type        text NOT NULL,           -- policy | sop | reference | plan | other
            version         text NOT NULL,
            effective_date  date,
            status          text NOT NULL CHECK (status IN ('current', 'superseded', 'draft')),
            owner           text,
            source_name     text NOT NULL,           -- original file name
            content_hash    text NOT NULL,
            metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
            ingested_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (domain, doc_key, version)
        );

        CREATE TABLE knowledge.chunks (
            chunk_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            document_id      bigint NOT NULL REFERENCES knowledge.documents ON DELETE CASCADE,
            chunk_index      integer NOT NULL,
            section          text NOT NULL,          -- heading path, e.g. "4. Rules"
            content          text NOT NULL,
            embedding        vector NOT NULL,
            embedding_model  text NOT NULL,
            search_tsv       tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', section), 'A') ||
                setweight(to_tsvector('english', content), 'B')
            ) STORED,
            UNIQUE (document_id, chunk_index)
        );
        CREATE INDEX chunks_tsv_idx ON knowledge.chunks USING gin (search_tsv);
        CREATE INDEX chunks_model_idx ON knowledge.chunks (embedding_model);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS knowledge.chunks;
        DROP TABLE IF EXISTS knowledge.documents;
    """)

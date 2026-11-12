"""Knowledge MCP server: lets MCP clients search the policies, SOPs and change logs the
investigations cite. Every tool is read-only.

Tools
- list_documents    the pack's documents: key, title, type, version, status, effective date
- search_policies   hybrid (vector + keyword) retrieval; passages with document, version and
                    section, so the client can cite them
- get_document      a whole document, section by section

There is deliberately no "answer" tool: the client is a model that can read the passages
itself, so this server spends no LLM tokens. Superseded versions are excluded from search
unless asked for. Tools take an optional `domain` (default: the default pack).
Run: uvicorn watchdog_backend.mcp_servers.knowledge:app --host 0.0.0.0 --port 8102
"""

from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import text

from watchdog_backend.config import get_settings
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.knowledge.retrieval import SearchFilters
from watchdog_backend.knowledge.service import get_retriever
from watchdog_backend.mcp_servers.common import READ, build_asgi, call, make_server

PORT = 8102

server = make_server(
    name="watchdog-knowledge",
    title="Intelligence WatchDog: Knowledge",
    instructions=(
        "Policies, SOPs and change logs for business operations, one domain pack per process "
        "(e.g. insurance_claims, procure_to_pay). Search, then cite passages as "
        "[doc_key vVERSION §section]. Prefer current versions; superseded ones are history."
    ),
    port=PORT,
    scope="knowledge",
    tokens=lambda: get_settings().knowledge_mcp_tokens,
)


@server.tool(annotations=READ)
async def list_documents(domain: str | None = None) -> list[dict[str, Any]]:
    """List a pack's documents with type, version, status (current, superseded, draft),
    effective date and owner."""

    def work(conn) -> list[dict[str, Any]]:
        rows = conn.execute(
            text("""SELECT doc_key, title, doc_type, version, status, effective_date, owner
                    FROM knowledge.documents WHERE domain = :d
                    ORDER BY doc_key, effective_date DESC NULLS LAST"""),
            {"d": get_pack().domain},
        ).mappings()
        return [
            {
                **r,
                "effective_date": r["effective_date"].isoformat() if r["effective_date"] else None,
            }
            for r in rows
        ]

    return await call(work, domain=domain)


@server.tool(annotations=READ)
async def search_policies(
    query: str,
    k: int = 5,
    method: Literal["hybrid", "vector", "keyword", "hybrid_rerank"] = "hybrid",
    doc_types: list[str] | None = None,
    include_superseded: bool = False,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Find the passages that best match a question. Returns document key, title, version,
    status, section and text, best first. method: hybrid (default; vector + keyword),
    vector, keyword, or hybrid_rerank (slower, cross-encoder reranking)."""
    if not query.strip():
        raise ToolError("query is empty")
    k = max(1, min(k, 20))
    filters = SearchFilters(doc_types=doc_types, include_superseded=include_superseded)

    def work(conn) -> list[dict[str, Any]]:
        hits = get_retriever().search(conn, query, k, method, filters)
        return [
            h.model_dump(
                include={"doc_key", "title", "version", "status", "doc_type", "section", "content"}
            )
            | {"score": round(h.score, 4)}
            for h in hits
        ]

    return await call(work, domain=domain)


@server.tool(annotations=READ)
async def get_document(
    doc_key: str, version: str | None = None, domain: str | None = None
) -> dict[str, Any]:
    """A whole document, section by section. Without `version`, the current version (or the
    latest, if none is current)."""

    def work(conn) -> dict[str, Any]:
        doc = (
            conn.execute(
                text("""SELECT document_id, doc_key, title, doc_type, version, status,
                               effective_date, owner
                        FROM knowledge.documents
                        WHERE domain = :d AND doc_key = :k
                          AND (CAST(:v AS text) IS NULL OR version = :v)
                        ORDER BY (status = 'current') DESC, effective_date DESC NULLS LAST
                        LIMIT 1"""),
                {"d": get_pack().domain, "k": doc_key, "v": version},
            )
            .mappings()
            .one_or_none()
        )
        if doc is None:
            raise ToolError(f"No document {doc_key!r}" + (f" version {version}" if version else ""))
        sections = conn.execute(
            text("""SELECT section, content FROM knowledge.chunks
                    WHERE document_id = :id ORDER BY chunk_index"""),
            {"id": doc["document_id"]},
        ).mappings()
        out = {k: v for k, v in doc.items() if k != "document_id"}
        out["effective_date"] = _iso(doc["effective_date"])
        out["sections"] = [dict(s) for s in sections]
        return out

    return await call(work, domain=domain)


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def build_app():
    return build_asgi(server, PORT, "knowledge-mcp")


app = build_app()

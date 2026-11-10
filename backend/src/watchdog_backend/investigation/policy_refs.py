"""Resolve references like "POL-002 §4.3" to the current text of that clause."""

import re

from pydantic import BaseModel
from sqlalchemy import Connection, text

_REF = re.compile(r"^\s*([A-Z]+-\d+)\s*§\s*([\d.]+)\s*$")


class PolicyClause(BaseModel):
    ref: str
    doc_key: str
    title: str
    version: str
    section: str
    text: str


def resolve(conn: Connection, domain: str, ref: str) -> PolicyClause | None:
    m = _REF.match(ref)
    if not m:
        return None
    doc_key, number = m.group(1), m.group(2).rstrip(".")
    top = number.split(".")[0]
    rows = (
        conn.execute(
            text("""
            SELECT d.title, d.version, c.section, c.content
            FROM knowledge.chunks c JOIN knowledge.documents d USING (document_id)
            WHERE d.domain = :domain AND d.doc_key = :doc AND d.status = 'current'
              AND (c.section LIKE :top || '.%' OR c.section LIKE :top || ' %')
            ORDER BY c.chunk_index
        """),
            {"domain": domain, "doc": doc_key, "top": top},
        )
        .mappings()
        .all()
    )
    if not rows:
        return None
    content = "\n\n".join(r["content"] for r in rows)
    if "." in number:  # a sub-clause like 4.3: keep just the paragraph that starts with it
        para = next((p for p in content.split("\n\n") if p.lstrip().startswith(number)), None)
        content = para or content
    return PolicyClause(
        ref=ref,
        doc_key=doc_key,
        title=rows[0]["title"],
        version=rows[0]["version"],
        section=rows[0]["section"],
        text=content.strip(),
    )

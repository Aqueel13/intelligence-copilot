"""Turn uploaded files into Markdown text plus metadata.

Supported: .md / .markdown (optional YAML front matter), .txt, .docx, .pdf.
DOCX headings become Markdown headings, so section-aware chunking works for them too.
PDF text has no reliable structure; it is split into paragraphs only.
"""

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import yaml

DocType = Literal["policy", "sop", "reference", "plan", "other"]
Status = Literal["current", "superseded", "draft"]
SUPPORTED = (".md", ".markdown", ".txt", ".docx", ".pdf")
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class UnsupportedDocument(ValueError):
    pass


@dataclass
class ParsedDocument:
    doc_key: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: date | None
    owner: str | None
    source_name: str
    markdown: str
    content_hash: str
    metadata: dict[str, object] = field(default_factory=dict)


def parse_document(
    source_name: str, data: bytes, overrides: dict[str, object] | None = None
) -> ParsedDocument:
    """Parse a file. `overrides` (e.g. from an upload form) win over front matter."""
    lower = source_name.lower()
    if not lower.endswith(SUPPORTED):
        raise UnsupportedDocument(f"Unsupported file type. Supported: {', '.join(SUPPORTED)}")

    meta: dict[str, object] = {}
    if lower.endswith((".md", ".markdown", ".txt")):
        text = data.decode("utf-8-sig")
        match = _FRONT_MATTER.match(text)
        if match:
            meta = yaml.safe_load(match.group(1)) or {}
            text = text[match.end() :]
    elif lower.endswith(".docx"):
        text = _docx_to_markdown(data)
    else:
        text = _pdf_to_text(data)

    meta.update({k: v for k, v in (overrides or {}).items() if v not in (None, "")})
    text = text.strip()
    if not text:
        raise UnsupportedDocument("The document contains no extractable text")

    stem = re.sub(r"\.[^.]+$", "", source_name)
    title = str(meta.get("title") or _first_heading(text) or stem)
    effective = meta.get("effective_date")
    if isinstance(effective, str):
        effective = date.fromisoformat(effective)
    known = {"id", "title", "doc_type", "version", "status", "effective_date", "owner"}
    return ParsedDocument(
        doc_key=str(meta.get("id") or stem),
        title=title,
        doc_type=str(meta.get("doc_type") or "other"),
        version=str(meta.get("version") or "1.0"),
        status=str(meta.get("status") or "current"),
        effective_date=effective if isinstance(effective, date) else None,
        owner=str(meta["owner"]) if meta.get("owner") else None,
        source_name=source_name,
        markdown=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        metadata={k: v for k, v in meta.items() if k not in known},
    )


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _docx_to_markdown(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name if p.style is not None else "") or ""
        level = re.match(r"Heading (\d)", style)
        if style == "Title":
            lines.append(f"# {text}")
        elif level:
            lines.append(f"{'#' * (int(level.group(1)) + 1)} {text}")
        elif style.startswith("List"):
            lines.append(f"- {text}")
        else:
            lines.append(text)
        lines.append("")
    for table in doc.tables:
        rows = [[c.text.strip() for c in row.cells] for row in table.rows]
        if rows:
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + "---|" * len(rows[0]))
            lines.extend("| " + " | ".join(r) + " |" for r in rows[1:])
            lines.append("")
    return "\n".join(lines)


def _pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(p for p in pages if p)

"""Parsing and chunking: pure functions, no database or models."""

import io

import pytest

from watchdog_backend.knowledge.chunking import chunk_markdown
from watchdog_backend.knowledge.parsing import UnsupportedDocument, parse_document

MD = b"""---
id: POL-999
title: Test Policy
doc_type: policy
version: "2.0"
effective_date: 2026-01-01
status: current
owner: Someone
reviewer: Another
---

# Test Policy

Intro line.

## 1. Scope

Applies to all claims.

## 2. Levels

| Amount | Approver |
|---|---|
| Up to 2L | Officer |
| Above 2L | Senior |

### 2.1 Notes

A note under a subsection.
"""


def test_markdown_front_matter_becomes_metadata() -> None:
    doc = parse_document("pol.md", MD)
    assert (doc.doc_key, doc.title, doc.doc_type, doc.version, doc.status) == (
        "POL-999",
        "Test Policy",
        "policy",
        "2.0",
        "current",
    )
    assert str(doc.effective_date) == "2026-01-01"
    assert doc.metadata == {"reviewer": "Another"}  # unknown keys are kept, not dropped
    assert not doc.markdown.startswith("---")


def test_overrides_win_over_front_matter() -> None:
    doc = parse_document("pol.md", MD, {"version": "3.0", "status": None})
    assert doc.version == "3.0" and doc.status == "current"


def test_same_content_same_hash() -> None:
    assert parse_document("a.md", MD).content_hash == parse_document("b.md", MD).content_hash


def test_unsupported_and_empty_files_are_rejected() -> None:
    with pytest.raises(UnsupportedDocument, match="Unsupported"):
        parse_document("x.exe", b"MZ")
    with pytest.raises(UnsupportedDocument, match="no extractable text"):
        parse_document("x.md", b"   \n")


def test_docx_headings_become_sections() -> None:
    from docx import Document

    d = Document()
    d.add_heading("Handbook", level=0)
    d.add_heading("Working hours", level=1)
    d.add_paragraph("Teams work Monday to Friday.")
    buf = io.BytesIO()
    d.save(buf)
    doc = parse_document("handbook.docx", buf.getvalue())
    chunks = chunk_markdown(doc.markdown)
    assert doc.title == "Handbook"
    assert [c.section for c in chunks] == ["Working hours"]
    assert "Monday to Friday" in chunks[0].content


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_is_extracted() -> None:
    doc = parse_document("memo.pdf", _minimal_pdf("Senior approval within 24 hours"))
    assert "Senior approval within 24 hours" in doc.markdown


# --- Chunking ----------------------------------------------------------------------


def test_sections_follow_headings_and_title_is_excluded() -> None:
    chunks = chunk_markdown(parse_document("p.md", MD).markdown)
    assert [c.section for c in chunks] == [
        "Introduction",
        "1. Scope",
        "2. Levels",
        "2. Levels › 2.1 Notes",
    ]
    assert all("# Test Policy" not in c.content for c in chunks)


def test_tables_are_never_split() -> None:
    rows = "\n".join(f"| row {i} | value {i} with several words here |" for i in range(80))
    chunks = chunk_markdown(f"## T\n\n| a | b |\n|---|---|\n{rows}\n", max_words=50)
    assert len(chunks) == 1 and chunks[0].content.count("| row") == 80


def test_long_paragraphs_split_by_sentence() -> None:
    para = " ".join(f"Sentence number {i} has exactly seven words." for i in range(60))
    chunks = chunk_markdown(f"## Long\n\n{para}\n", max_words=100)
    assert len(chunks) > 1
    assert all(c.words <= 100 for c in chunks)
    assert all(c.content.endswith(".") for c in chunks)


def test_every_shipped_document_chunks_cleanly(pack) -> None:
    from watchdog_backend.knowledge.service import documents_dir

    for path in sorted(documents_dir().glob("*.md")):
        doc = parse_document(path.name, path.read_bytes())
        chunks = chunk_markdown(doc.markdown)
        assert chunks, path.name
        assert doc.status in ("current", "superseded"), path.name
        assert all(c.words <= 200 or c.content.lstrip().startswith("|") for c in chunks)

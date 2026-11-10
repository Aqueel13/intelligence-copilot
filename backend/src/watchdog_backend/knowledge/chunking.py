"""Section-aware chunking for Markdown.

- Sections come from `##`/`###`… headings; the `#` title is the document, not a section.
- Within a section, blocks (paragraphs, lists, tables) are packed into chunks of at most
  `max_words`. A table is never split; a single oversized paragraph is split by sentence.
- Each chunk records its section path so citations can say "§4. Rules" rather than
  "chunk 17".
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    section: str
    content: str

    @property
    def words(self) -> int:
        return len(self.content.split())


def _blocks(lines: list[str]) -> list[str]:
    """Group lines into blocks separated by blank lines; keep tables and lists together."""
    blocks, current = [], []
    for line in lines:
        if line.strip():
            current.append(line.rstrip())
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _split_long(block: str, max_words: int) -> list[str]:
    if len(block.split()) <= max_words or block.lstrip().startswith("|"):
        return [block]
    parts, current = [], []
    for sentence in _SENTENCE.split(block):
        if current and len(" ".join([*current, sentence]).split()) > max_words:
            parts.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        parts.append(" ".join(current))
    return parts


def chunk_markdown(markdown: str, max_words: int = 160) -> list[Chunk]:
    sections: list[tuple[str, list[str]]] = []
    path: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_section = "Introduction"

    def flush() -> None:
        if any(line.strip() for line in current_lines):
            sections.append((current_section, list(current_lines)))
        current_lines.clear()

    for line in markdown.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) >= 2:
            flush()
            level = len(m.group(1))
            path = [(lvl, title) for lvl, title in path if lvl < level] + [(level, m.group(2))]
            current_section = " › ".join(title for _, title in path)
        elif m:  # document title: not part of any section's text
            continue
        else:
            current_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    for section, lines in sections:
        pending: list[str] = []
        for block in (b for raw in _blocks(lines) for b in _split_long(raw, max_words)):
            if pending and len(" ".join([*pending, block]).split()) > max_words:
                chunks.append(Chunk(len(chunks), section, "\n\n".join(pending)))
                pending = []
            pending.append(block)
        if pending:
            chunks.append(Chunk(len(chunks), section, "\n\n".join(pending)))
    return chunks

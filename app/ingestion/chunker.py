"""Article-based chunking.

Rules:
- one article never shares a chunk with another article;
- a short article is one chunk;
- a long article is split on paragraph (band/xatboshi) boundaries, and a single
  over-long paragraph on sentence boundaries;
- every chunk carries the document, article label, title and chapter context in
  its embedding text;
- optional overlap: the previous chunk's last paragraph is repeated when it is short.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from app.retrieval.normalize import normalize_for_search

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;:])\s+")


@dataclass(frozen=True)
class ChunkSpec:
    ordinal: int
    text: str
    embed_text: str
    search_text: str
    content_hash: str
    char_len: int
    est_tokens: int


def estimate_tokens(text: str) -> int:
    """Rough estimate (~4 chars/token). Used for limits, not billing."""
    return max(1, math.ceil(len(text) / 4))


def _split_long_paragraph(par: str, max_chars: int) -> list[str]:
    if len(par) <= max_chars:
        return [par]
    parts, buf = [], ""
    for sent in _SENTENCE_SPLIT_RE.split(par):
        if buf and len(buf) + 1 + len(sent) > max_chars:
            parts.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
        while len(buf) > max_chars:  # a "sentence" longer than the limit
            parts.append(buf[:max_chars])
            buf = buf[max_chars:]
    if buf:
        parts.append(buf)
    return parts


def article_header(doc_short_name: str, label: str, title: str, heading_context: str) -> str:
    head = f"{doc_short_name}. {label}-modda. {title}".strip()
    return f"{head}\n{heading_context}" if heading_context else head


def chunk_article(
    *,
    doc_short_name: str,
    label: str,
    title: str,
    heading_context: str,
    paragraphs: list[str],
    max_chars: int = 1400,
    overlap_paragraphs: int = 1,
    overlap_max_chars: int = 300,
) -> list[ChunkSpec]:
    header = article_header(doc_short_name, label, title, heading_context)
    pieces: list[str] = []
    for par in paragraphs:
        pieces.extend(_split_long_paragraph(par, max_chars))
    if not pieces:
        pieces = [title]

    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for piece in pieces:
        if current and size + len(piece) + 1 > max_chars:
            groups.append(current)
            tail = current[-overlap_paragraphs:] if overlap_paragraphs else []
            tail = [p for p in tail if len(p) <= overlap_max_chars]
            current = list(tail)
            size = sum(len(p) + 1 for p in current)
        current.append(piece)
        size += len(piece) + 1
    if current:
        groups.append(current)

    chunks = []
    for i, group in enumerate(groups):
        text = "\n".join(group)
        embed_text = f"{header}\n{text}"
        chunks.append(
            ChunkSpec(
                ordinal=i,
                text=text,
                embed_text=embed_text,
                search_text=normalize_for_search(embed_text),
                content_hash=hashlib.sha256(embed_text.encode("utf-8")).hexdigest(),
                char_len=len(text),
                est_tokens=estimate_tokens(embed_text),
            )
        )
    return chunks

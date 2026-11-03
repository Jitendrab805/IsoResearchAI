"""Section-aware chunking.

Chunks never span two pages, so every chunk has one exact page number for
citation.  Each chunk carries the most recent section heading.  Paragraphs are
packed up to ``max_chars``; long paragraphs are split on sentence boundaries,
with a small sentence overlap to keep context.
"""
from __future__ import annotations

import re

from .pdf_extract import Extracted

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(δΔ])")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def chunk_document(ex: Extracted, max_chars: int = 1100, overlap: int = 150,
                   min_chars: int = 40) -> list[dict]:
    chunks: list[dict] = []
    section = "Front matter"
    for page in ex.pages:
        buf: list[str] = []
        size = 0

        def flush(sec: str) -> None:
            nonlocal buf, size
            text = " ".join(buf).strip()
            if len(text) >= min_chars:
                chunks.append({"page": page.number, "section": sec, "text": text})
            buf, size = [], 0

        for block in page.blocks:
            if block.kind == "heading":
                flush(section)
                section = block.text[:120]
                continue
            para = block.text
            if size + len(para) <= max_chars:
                buf.append(para)
                size += len(para) + 1
                continue
            # paragraph does not fit — split by sentences
            for sent in _sentences(para) or [para]:
                while len(sent) > max_chars:  # pathological very long "sentence"
                    if buf:
                        flush(section)
                    buf, size = [sent[:max_chars]], max_chars
                    flush(section)
                    sent = sent[max_chars - overlap:]
                if size + len(sent) > max_chars and buf:
                    tail = []
                    for s in reversed(buf):  # carry overlap
                        if sum(len(x) for x in tail) + len(s) > overlap:
                            break
                        tail.insert(0, s)
                    flush(section)
                    buf, size = list(tail), sum(len(x) + 1 for x in tail)
                buf.append(sent)
                size += len(sent) + 1
        flush(section)
    return chunks

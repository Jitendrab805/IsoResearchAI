"""Citation validation: map [S#] markers to real retrieved passages.

Markers that do not correspond to a provided passage are *never* turned into
references — they are flagged as invalid so a fabricated citation cannot
masquerade as evidence.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..core.repository import Chunk

MARKER = re.compile(r"\[(S\d+(?:\s*[,;]\s*S?\d+)*)\]")


@dataclass
class Citation:
    n: int
    chunk_id: int
    doc_id: int
    title: str
    authors: str
    year: int | None
    page: int
    section: str
    excerpt: str
    filename: str = ""

    def label(self) -> str:
        bits = [self.title or self.filename]
        who = []
        if self.authors:
            who.append(self.authors.split(";")[0].strip())
        if self.year:
            who.append(str(self.year))
        s = bits[0] + (f" ({', '.join(who)})" if who else "")
        return f"{s}, p. {self.page}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CitationReport:
    text: str
    citations: list[Citation]
    invalid: list[str]
    used: list[int]

    @property
    def uncited(self) -> bool:
        return not self.used


def _numbers(group: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", group)]


def validate(answer: str, sources: list[Chunk]) -> CitationReport:
    cits = [Citation(i, c.id, c.doc_id, c.title, c.authors or "", c.year, c.page, c.section or "",
                     c.text[:400], c.filename) for i, c in enumerate(sources, 1)]
    valid = {c.n for c in cits}
    used: list[int] = []
    invalid: list[str] = []

    def fix(m: re.Match) -> str:
        nums = _numbers(m.group(1))
        good = [n for n in nums if n in valid]
        bad = [n for n in nums if n not in valid]
        for n in good:
            if n not in used:
                used.append(n)
        invalid.extend(f"S{n}" for n in bad)
        parts = [f"[S{n}]" for n in good] + [f"[S{n}?invalid]" for n in bad]
        return "".join(parts)

    text = MARKER.sub(fix, answer)
    return CitationReport(text, cits, sorted(set(invalid)), used)


def link_markers(text: str) -> str:
    """Turn [S#] into markdown links handled by the UI (iso://cite/N)."""
    text = re.sub(r"\[S(\d+)\?invalid\]", r"<span class='invalid'>[S\1: not a provided source]</span>", text)
    return re.sub(r"\[S(\d+)\]", r"[[S\1]](iso://cite/\1)", text)


def references_markdown(report: CitationReport, only_used: bool = True) -> str:
    rows = []
    for c in report.citations:
        if only_used and c.n not in report.used:
            continue
        rows.append(f"- **[S{c.n}]** {c.label()} — section: {c.section or 'n/a'}")
    if not rows:
        return ""
    return "\n\n**Sources (local library)**\n\n" + "\n".join(rows)

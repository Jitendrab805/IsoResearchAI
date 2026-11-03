"""Keyword (SQLite FTS5 / BM25), semantic (vector) and hybrid search.

Hybrid search merges both rankings with Reciprocal Rank Fusion, which is
robust when the two score scales are not comparable.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.db import Database
from ..core.repository import Chunk, LibraryRepo
from .embeddings import Embedder, load_embedder, tokenize
from .vector_index import VectorIndex

log = logging.getLogger(__name__)

REFERENCE_SECTIONS = re.compile(r"references|bibliography|acknowledg", re.I)


@dataclass
class SearchFilters:
    doc_ids: set[int] | None = None  # restrict to these documents (collections/selection)
    year_min: int | None = None
    year_max: int | None = None
    include_references: bool = False


class SearchEngine:
    def __init__(self, db: Database, index_dir: Path, embedding_model: str, use_st: bool,
                 models_dir: Path | None = None):
        self.db = db
        self.repo = LibraryRepo(db)
        self.index_dir = index_dir
        self._lock = threading.RLock()
        self.embedder: Embedder
        self.embedder, self.embedder_status = load_embedder(embedding_model, use_st, models_dir)
        self.index = VectorIndex(index_dir, self.embedder.name, self.embedder.dim)

    @property
    def semantic_available(self) -> bool:
        return getattr(self.embedder, "semantic", False)

    # ----------------------------------------------------------- indexing
    def index_chunks(self, ids: list[int], texts: list[str], batch: int = 64,
                     progress: Callable[[int, int], None] | None = None,
                     cancel: Callable[[], bool] | None = None) -> None:
        with self._lock:
            for start in range(0, len(ids), batch):
                if cancel and cancel():
                    raise InterruptedError("Indexing cancelled")
                vecs = self.embedder.encode(texts[start:start + batch])
                self.index.add(ids[start:start + batch], vecs)
                if progress:
                    progress(min(start + batch, len(ids)), len(ids))
            self.index.save()

    def remove_chunks(self, ids: list[int]) -> None:
        with self._lock:
            self.index.remove(ids)
            self.index.save()

    def rebuild(self, progress: Callable[[int, int], None] | None = None,
                cancel: Callable[[], bool] | None = None) -> int:
        rows = self.repo.all_chunk_rows()
        with self._lock:
            self.index.clear()
            self.index_chunks([r[0] for r in rows], [r[1] for r in rows], progress=progress, cancel=cancel)
        log.info("Vector index rebuilt with %d chunks", len(rows))
        return len(rows)

    def ensure_index(self, progress=None) -> bool:
        """Rebuild when stale/missing.  Returns True if a rebuild happened."""
        n_chunks = self.db.one("SELECT COUNT(*) FROM chunks")[0]
        if self.index.needs_rebuild or len(self.index) != n_chunks:
            self.rebuild(progress=progress)
            return True
        return False

    # ------------------------------------------------------------ filters
    def _allowed_docs(self, f: SearchFilters | None) -> set[int] | None:
        if f is None:
            return None
        allowed = set(f.doc_ids) if f.doc_ids is not None else None
        if f.year_min or f.year_max:
            rows = self.db.query("SELECT id FROM documents WHERE year IS NOT NULL AND year BETWEEN ? AND ?",
                                 (f.year_min or 0, f.year_max or 9999))
            yr = {r[0] for r in rows}
            allowed = yr if allowed is None else allowed & yr
        return allowed

    def _allowed_chunks(self, docs: set[int] | None) -> set[int] | None:
        if docs is None:
            return None
        if not docs:
            return set()
        q = ",".join("?" * len(docs))
        return {r[0] for r in self.db.query(f"SELECT id FROM chunks WHERE doc_id IN ({q})", list(docs))}

    # ------------------------------------------------------------- search
    @staticmethod
    def fts_query(text: str) -> str:
        toks = tokenize(text)
        # also keep raw words (FTS tokenizer sees the original text)
        raw = [w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", text)]
        terms = list(dict.fromkeys([t for t in raw if t not in {"the", "and", "of", "in", "for", "to", "a"}]
                                   + [t for t in toks if "_" not in t]))[:24]
        return " OR ".join('"' + t.replace('"', "") + '"' for t in terms)

    def keyword(self, query: str, k: int = 10, filters: SearchFilters | None = None) -> list[Chunk]:
        q = self.fts_query(query)
        if not q:
            return []
        docs = self._allowed_docs(filters)
        params: list = [q]
        extra = ""
        if docs is not None:
            if not docs:
                return []
            extra = f" AND c.doc_id IN ({','.join('?' * len(docs))})"
            params += list(docs)
        if not (filters and filters.include_references):
            extra += " AND c.section NOT LIKE '%reference%' AND c.section NOT LIKE '%bibliograph%'"
        params.append(k)
        sql = ("SELECT c.id, bm25(chunks_fts) AS s FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
               f"WHERE chunks_fts MATCH ?{extra} ORDER BY s LIMIT ?")
        try:
            rows = self.db.query(sql, params)
        except Exception as exc:  # noqa: BLE001 - malformed MATCH
            log.warning("Keyword search failed: %s", type(exc).__name__)
            return []
        chunks = self.repo.chunks_by_ids([r[0] for r in rows])
        for c, r in zip(chunks, rows):
            c.score = -float(r[1])
        return chunks

    def semantic(self, query: str, k: int = 10, filters: SearchFilters | None = None) -> list[Chunk]:
        allowed = self._allowed_chunks(self._allowed_docs(filters))
        if allowed is not None and not allowed:
            return []
        vec = self.embedder.encode([query])[0]
        hits = self.index.search(vec, k * 3, allowed)
        chunks = self.repo.chunks_by_ids([h[0] for h in hits])
        score = dict(hits)
        out = []
        for c in chunks:
            c.score = score.get(c.id, 0.0)
            if not (filters and filters.include_references) and REFERENCE_SECTIONS.search(c.section or ""):
                continue
            out.append(c)
        return out[:k]

    def hybrid(self, query: str, k: int = 8, filters: SearchFilters | None = None, rrf_k: int = 60) -> list[Chunk]:
        kw = self.keyword(query, k * 3, filters)
        se = self.semantic(query, k * 3, filters)
        fused: dict[int, float] = {}
        by_id: dict[int, Chunk] = {}
        for ranking in (kw, se):
            for rank, c in enumerate(ranking):
                fused[c.id] = fused.get(c.id, 0.0) + 1.0 / (rrf_k + rank + 1)
                by_id[c.id] = c
        order = sorted(fused, key=lambda i: -fused[i])[:k]
        out = []
        for i in order:
            c = by_id[i]
            c.score = round(fused[i] * 1000, 2)
            out.append(c)
        return out

    def search(self, query: str, mode: str = "hybrid", k: int = 8,
               filters: SearchFilters | None = None) -> list[Chunk]:
        if mode == "keyword":
            return self.keyword(query, k, filters)
        if mode == "semantic":
            return self.semantic(query, k, filters)
        return self.hybrid(query, k, filters)

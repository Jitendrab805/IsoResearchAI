"""Data-access helpers for the research library (documents, collections, tags)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable

from .db import Database, dumps, loads


@dataclass
class Chunk:
    id: int
    doc_id: int
    page: int
    section: str
    text: str
    chunk_index: int = 0
    # filled by joins
    filename: str = ""
    title: str = ""
    authors: str = ""
    year: int | None = None
    score: float = 0.0

    def label(self) -> str:
        """Short human citation label: Title (Authors, Year), p. N."""
        bits = []
        if self.authors:
            first = self.authors.split(";")[0].split(",")[0].strip()
            more = " et al." if (";" in self.authors or self.authors.count(",") > 1) else ""
            bits.append(first + more)
        if self.year:
            bits.append(str(self.year))
        who = f" ({', '.join(bits)})" if bits else ""
        return f"{self.title or self.filename}{who}, p. {self.page}"


class LibraryRepo:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ documents
    def documents(self, search: str = "", collection_id: int | None = None,
                  tag: str | None = None, status: str | None = None) -> list[dict]:
        sql = ["SELECT d.* FROM documents d"]
        where, params = [], []
        if collection_id:
            sql.append("JOIN document_collections dc ON dc.doc_id = d.id")
            where.append("dc.collection_id = ?")
            params.append(collection_id)
        if tag:
            sql.append("JOIN document_tags dt ON dt.doc_id = d.id JOIN tags t ON t.id = dt.tag_id")
            where.append("t.name = ?")
            params.append(tag)
        if status:
            where.append("d.status = ?")
            params.append(status)
        if search:
            like = f"%{search}%"
            where.append("(d.filename LIKE ? OR d.display_label LIKE ? OR d.title LIKE ? "
                         "OR d.authors LIKE ? OR d.journal LIKE ? OR d.doi LIKE ? OR CAST(d.year AS TEXT) LIKE ?)")
            params += [like] * 7
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY d.imported_at DESC")
        rows = self.db.query(" ".join(sql), params)
        docs = [dict(r) for r in rows]
        if docs:
            tag_map = self.tags_by_doc([d["id"] for d in docs])
            for d in docs:
                d["tags"] = tag_map.get(d["id"], [])
        return docs

    def document(self, doc_id: int) -> dict | None:
        r = self.db.one("SELECT * FROM documents WHERE id = ?", (doc_id,))
        if not r:
            return None
        d = dict(r)
        d["tags"] = self.tags_by_doc([doc_id]).get(doc_id, [])
        d["collections"] = [dict(c) for c in self.db.query(
            "SELECT c.id, c.name FROM collections c JOIN document_collections dc ON dc.collection_id=c.id "
            "WHERE dc.doc_id = ?", (doc_id,))]
        d["metadata"] = loads(d.get("metadata_json"), {})
        return d

    def by_sha(self, sha: str) -> dict | None:
        r = self.db.one("SELECT * FROM documents WHERE sha256 = ?", (sha,))
        return dict(r) if r else None

    ALLOWED_FIELDS = {"display_label", "title", "authors", "year", "journal", "doi", "notes",
                      "status", "status_detail", "page_count", "is_scanned", "ocr_used", "metadata_json"}

    def update_document(self, doc_id: int, **fields: Any) -> None:
        cols = [k for k in fields if k in self.ALLOWED_FIELDS]  # column names are whitelisted
        if not cols:
            return
        sets = ", ".join(f"{c} = ?" for c in cols) + ", updated_at = ?"
        self.db.execute(f"UPDATE documents SET {sets} WHERE id = ?",
                        [fields[c] for c in cols] + [time.time(), doc_id])

    def delete_document(self, doc_id: int) -> dict | None:
        doc = self.document(doc_id)
        if doc:
            self.db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return doc

    def counts(self) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) n FROM documents GROUP BY status")
        out = {r["status"]: r["n"] for r in rows}
        out["total"] = sum(out.values())
        out["chunks"] = self.db.one("SELECT COUNT(*) FROM chunks")[0]
        return out

    # ---------------------------------------------------------- collections
    def collections(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT c.*, (SELECT COUNT(*) FROM document_collections dc WHERE dc.collection_id = c.id) AS n "
            "FROM collections c ORDER BY c.name = 'All papers' DESC, c.name")]

    def create_collection(self, name: str, description: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("Collection name cannot be empty")
        existing = self.db.one("SELECT id FROM collections WHERE name = ?", (name,))
        if existing:
            return existing["id"]
        return self.db.execute("INSERT INTO collections(name, description, created_at) VALUES (?,?,?)",
                               (name, description, time.time()))

    def delete_collection(self, cid: int) -> None:
        self.db.execute("DELETE FROM collections WHERE id = ? AND name != 'All papers'", (cid,))

    def default_collection_id(self) -> int:
        return self.db.one("SELECT id FROM collections WHERE name = 'All papers'")["id"]

    def add_to_collection(self, doc_ids: Iterable[int], cid: int) -> None:
        with self.db.tx() as c:
            c.executemany("INSERT OR IGNORE INTO document_collections(doc_id, collection_id) VALUES (?,?)",
                          [(d, cid) for d in doc_ids])

    def remove_from_collection(self, doc_ids: Iterable[int], cid: int) -> None:
        with self.db.tx() as c:
            c.executemany("DELETE FROM document_collections WHERE doc_id = ? AND collection_id = ?",
                          [(d, cid) for d in doc_ids])

    def doc_ids_in_collections(self, cids: Iterable[int]) -> set[int]:
        cids = list(cids)
        if not cids:
            return set()
        q = ",".join("?" * len(cids))
        return {r[0] for r in self.db.query(
            f"SELECT DISTINCT doc_id FROM document_collections WHERE collection_id IN ({q})", cids)}

    # ----------------------------------------------------------------- tags
    def tags(self) -> list[str]:
        return [r[0] for r in self.db.query("SELECT name FROM tags ORDER BY name")]

    def tags_by_doc(self, doc_ids: list[int]) -> dict[int, list[str]]:
        if not doc_ids:
            return {}
        q = ",".join("?" * len(doc_ids))
        out: dict[int, list[str]] = {}
        for r in self.db.query(f"SELECT dt.doc_id, t.name FROM document_tags dt JOIN tags t ON t.id=dt.tag_id "
                               f"WHERE dt.doc_id IN ({q}) ORDER BY t.name", doc_ids):
            out.setdefault(r[0], []).append(r[1])
        return out

    def set_tags(self, doc_id: int, names: Iterable[str]) -> None:
        names = sorted({n.strip() for n in names if n.strip()})
        with self.db.tx() as c:
            c.execute("DELETE FROM document_tags WHERE doc_id = ?", (doc_id,))
            for n in names:
                c.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (n,))
                tid = c.execute("SELECT id FROM tags WHERE name = ?", (n,)).fetchone()[0]
                c.execute("INSERT OR IGNORE INTO document_tags(doc_id, tag_id) VALUES (?,?)", (doc_id, tid))

    # --------------------------------------------------------------- chunks
    def replace_chunks(self, doc_id: int, chunks: list[dict]) -> list[int]:
        ids = []
        with self.db.tx() as c:
            c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            for i, ch in enumerate(chunks):
                cur = c.execute("INSERT INTO chunks(doc_id, page, section, chunk_index, text) VALUES (?,?,?,?,?)",
                                (doc_id, ch["page"], ch.get("section") or "", i, ch["text"]))
                ids.append(cur.lastrowid)
        return ids

    _CHUNK_SELECT = ("SELECT c.id, c.doc_id, c.page, c.section, c.text, c.chunk_index, d.filename, "
                     "COALESCE(NULLIF(d.display_label,''), d.title, d.filename) AS title, d.authors, d.year "
                     "FROM chunks c JOIN documents d ON d.id = c.doc_id")

    def chunks_by_ids(self, ids: list[int]) -> list[Chunk]:
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        rows = self.db.query(f"{self._CHUNK_SELECT} WHERE c.id IN ({q})", ids)
        by_id = {r["id"]: Chunk(**{k: r[k] for k in r.keys()}) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def chunks_for_doc(self, doc_id: int) -> list[Chunk]:
        rows = self.db.query(f"{self._CHUNK_SELECT} WHERE c.doc_id = ? ORDER BY c.chunk_index", (doc_id,))
        return [Chunk(**{k: r[k] for k in r.keys()}) for r in rows]

    def all_chunk_rows(self) -> list[tuple[int, str]]:
        return [(r[0], r[1]) for r in self.db.query(
            "SELECT c.id, c.text FROM chunks c JOIN documents d ON d.id=c.doc_id ORDER BY c.id")]

    def log_import(self, path: str, sha: str | None, doc_id: int | None, status: str, message: str) -> None:
        self.db.execute("INSERT INTO import_log(path, sha256, doc_id, status, message, created_at) "
                        "VALUES (?,?,?,?,?,?)", (path, sha, doc_id, status, message, time.time()))

    def import_log(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM import_log ORDER BY id DESC LIMIT ?", (limit,))]

    def set_metadata(self, doc_id: int, meta: dict) -> None:
        self.update_document(doc_id, metadata_json=dumps(meta))

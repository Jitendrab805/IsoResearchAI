"""Import PDFs into the local library.

Pipeline per file: hash → duplicate check → copy into the library folder →
register (status=processing) → extract → chunk → store → embed/index.

A document is *never* silently dropped: if text extraction fails or yields no
text, it stays in the library with status ``failed`` or ``no_text`` and a
diagnostic message, and the original PDF is kept so it can still be opened.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.db import Database, dumps
from ..core.repository import LibraryRepo
from ..retrieval.search import SearchEngine
from .chunker import chunk_document
from .pdf_extract import extract_pdf

log = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^\w.\- ()]+", "_", Path(name).stem).strip(" ._") or "document"
    return stem[:120] + ".pdf"


def find_pdfs(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(x for x in p.rglob("*") if x.suffix.lower() == ".pdf" and x.is_file())
        elif p.suffix.lower() == ".pdf" and p.is_file():
            out.append(p)
    return out


@dataclass
class ImportResult:
    path: str
    status: str  # indexed | no_text | failed | duplicate
    doc_id: int | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)


class Importer:
    def __init__(self, db: Database, search: SearchEngine, library_dir: Path, *,
                 ocr_enabled: bool = True, ocr_language: str = "eng", tessdata: str = "",
                 chunk_chars: int = 1100, chunk_overlap: int = 150):
        self.db = db
        self.repo = LibraryRepo(db)
        self.search = search
        self.library_dir = Path(library_dir)
        self.ocr = (ocr_enabled, ocr_language, tessdata)
        self.chunk_chars, self.chunk_overlap = chunk_chars, chunk_overlap

    def import_paths(self, paths: list[Path], collection_id: int | None = None,
                     progress: Callable[[int, int, str], None] | None = None,
                     cancel: Callable[[], bool] | None = None) -> list[ImportResult]:
        files = find_pdfs(paths)
        results = []
        for i, f in enumerate(files):
            if cancel and cancel():
                results.append(ImportResult(str(f), "failed", message="Cancelled by user before import"))
                break
            if progress:
                progress(i, len(files), f.name)
            results.append(self.import_file(f, collection_id))
        if progress:
            progress(len(files), len(files), "done")
        return results

    def import_file(self, src: Path, collection_id: int | None = None) -> ImportResult:
        src = Path(src)
        default_cid = self.repo.default_collection_id()
        try:
            sha = sha256_file(src)
        except OSError as exc:
            self.repo.log_import(str(src), None, None, "failed", f"Cannot read file: {exc}")
            return ImportResult(str(src), "failed", message=f"Cannot read file: {exc}")

        existing = self.repo.by_sha(sha)
        if existing:
            cids = {default_cid} | ({collection_id} if collection_id else set())
            for cid in cids:
                self.repo.add_to_collection([existing["id"]], cid)
            msg = f"Duplicate of '{existing['display_label'] or existing['filename']}' (same SHA-256); not imported again."
            self.repo.log_import(str(src), sha, existing["id"], "duplicate", msg)
            return ImportResult(str(src), "duplicate", existing["id"], msg)

        dest = self.library_dir / f"{sha[:12]}_{safe_filename(src.name)}"
        try:
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
        except OSError as exc:
            self.repo.log_import(str(src), sha, None, "failed", f"Could not copy into library: {exc}")
            return ImportResult(str(src), "failed", message=f"Could not copy into library: {exc}")

        now = time.time()
        doc_id = self.db.execute(
            "INSERT INTO documents(sha256, filename, stored_path, display_label, status, imported_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", (sha, src.name, str(dest), "", "processing", now, now))
        for cid in {default_cid} | ({collection_id} if collection_id else set()):
            self.repo.add_to_collection([doc_id], cid)
        return self.process(doc_id, dest, src_label=str(src))

    def process(self, doc_id: int, path: Path, src_label: str = "") -> ImportResult:
        """(Re)extract and index one stored document."""
        sha = self.db.one("SELECT sha256 FROM documents WHERE id=?", (doc_id,))[0]
        try:
            ex = extract_pdf(path, *self.ocr)
        except Exception as exc:  # noqa: BLE001
            msg = f"Text extraction failed: {type(exc).__name__}: {exc}"
            self.repo.update_document(doc_id, status="failed", status_detail=msg)
            self.repo.log_import(src_label or str(path), sha, doc_id, "failed", msg)
            log.warning("Import failed for doc %s: %s", doc_id, type(exc).__name__)
            return ImportResult(src_label, "failed", doc_id, msg)

        g = ex.guessed
        meta = {"pdf_metadata": ex.metadata, "guessed": g, "warnings": ex.warnings}
        fields = dict(page_count=ex.page_count, is_scanned=int(ex.is_scanned), ocr_used=int(ex.ocr_used),
                      metadata_json=dumps(meta))
        cur = self.repo.document(doc_id) or {}
        for key in ("title", "authors", "doi", "year"):
            if not cur.get(key) and g.get(key, {}).get("value"):
                fields[key] = g[key]["value"]

        chunks = chunk_document(ex, self.chunk_chars, self.chunk_overlap)
        old_ids = [r[0] for r in self.db.query("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        if old_ids:
            self.search.remove_chunks(old_ids)
        if not chunks:
            detail = "No extractable text. " + (" ".join(ex.warnings) or
                                                "The PDF may be scanned, image-only or use unusual encoding.")
            fields.update(status="no_text", status_detail=detail)
            self.repo.replace_chunks(doc_id, [])
            self.repo.update_document(doc_id, **fields)
            self.repo.log_import(src_label or str(path), sha, doc_id, "no_text", detail)
            return ImportResult(src_label, "no_text", doc_id, detail, ex.warnings)

        ids = self.repo.replace_chunks(doc_id, chunks)
        try:
            self.search.index_chunks(ids, [c["text"] for c in chunks])
        except Exception as exc:  # noqa: BLE001
            msg = f"Text extracted but indexing failed: {exc}. Use Settings → Rebuild index."
            fields.update(status="failed", status_detail=msg)
            self.repo.update_document(doc_id, **fields)
            self.repo.log_import(src_label or str(path), sha, doc_id, "failed", msg)
            return ImportResult(src_label, "failed", doc_id, msg, ex.warnings)

        detail = f"{len(chunks)} passages from {ex.page_count} pages" + (" (OCR)" if ex.ocr_used else "")
        if ex.warnings:
            detail += ". " + " ".join(ex.warnings)
        fields.update(status="indexed", status_detail=detail)
        self.repo.update_document(doc_id, **fields)
        self.repo.log_import(src_label or str(path), sha, doc_id, "indexed", detail)
        return ImportResult(src_label, "indexed", doc_id, detail, ex.warnings)

    def remove(self, doc_id: int, delete_file: bool = True) -> bool:
        ids = [r[0] for r in self.db.query("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        doc = self.repo.delete_document(doc_id)
        if not doc:
            return False
        self.search.remove_chunks(ids)
        p = Path(doc["stored_path"])
        if delete_file and p.exists():
            try:  # only delete files that live inside our library folder
                p.resolve().relative_to(self.library_dir.resolve())
                p.unlink()
            except (ValueError, OSError):
                pass
        self.repo.log_import(doc["filename"], doc["sha256"], None, "removed", "Removed by user")
        return True

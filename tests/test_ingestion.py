from pathlib import Path

import pytest

from conftest import make_scanned_pdf
from isoresearch.ingest.pdf_extract import ocr_available


def test_import_extracts_pages_sections_metadata(app_ctx, pdfs):
    res = app_ctx.importer.import_paths([pdfs["a"]])
    assert [r.status for r in res] == ["indexed"]
    doc = app_ctx.repo.document(res[0].doc_id)
    assert doc["page_count"] == 3
    assert doc["title"].startswith("Synthetic Study of Amount Effect")
    assert doc["doi"] == "10.9999/synthetic.2024.001"
    assert Path(doc["stored_path"]).exists()
    assert Path(doc["stored_path"]).parent == app_ctx.settings.library_dir
    chunks = app_ctx.repo.chunks_for_doc(doc["id"])
    sections = {c.section for c in chunks}
    assert {"Abstract", "2. Data and methods", "4. Limitations"} <= sections
    lim = [c for c in chunks if c.section == "4. Limitations"][0]
    assert lim.page == 3 and lim.filename == "paper_a.pdf"
    assert all(c.page in (1, 2, 3) for c in chunks)


def test_folder_import_and_duplicates(app_ctx, pdfs):
    first = app_ctx.importer.import_paths([pdfs["dir"]])
    assert sorted(r.status for r in first) == ["indexed", "indexed"]
    again = app_ctx.importer.import_paths([pdfs["a"]])
    assert again[0].status == "duplicate"
    assert app_ctx.repo.counts()["total"] == 2
    log = app_ctx.repo.import_log()
    assert any(r["status"] == "duplicate" for r in log)


def test_scanned_pdf_without_ocr_is_kept_and_flagged(app_ctx, tmp_path):
    app_ctx.settings.set("ocr.enabled", False)
    app_ctx.reload_importer()
    p = make_scanned_pdf(tmp_path / "scan.pdf")
    r = app_ctx.importer.import_file(p)
    assert r.status == "no_text"
    doc = app_ctx.repo.document(r.doc_id)
    assert doc is not None and "scanned" in doc["status_detail"].lower()
    assert Path(doc["stored_path"]).exists()  # never silently discarded


@pytest.mark.skipif(not ocr_available(), reason="Tesseract OCR not installed")
def test_scanned_pdf_with_local_ocr(app_ctx, tmp_path):
    p = make_scanned_pdf(tmp_path / "scan.pdf")
    r = app_ctx.importer.import_file(p)
    assert r.status == "indexed"
    doc = app_ctx.repo.document(r.doc_id)
    assert doc["ocr_used"] == 1
    text = " ".join(c.text for c in app_ctx.repo.chunks_for_doc(r.doc_id)).lower()
    assert "deuterium" in text


def test_corrupt_pdf_recorded_as_failed(app_ctx, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    r = app_ctx.importer.import_file(bad)
    assert r.status == "failed"
    doc = app_ctx.repo.document(r.doc_id)
    assert doc["status"] == "failed" and "extraction failed" in doc["status_detail"].lower()


def test_remove_document_deletes_copy_and_index(app_ctx, pdfs):
    r = app_ctx.importer.import_file(pdfs["a"])
    stored = Path(app_ctx.repo.document(r.doc_id)["stored_path"])
    n_before = len(app_ctx.search.index)
    assert app_ctx.importer.remove(r.doc_id)
    assert not stored.exists()
    assert pdfs["a"].exists()  # the user's original is untouched
    assert len(app_ctx.search.index) < n_before
    assert app_ctx.repo.document(r.doc_id) is None
    assert app_ctx.search.keyword("amount effect") == []

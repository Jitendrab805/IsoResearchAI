"""Shared fixtures.  All PDFs here are generated on the fly with synthetic,
original text written for testing — no real papers are used."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PAPER_A = {
    "title": "Synthetic Study of Amount Effect in Island Monsoon Rainfall",
    "author": "A. Example; B. Placeholder",
    "pages": [
        [("h", "Abstract"),
         ("p", "This synthetic test document describes rainfall isotopes at an island station. "
               "Daily rainfall delta 18O values were more depleted during heavy convective events, "
               "which is consistent with the amount effect. DOI: 10.9999/synthetic.2024.001"),
         ("h", "1. Introduction"),
         ("p", "Stable water isotopes record moisture source and convective history. Rayleigh distillation "
               "progressively depletes the heavy isotopes in remaining vapour.")],
        [("h", "2. Data and methods"),
         ("p", "Rainfall samples were collected after each event and analysed with a laser spectrometer. "
               "Deuterium excess was computed as d = δ2H − 8·δ18O. Back trajectories were computed for 120 hours."),
         ("h", "3. Results"),
         ("p", "The regression of δ18O on rainfall amount gave a negative slope. Model simulations with an "
               "isotope-enabled regional model reproduced the seasonal cycle but underestimated event depletion.")],
        [("h", "4. Limitations"),
         ("p", "The record covers only one monsoon season, so interannual variability could not be assessed. "
               "Future work should evaluate the model against vapour isotope observations.")],
    ],
}
PAPER_B = {
    "title": "Synthetic Evaluation of Satellite Vapour Isotope Retrievals",
    "author": "C. Testauthor",
    "pages": [
        [("h", "Abstract"),
         ("p", "This synthetic document compares satellite retrievals of vapour δD with in-situ observations. "
               "Averaging kernels were applied to model profiles before comparison with the retrievals.")],
        [("h", "2. Methods"),
         ("p", "The a priori profile and averaging kernel matrix were used to smooth simulated vertical profiles. "
               "Mean bias and root mean square error were computed for the lower troposphere.")],
    ],
}


def make_pdf(path: Path, spec: dict) -> Path:
    doc = pymupdf.open()
    for blocks in spec["pages"]:
        page = doc.new_page()
        y = 72
        if page.number == 0:
            page.insert_textbox(pymupdf.Rect(72, y, 540, y + 60), spec["title"], fontsize=18, fontname="hebo")
            y += 70
        for kind, text in blocks:
            if kind == "h":
                page.insert_text((72, y + 14), text, fontsize=13, fontname="hebo")
                y += 30
            else:
                rect = pymupdf.Rect(72, y, 540, y + 160)
                page.insert_textbox(rect, text, fontsize=10, fontname="helv")
                y += 20 + 14 * (len(text) // 85 + 1)
    doc.set_metadata({"title": spec["title"], "author": spec["author"], "creationDate": "D:20240101000000"})
    doc.save(str(path))
    doc.close()
    return path


def make_scanned_pdf(path: Path, with_text_image: bool = True) -> Path:
    """An image-only page (renders text into a pixmap so OCR has something to read)."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(72, 72, 540, 300),
                     "Scanned page about deuterium excess in rainfall. The samples show higher "
                     "d-excess values during the post-monsoon season at the island station.", fontsize=16) if with_text_image else None
    pix = p.get_pixmap(dpi=150)
    out = pymupdf.open()
    page = out.new_page()
    page.insert_image(page.rect, pixmap=pix)
    out.save(str(path))
    return path


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("ISORESEARCH_HOME", str(tmp_path / "home"))
    from isoresearch.context import AppContext

    ctx = AppContext.create(enforce_offline=False)
    yield ctx
    ctx.close()


@pytest.fixture()
def pdfs(tmp_path):
    d = tmp_path / "pdfs"
    d.mkdir()
    return {"a": make_pdf(d / "paper_a.pdf", PAPER_A), "b": make_pdf(d / "paper_b.pdf", PAPER_B), "dir": d}

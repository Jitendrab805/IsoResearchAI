"""PDF text extraction with PyMuPDF, preserving pages and section headings.

Scanned (image-only) pages are detected; if OCR is enabled and a local
Tesseract installation is found, PyMuPDF's OCR text page is used.  Nothing is
sent anywhere — OCR runs entirely on this computer.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)

HEADING_WORDS = re.compile(
    r"^(\d+(\.\d+)*\.?\s+)?(abstract|introduction|background|data|data and methods?|methods?|methodology|"
    r"materials and methods|study (area|region|site)|model(s| description| set-?up)?|experimental design|"
    r"observations?|results?( and discussion)?|discussion|summary|conclusions?|concluding remarks|"
    r"limitations?|future work|outlook|acknowledg(e)?ments?|references|bibliography|appendix\b.*|"
    r"supplementary.*|keywords?)\s*:?$", re.I)
NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+){0,3})\.?\s+[A-Z][^.!?]{2,90}$")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;)\]])", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


@dataclass
class Block:
    kind: str  # "heading" | "para"
    text: str


@dataclass
class PageText:
    number: int  # 1-based
    blocks: list[Block] = field(default_factory=list)
    ocr: bool = False

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass
class Extracted:
    pages: list[PageText]
    metadata: dict
    page_count: int
    is_scanned: bool = False
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)
    guessed: dict = field(default_factory=dict)  # title/doi/year/authors with confidence

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)


def find_tessdata(configured: str = "") -> str | None:
    candidates = [configured, os.environ.get("TESSDATA_PREFIX", "")]
    exe = shutil.which("tesseract")
    if exe:
        base = Path(exe).resolve().parent
        candidates += [str(base / "tessdata"), str(base.parent / "share" / "tessdata")]
    candidates += [
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata", "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata",
    ]
    for c in candidates:
        if c and Path(c).is_dir() and any(Path(c).glob("*.traineddata")):
            return str(c)
    return None


def ocr_available(configured: str = "") -> bool:
    return find_tessdata(configured) is not None


def _clean(text: str) -> str:
    text = text.replace("\u00ad", "")  # soft hyphen
    text = re.sub(r"-\n(?=[a-z])", "", text)  # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _page_blocks(page: "pymupdf.Page", body_size: float, textpage=None, ocr: bool = False) -> list[Block]:
    data = page.get_text("dict", textpage=textpage, sort=True)
    out: list[Block] = []
    for b in data.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines_txt, sizes, bold_chars, chars = [], [], 0, 0
        for line in b.get("lines", []):
            spans = line.get("spans", [])
            t = "".join(s.get("text", "") for s in spans)
            if t.strip():
                lines_txt.append(t)
            for s in spans:
                n = len(s.get("text", "").strip())
                chars += n
                sizes.append(s.get("size", body_size))
                if s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower():
                    bold_chars += n
        text = _clean("\n".join(lines_txt))
        if not text:
            continue
        size = max(sizes) if sizes else body_size
        one_line = "\n" not in text and len(text) < 110
        is_bold = chars and bold_chars / chars > 0.6
        if ocr:  # font sizes from OCR are unreliable; only trust heading words
            is_heading = bool(one_line and HEADING_WORDS.match(text))
        else:
            is_heading = one_line and (
            HEADING_WORDS.match(text)
            or (NUMBERED_HEADING.match(text) and (is_bold or size > body_size * 1.05))
            or (size >= body_size * 1.2 and len(text.split()) <= 14 and not text.endswith("."))
        )
        if is_heading:
            out.append(Block("heading", re.sub(r"\s+", " ", text)))
        else:
            out.append(Block("para", re.sub(r"\s*\n\s*", " ", text)))
    return out


def _body_font_size(doc: "pymupdf.Document", max_pages: int = 6) -> float:
    sizes: list[float] = []
    for page in list(doc)[:max_pages]:
        for b in page.get_text("dict").get("blocks", []):
            for line in b.get("lines", []):
                for s in line.get("spans", []):
                    sizes.extend([round(s.get("size", 10), 1)] * max(1, len(s.get("text", "")) // 10))
    return statistics.median(sizes) if sizes else 10.0


def _guess_title(doc: "pymupdf.Document", meta_title: str) -> tuple[str, str]:
    bad = {"", "untitled", "microsoft word", "pdf", "document"}
    if meta_title and meta_title.strip().lower() not in bad and len(meta_title) > 8 \
            and not meta_title.lower().endswith((".doc", ".docx", ".pdf", ".tex", ".dvi")):
        return meta_title.strip(), "medium"
    if len(doc) == 0:
        return "", "low"
    page = doc[0]
    best, best_size = "", 0.0
    for b in page.get_text("dict").get("blocks", []):
        for line in b.get("lines", []):
            t = "".join(s["text"] for s in line["spans"]).strip()
            sz = max((s["size"] for s in line["spans"]), default=0)
            if len(t) > 6 and line["bbox"][1] < page.rect.height * 0.5:
                if sz > best_size + 0.5:
                    best, best_size = t, sz
                elif abs(sz - best_size) <= 0.5 and best and len(best) < 250:
                    best = f"{best} {t}"
    return best.strip(), ("low" if best else "low")


def extract_pdf(path: Path, ocr_enabled: bool = True, ocr_language: str = "eng",
                tessdata: str = "") -> Extracted:
    """Extract text + structure.  Raises on unreadable/encrypted files."""
    doc = pymupdf.open(str(path))
    try:
        if doc.needs_pass:
            raise ValueError("PDF is password-protected; remove the password and import again.")
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        body = _body_font_size(doc)
        pages: list[PageText] = []
        warnings: list[str] = []
        scanned_pages = 0
        ocr_used = False
        tess = find_tessdata(tessdata) if ocr_enabled else None
        for i, page in enumerate(doc):
            raw = page.get_text("text").strip()
            has_images = bool(page.get_images(full=False))
            looks_scanned = len(raw) < 25 and has_images
            pt = PageText(number=i + 1)
            if looks_scanned:
                scanned_pages += 1
                if tess:
                    try:
                        tp = page.get_textpage_ocr(language=ocr_language, dpi=300, full=True, tessdata=tess)
                        pt.blocks = _page_blocks(page, body, textpage=tp, ocr=True)
                        pt.ocr = True
                        ocr_used = True
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"OCR failed on page {i + 1}: {exc}")
            else:
                pt.blocks = _page_blocks(page, body)
            pages.append(pt)
        is_scanned = scanned_pages > 0 and scanned_pages >= max(1, len(doc) // 2)
        if scanned_pages and not tess:
            warnings.append(f"{scanned_pages} page(s) appear to be scanned images. "
                            + ("OCR is disabled in Settings." if not ocr_enabled
                               else "No local Tesseract OCR installation was found."))
        # bibliographic guesses (with explicit confidence)
        first_text = " ".join(p.text for p in pages[:2])
        title, tconf = _guess_title(doc, meta.get("title", ""))
        guessed: dict = {"title": {"value": title, "confidence": tconf, "method": "pdf metadata/layout"}}
        m = DOI_RE.search(first_text) or DOI_RE.search(meta.get("subject", "") + " " + meta.get("keywords", ""))
        if m:
            guessed["doi"] = {"value": m.group(1).rstrip("."), "confidence": "high", "method": "found in text"}
        if meta.get("author"):
            guessed["authors"] = {"value": meta["author"], "confidence": "medium", "method": "pdf metadata"}
        years = YEAR_RE.findall(first_text[:4000])
        if years:
            yr = max(set(years), key=years.count)
            guessed["year"] = {"value": int(yr), "confidence": "low", "method": "most frequent year on first pages"}
        elif meta.get("creationDate", "").startswith("D:"):
            guessed["year"] = {"value": int(meta["creationDate"][2:6]), "confidence": "low",
                               "method": "PDF creation date"}
        return Extracted(pages=pages, metadata=meta, page_count=len(doc), is_scanned=is_scanned,
                         ocr_used=ocr_used, warnings=warnings, guessed=guessed)
    finally:
        doc.close()

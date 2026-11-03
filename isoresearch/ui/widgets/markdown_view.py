"""Markdown + LaTeX rendering for chat bubbles (fully local).

* Markdown → HTML with the ``markdown`` package (tables, fenced code).
* LaTeX ($…$, $$…$$, \\(…\\), \\[…\\]) → PNG via Matplotlib *mathtext*,
  cached and served to QTextBrowser through a custom ``math:`` URL scheme.
  Unsupported TeX falls back to monospace source, never to a network renderer.
"""
from __future__ import annotations

import hashlib
import html
import io
import re

import markdown as md_lib
import matplotlib
from matplotlib import mathtext
from matplotlib.font_manager import FontProperties
from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QSizePolicy, QTextBrowser

_MATH_CACHE: dict[str, QImage] = {}

FENCE = re.compile(r"```[^\n]*\n.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]+`")
DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
INLINE = re.compile(r"(?<![\\$\w])\$(?![\s$])([^$\n]{1,300}?)(?<![\s\\])\$(?![\w$])|\\\((.+?)\\\)")

TEX_FIXES = [(r"\\text\{", r"\\mathrm{"), (r"\\operatorname\{", r"\\mathrm{"), (r"\\tfrac", r"\\frac"),
             (r"\\dfrac", r"\\frac"), (r"\\,", r"\\ "), (r"\\!", ""), (r"\\permil", r"‰"), (r"\\textperthousand", "‰")]


def _tex_image(tex: str, color: str, display: bool) -> tuple[str, int, int] | None:
    key = hashlib.sha1(f"{tex}|{color}|{display}".encode()).hexdigest()[:16]
    if key in _MATH_CACHE:
        img = _MATH_CACHE[key]
        return key, img.width(), img.height()
    src = tex.strip()
    for a, b in TEX_FIXES:
        src = re.sub(a, b, src)
    buf = io.BytesIO()
    try:
        with matplotlib.rc_context({"savefig.transparent": True}):
            mathtext.math_to_image(f"${src}$", buf, prop=FontProperties(size=15 if display else 12.5),
                                   dpi=200, format="png", color=color)
    except Exception:  # noqa: BLE001 - unsupported construct
        return None
    img = QImage.fromData(buf.getvalue(), "PNG")
    if img.isNull():
        return None
    _MATH_CACHE[key] = img
    return key, img.width(), img.height()


def render_markdown(text: str, text_color: str = "#e4e8ea", css: str = "") -> tuple[str, list[str]]:
    """Return (html, code_blocks)."""
    stash: list[str] = []

    def keep(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00CODE{len(stash) - 1}\x00"

    work = FENCE.sub(keep, text or "")
    work = INLINE_CODE.sub(keep, work)
    maths: list[tuple[str, bool]] = []

    def m_display(m: re.Match) -> str:
        maths.append(((m.group(1) or m.group(2) or "").strip(), True))
        return f"\n\nMATHPH{len(maths) - 1}Z\n\n"

    def m_inline(m: re.Match) -> str:
        maths.append(((m.group(1) or m.group(2) or "").strip(), False))
        return f"MATHPH{len(maths) - 1}Z"

    work = DISPLAY.sub(m_display, work)
    work = INLINE.sub(m_inline, work)
    work = re.sub(r"\x00CODE(\d+)\x00", lambda m: stash[int(m.group(1))], work)
    codes = [re.sub(r"^```[^\n]*\n|```$", "", c.strip()) for c in FENCE.findall(work)]
    body = md_lib.markdown(work, extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
                           output_format="html")

    def put_math(m: re.Match) -> str:
        tex, display = maths[int(m.group(1))]
        r = _tex_image(tex, text_color, display)
        if r is None:
            src = html.escape(tex)
            return f"<pre>{src}</pre>" if display else f"<code>{src}</code>"
        key, w, h = r
        tag = f'<img src="math:{key}" width="{w // 2}" height="{h // 2}" style="vertical-align: middle">'
        return f'<p align="center">{tag}</p>' if display else tag

    body = re.sub(r"\n</code></pre>", "</code></pre>", body)
    body = re.sub(r"<p>\s*MATHPH(\d+)Z\s*</p>", put_math, body)
    body = re.sub(r"MATHPH(\d+)Z", put_math, body)
    counter = iter(range(10_000))
    body = re.sub(r"<pre>", lambda m: f'<a class="copy" href="iso://copycode/{next(counter)}">⧉ Copy code</a><pre>',
                  body)
    body = body.replace('<a href="iso://cite/', '<a class="cite" href="iso://cite/')
    return f"<html><head><style>{css}</style></head><body>{body}</body></html>", codes


class MarkdownView(QTextBrowser):
    """Auto-height, read-only rich text view that emits clicked links."""

    linkActivated = Signal(QUrl)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Markdown")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self.linkActivated.emit)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.code_blocks: list[str] = []
        self.raw_markdown = ""

    def loadResource(self, rtype, url: QUrl):  # noqa: N802 (Qt override)
        if url.scheme() == "math":
            img = _MATH_CACHE.get(url.path() or url.toString().split(":", 1)[-1])
            if img is not None:
                return img
        if url.scheme() in ("http", "https", "ftp"):
            return None  # never fetch remote resources
        return super().loadResource(rtype, url)

    def set_markdown(self, text: str, color: str, css: str) -> None:
        self.raw_markdown = text
        html_text, self.code_blocks = render_markdown(text, color, css)
        sb = self.horizontalScrollBar().value()
        self.setHtml(html_text)
        self.horizontalScrollBar().setValue(sb)
        self._fit()

    def set_plain(self, text: str) -> None:
        self.raw_markdown = text
        self.setPlainText(text)
        self._fit()

    def _fit(self, *_):
        self.document().setTextWidth(self.viewport().width())
        h = int(self.document().size().height()) + 6
        if self.horizontalScrollBar().isVisible():
            h += self.horizontalScrollBar().height()
        if self.height() != h:
            self.setFixedHeight(max(h, 20))

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._fit()

    def sizeHint(self) -> QSize:
        return QSize(400, int(self.document().size().height()) + 6)


def plain_doc_text(html_text: str) -> str:
    d = QTextDocument()
    d.setHtml(html_text)
    return d.toPlainText()

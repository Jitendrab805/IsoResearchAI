"""Chat bubbles, source cards, composer and the scrolling chat view."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..icons import icon, logo_pixmap
from ...research.citations import link_markers
from ..theme import Palette, markdown_css
from .common import button, label
from .markdown_view import MarkdownView


class SourceCard(QFrame):
    open_requested = Signal(dict)
    selected = Signal(dict)

    def __init__(self, cit: dict, pal: Palette, compact: bool = False):
        super().__init__()
        self.cit = cit
        self.setObjectName("SourceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        top = QHBoxLayout()
        tag = label(f"S{cit.get('n', '?')}", "Pill")
        tag.setProperty("state", "accent")
        top.addWidget(tag)
        who = []
        if cit.get("authors"):
            who.append(str(cit["authors"]).split(";")[0].strip())
        if cit.get("year"):
            who.append(str(cit["year"]))
        title = cit.get("title") or cit.get("filename", "")
        t = label(f"<b>{_esc(title)}</b>", wrap=True)
        top.addWidget(t, 1)
        lay.addLayout(top)
        meta = f"{', '.join(who) + ' · ' if who else ''}p. {cit.get('page')} · {cit.get('section') or 'section n/a'}"
        lay.addWidget(label(meta, "Faint", wrap=True))
        if not compact and cit.get("excerpt"):
            ex = label(_esc(cit["excerpt"][:260]) + "…", "Muted", wrap=True)
            lay.addWidget(ex)
        row = QHBoxLayout()
        row.addStretch(1)
        b = button(f"Open p. {cit.get('page')}", "pdf", "Link", tip="Open the PDF at this page", color=pal.accent)
        b.clicked.connect(lambda: self.open_requested.emit(self.cit))
        row.addWidget(b)
        lay.addLayout(row)

    def mousePressEvent(self, e):  # noqa: N802
        self.selected.emit(self.cit)
        super().mousePressEvent(e)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MessageBubble(QFrame):
    open_source = Signal(dict)
    select_source = Signal(dict)
    action = Signal(str)  # e.g. "settings", "retry"

    def __init__(self, role: str, text: str, pal: Palette, citations: list[dict] | None = None,
                 model: str = "", when: float | None = None):
        super().__init__()
        self.role, self.pal = role, pal
        self.citations = citations or []
        self.setObjectName({"user": "UserBubble", "error": "ErrorBubble"}.get(role, "AssistantBubble"))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        av = QLabel()
        if role == "user":
            av.setPixmap(icon("chat-plus", pal.muted).pixmap(16, 16))
            name = "You"
        elif role == "error":
            av.setPixmap(icon("alert", pal.danger).pixmap(16, 16))
            name = "Not available"
        elif role == "library":
            av.setPixmap(icon("search", pal.accent).pixmap(16, 16))
            name = "Library search (no AI)"
        else:
            av.setPixmap(logo_pixmap(18))
            name = "IsoResearch AI"
        head.addWidget(av)
        head.addWidget(label(f"<b>{name}</b>"))
        if model:
            mp = label(model, "Pill")
            head.addWidget(mp)
        self.status = label("", "Faint")
        head.addWidget(self.status)
        head.addStretch(1)
        ts = time.strftime("%H:%M", time.localtime(when or time.time()))
        head.addWidget(label(ts, "Faint"))
        if role in ("assistant", "user", "library"):
            cp = button("", "copy", "Ghost", "Copy text", pal.muted, self.copy_text)
            head.addWidget(cp)
            if role != "user":
                cm = button("", "export", "Ghost", "Copy as Markdown (with citations)", pal.muted, self.copy_markdown)
                head.addWidget(cm)
        lay.addLayout(head)
        self.view = MarkdownView()
        self.view.linkActivated.connect(self._link)
        lay.addWidget(self.view)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(6)
        lay.addLayout(self.extra)
        self.src_toggle: QPushButton | None = None
        self.src_box: QWidget | None = None
        self.set_text(text)
        if self.citations:
            self.set_citations(self.citations)

    # ------------------------------------------------------------------ content
    def set_text(self, text: str) -> None:
        if self.role == "user":
            self.view.set_markdown(_esc(text).replace("\n", "  \n"), self.pal.text, markdown_css(self.pal))
        else:
            self.view.set_markdown(link_markers(text), self.pal.text, markdown_css(self.pal))
            self.view.raw_markdown = text

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def add_action(self, text: str, key: str, primary: bool = False) -> None:
        b = button(text, kind="Primary" if primary else None)
        b.clicked.connect(lambda: self.action.emit(key))
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        self.extra.addLayout(row)

    def set_citations(self, cits: list[dict]) -> None:
        self.citations = cits
        if self.src_box:
            self.src_box.deleteLater()
            self.src_toggle.deleteLater()
        shown = [c for c in cits if c.get("used", True)] or cits
        if not shown:
            return
        self.src_toggle = QPushButton(f"  Sources ({len(shown)})")
        self.src_toggle.setObjectName("Ghost")
        self.src_toggle.setCheckable(True)
        self.src_toggle.setIcon(icon("chevron-right", self.pal.muted))
        self.src_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.src_box = QWidget()
        bl = QVBoxLayout(self.src_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        for c in shown:
            card = SourceCard(c, self.pal)
            card.open_requested.connect(self.open_source.emit)
            card.selected.connect(self.select_source.emit)
            bl.addWidget(card)
        self.src_box.setVisible(False)
        self.src_toggle.toggled.connect(self._toggle_sources)
        row = QHBoxLayout()
        row.addWidget(self.src_toggle)
        row.addStretch(1)
        self.extra.addLayout(row)
        self.extra.addWidget(self.src_box)

    def _toggle_sources(self, on: bool) -> None:
        self.src_box.setVisible(on)
        self.src_toggle.setIcon(icon("chevron-down" if on else "chevron-right", self.pal.muted))

    # ------------------------------------------------------------------ actions
    def _link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("iso://cite/"):
            n = int(s.rsplit("/", 1)[-1])
            for c in self.citations:
                if c.get("n") == n:
                    self.select_source.emit(c)
                    self.open_source.emit(c)
                    return
        elif s.startswith("iso://copycode/"):
            i = int(s.rsplit("/", 1)[-1])
            if i < len(self.view.code_blocks):
                QGuiApplication.clipboard().setText(self.view.code_blocks[i])
                self.set_status("code copied ✓")
                QTimer.singleShot(1800, lambda: self.set_status(""))
        elif s.startswith("iso://action/"):
            self.action.emit(s.rsplit("/", 1)[-1])

    def copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self.view.toPlainText())
        self.set_status("copied ✓")
        QTimer.singleShot(1800, lambda: self.set_status(""))

    def copy_markdown(self) -> None:
        QGuiApplication.clipboard().setText(self.view.raw_markdown)
        self.set_status("Markdown copied ✓")
        QTimer.singleShot(1800, lambda: self.set_status(""))


class ThinkingDots(QLabel):
    def __init__(self, text: str = "Searching your library"):
        super().__init__()
        self.setObjectName("Faint")
        self.base = text
        self.n = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(350)
        self._tick()

    def set_base(self, t: str) -> None:
        self.base = t

    def _tick(self):
        self.n = (self.n + 1) % 4
        self.setText(self.base + "." * self.n)


class ChatView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("Workspace")
        outer = QHBoxLayout(self.inner)
        outer.setContentsMargins(0, 0, 0, 0)
        col = QWidget()
        col.setMaximumWidth(920)
        self.lay = QVBoxLayout(col)
        self.lay.setContentsMargins(24, 20, 24, 20)
        self.lay.setSpacing(14)
        self.lay.addStretch(1)
        outer.addStretch(1)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        self.setWidget(self.inner)
        self._stick = True
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)
        self.verticalScrollBar().valueChanged.connect(self._value_changed)

    def add(self, w: QWidget, align_right: bool = False) -> QWidget:
        if align_right:
            wrap = QWidget()
            h = QHBoxLayout(wrap)
            h.setContentsMargins(80, 0, 0, 0)
            h.addWidget(w)
            self.lay.insertWidget(self.lay.count(), wrap)
        else:
            self.lay.insertWidget(self.lay.count(), w)
        self._stick = True
        return w

    def clear(self) -> None:
        while self.lay.count() > 1:
            item = self.lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

    def _value_changed(self, v: int) -> None:
        sb = self.verticalScrollBar()
        self._stick = v >= sb.maximum() - 40

    def _range_changed(self, _min: int, mx: int) -> None:
        if self._stick:
            self.verticalScrollBar().setValue(mx)


class ComposerInput(QPlainTextEdit):
    submitted = Signal()
    focus_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("ComposerInput")
        self.setPlaceholderText("Ask about isotope processes, your papers, models or plots…   "
                                "(Enter to send · Shift+Enter for a new line)")
        self.setTabChangesFocus(True)
        self.document().contentsChanged.connect(self._grow)
        self.setMinimumHeight(48)
        self._grow()

    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):  # noqa: N802
        self.focus_changed.emit(True)
        super().focusInEvent(e)

    def focusOutEvent(self, e):  # noqa: N802
        self.focus_changed.emit(False)
        super().focusOutEvent(e)

    def _grow(self):
        h = int(self.document().size().height() * self.fontMetrics().lineSpacing()) + 18
        self.setFixedHeight(max(52, min(h, 220)))

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            e.accept()
            return True
        return super().event(e)

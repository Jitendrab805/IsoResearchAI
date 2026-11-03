"""Right-hand context panel: scope, selected documents, passages, metadata, topic & filters."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .state import AppState
from .widgets.chat_widgets import SourceCard
from .widgets.common import button, label


class ContextPanel(QFrame):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.setObjectName("ContextPanel")
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        pal = state.pal
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setMinimumWidth(0)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        lay.addWidget(label("RESEARCH CONTEXT", "Eyebrow"))
        # topic & filters
        lay.addWidget(label("Active research topic", "Muted", wrap=True))
        self.topic = QLineEdit(state.topic)
        self.topic.setPlaceholderText("e.g. amount effect at Port Blair")
        self.topic.editingFinished.connect(self._topic)
        lay.addWidget(self.topic)
        yr = QHBoxLayout()
        yr.addWidget(label("Years", "Faint"))
        self.ymin, self.ymax = QSpinBox(), QSpinBox()
        for s, v in ((self.ymin, 0), (self.ymax, 0)):
            s.setRange(0, 2100)
            s.setSpecialValueText("any")
            s.setValue(v)
            s.valueChanged.connect(self._years)
            yr.addWidget(s)
        lay.addLayout(yr)
        # collections
        lay.addWidget(label("Collections in scope (none ticked = whole library)", "Muted", wrap=True))
        self.colls = QListWidget()
        self.colls.setMaximumHeight(130)
        self.colls.itemChanged.connect(self._colls)
        lay.addWidget(self.colls)
        # selected documents
        hdr = QHBoxLayout()
        hdr.addWidget(label("Selected documents", "Muted", wrap=True))
        hdr.addStretch(1)
        hdr.addWidget(button("Clear", kind="Ghost", slot=self._clear_docs))
        lay.addLayout(hdr)
        self.docs = QListWidget()
        self.docs.setMaximumHeight(110)
        lay.addWidget(self.docs)
        self.scope_note = label("", "Faint", wrap=True)
        lay.addWidget(self.scope_note)
        # passages
        lay.addWidget(label("Relevant source passages", "Muted", wrap=True))
        self.passages = QVBoxLayout()
        self.passages.setSpacing(6)
        lay.addLayout(self.passages)
        self.no_passages = label("Passages retrieved for the latest question appear here.", "Faint", wrap=True)
        lay.addWidget(self.no_passages)
        # metadata
        lay.addWidget(label("Paper metadata", "Muted", wrap=True))
        self.meta = label("Click a source or a paper to see its details.", wrap=True, selectable=True)
        self.meta.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.meta)
        self.open_btn = button("Open PDF", "pdf", color=pal.muted)
        self.open_btn.hide()
        lay.addWidget(self.open_btn)
        lay.addStretch(1)
        sc.setWidget(body)
        outer.addWidget(sc)

        state.library_changed.connect(self.refresh_collections)
        state.scope_changed.connect(self.refresh_docs)
        state.sources_changed.connect(self.show_sources)
        state.source_selected.connect(self.show_meta)
        self.refresh_collections()
        self.refresh_docs()

    def refresh_collections(self) -> None:
        self.colls.blockSignals(True)
        self.colls.clear()
        for c in self.ctx.repo.collections():
            if c["name"] == "All papers":
                continue
            it = QListWidgetItem(f"{c['name']} ({c['n']})")
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c["id"] in self.state.scope_collections else Qt.CheckState.Unchecked)
            self.colls.addItem(it)
        if self.colls.count() == 0:
            it = QListWidgetItem("No collections yet — create them in the Library")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.colls.addItem(it)
        self.colls.blockSignals(False)
        self.refresh_docs()

    def _colls(self, _it=None) -> None:
        self.state.scope_collections = [self.colls.item(i).data(Qt.ItemDataRole.UserRole)
                                        for i in range(self.colls.count())
                                        if self.colls.item(i).checkState() == Qt.CheckState.Checked
                                        and self.colls.item(i).data(Qt.ItemDataRole.UserRole)]
        self.state.scope_changed.emit()

    def refresh_docs(self) -> None:
        self.docs.clear()
        for i in sorted(self.state.scope_docs):
            d = self.ctx.repo.document(i)
            if d:
                self.docs.addItem(d.get("display_label") or d.get("title") or d["filename"])
        if not self.state.scope_docs:
            self.docs.addItem("All documents (no manual selection)")
        ids = self.state.scope_doc_ids()
        self.scope_note.setText("Chat retrieval uses the whole library." if ids is None else
                                f"Chat retrieval is limited to {len(ids)} paper(s).")

    def _clear_docs(self) -> None:
        self.state.scope_docs = set()
        self.state.scope_changed.emit()

    def _topic(self) -> None:
        self.state.topic = self.topic.text().strip()
        self.state.scope_changed.emit()

    def _years(self) -> None:
        self.state.year_min = self.ymin.value() or None
        self.state.year_max = self.ymax.value() or None
        self.state.scope_changed.emit()

    def show_sources(self, cits: list) -> None:
        while self.passages.count():
            w = self.passages.takeAt(0).widget()
            if w:
                w.deleteLater()
        shown = [c for c in cits if c.get("used", True)] or cits
        self.no_passages.setVisible(not shown)
        for c in shown[:10]:
            card = SourceCard(c, self.state.pal, compact=True)
            card.open_requested.connect(lambda cc: self.state.open_pdf.emit(int(cc["doc_id"]), int(cc["page"])))
            card.selected.connect(self.show_meta)
            self.passages.addWidget(card)

    def show_meta(self, c: dict) -> None:
        d = self.ctx.repo.document(int(c.get("doc_id", 0) or 0))
        if not d:
            return
        pal = self.state.pal
        rows = [("Title", d.get("title") or d.get("display_label") or d["filename"]), ("Authors", d.get("authors")),
                ("Year", d.get("year")), ("Journal", d.get("journal")), ("DOI", d.get("doi")),
                ("Pages", d.get("page_count")), ("File", d["filename"]),
                ("Collections", ", ".join(x["name"] for x in d.get("collections", []))),
                ("Tags", ", ".join(d.get("tags", [])))]
        html = "".join(f"<div style='margin-bottom:4px'><span style='color:{pal.faint}'>{k}</span><br>{v}</div>"
                       for k, v in rows if v)
        if c.get("excerpt"):
            html += (f"<div style='margin-top:6px;color:{pal.muted}'>p. {c.get('page')} · {c.get('section') or ''}"
                     f"<br><i>“{str(c['excerpt'])[:350]}…”</i></div>")
        self.meta.setText(html)
        self.open_btn.show()
        try:
            self.open_btn.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        page = int(c.get("page") or 1)
        self.open_btn.setText(f" Open PDF at p. {page}")
        self.open_btn.clicked.connect(lambda: self.state.open_pdf.emit(d["id"], page))

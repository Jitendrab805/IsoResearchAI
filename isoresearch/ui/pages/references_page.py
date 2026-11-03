"""Reference manager: bibliographic records of the local library."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QMenu,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...export.exporters import citation_text, to_bibtex, to_ris, write_table, write_text
from ..state import AppState
from ..widgets.common import PageHeader, button, confirm, label

COLS = [("title", "Title"), ("authors", "Authors"), ("year", "Year"), ("journal", "Journal"), ("doi", "DOI")]


class ReferencesPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self._loading = False
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        root.addWidget(PageHeader("Reference Manager", "Bibliographic details come from PDF metadata, text patterns or "
                                  "your edits. Auto-detected values are highlighted until you confirm them. Double-click "
                                  "a cell to edit.", "Bibliography"))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter references…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        row.addWidget(button("Copy citation", "copy", color=pal.muted, slot=self.copy_citation))
        exp = button(" Export", "export", "Primary", color=pal.accent_text)
        m = QMenu(exp)
        m.addAction("BibTeX (.bib)", lambda: self.export("bib"))
        m.addAction("RIS (.ris)", lambda: self.export("ris"))
        m.addAction("CSV (.csv)", lambda: self.export("csv"))
        m.addAction("Excel (.xlsx)", lambda: self.export("xlsx"))
        exp.setMenu(m)
        row.addWidget(exp)
        root.addLayout(row)
        self.table = QTableWidget(0, len(COLS) + 1)
        self.table.setHorizontalHeaderLabels([c[1] for c in COLS] + ["Open"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._edited)
        root.addWidget(self.table, 1)
        root.addWidget(label("Only stored fields are exported — missing authors/years are left empty, never guessed.",
                             "Faint"))
        state.library_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        self.docs = self.ctx.repo.documents(self.search.text().strip())
        self.table.setRowCount(len(self.docs))
        pal = self.state.pal
        for r, d in enumerate(self.docs):
            guessed = (self.ctx.repo.document(d["id"]) or {}).get("metadata", {}).get("guessed", {})
            for c, (key, _) in enumerate(COLS):
                val = d.get(key)
                if key == "title" and not val:
                    val = d.get("display_label") or d["filename"]
                it = QTableWidgetItem("" if val is None else str(val))
                it.setData(Qt.ItemDataRole.UserRole, d["id"])
                g = guessed.get(key)
                if g and str(g.get("value")) == str(d.get(key)):
                    it.setForeground(Qt.GlobalColor.darkYellow if pal.name == "light" else Qt.GlobalColor.yellow)
                    it.setToolTip(f"Auto-detected ({g['method']}, {g['confidence']} confidence). Edit to confirm.")
                self.table.setItem(r, c, it)
            b = button("", "pdf", "Ghost", "Open PDF", pal.muted)
            b.clicked.connect(lambda _=False, i=d["id"]: self.state.open_pdf.emit(i, 1))
            self.table.setCellWidget(r, len(COLS), b)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._loading = False

    def _edited(self, it: QTableWidgetItem) -> None:
        if self._loading:
            return
        key = COLS[it.column()][0]
        doc_id = it.data(Qt.ItemDataRole.UserRole)
        val = it.text().strip()
        if key == "year":
            try:
                val = int(val) if val else None
            except ValueError:
                self.state.toast.emit("Year must be a number.", "warn")
                self.refresh()
                return
        self.ctx.repo.update_document(doc_id, **{key: val})
        doc = self.ctx.repo.document(doc_id)
        meta = doc.get("metadata", {})
        meta.get("guessed", {}).pop(key, None)  # user confirmed/edited -> no longer a guess
        self.ctx.repo.set_metadata(doc_id, meta)
        it.setForeground(Qt.GlobalColor.white if self.state.pal.name == "dark" else Qt.GlobalColor.black)
        it.setToolTip("Edited by you")

    def _selected_docs(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.docs[r] for r in rows] if rows else []

    def copy_citation(self) -> None:
        docs = self._selected_docs()
        if not docs:
            self.state.toast.emit("Select one or more references first.", "warn")
            return
        QGuiApplication.clipboard().setText("\n".join(citation_text(d) for d in docs))
        self.state.toast.emit(f"Copied {len(docs)} citation(s).", "ok")

    def export(self, fmt: str) -> None:
        docs = self._selected_docs() or self.docs
        path, _ = QFileDialog.getSaveFileName(self, "Export references",
                                              str(self.ctx.paths.exports_dir / f"references.{fmt}"), f"*.{fmt}")
        if not path:
            return
        p = Path(path)
        overwrite = p.exists() and confirm(self, "Overwrite?", f"{p.name} exists. Overwrite it?", "Overwrite", True)
        if p.exists() and not overwrite:
            return
        if fmt == "bib":
            write_text(p, to_bibtex(docs), overwrite)
        elif fmt == "ris":
            write_text(p, to_ris(docs), overwrite)
        else:
            write_table(p, ["Title", "Authors", "Year", "Journal", "DOI", "File"],
                        [[d.get("title") or d.get("display_label") or d["filename"], d.get("authors") or "",
                          d.get("year") or "", d.get("journal") or "", d.get("doi") or "", d["filename"]] for d in docs],
                        overwrite)
        self.state.toast.emit(f"Exported {len(docs)} reference(s) to {p.name}", "ok")

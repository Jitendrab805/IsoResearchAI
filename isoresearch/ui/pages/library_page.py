"""Research library: import, organise, search and open PDFs."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QScrollArea, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...retrieval.search import SearchFilters
from ..state import AppState
from ..widgets.chat_widgets import SourceCard
from ..widgets.common import Card, EmptyState, PageHeader, Pill, button, confirm, label
from ..workers import run_task

STATUS = {"indexed": ("Indexed", "ok"), "no_text": ("No text", "warn"), "failed": ("Failed", "error"),
          "processing": ("Processing", "accent"), "pending": ("Pending", "")}


class LibraryPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.task = None
        self.current_id: int | None = None
        self.setAcceptDrops(True)
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(PageHeader("Research Library", "Import your own PDFs. Text, pages and section headings are "
                                 "extracted and indexed locally. Drag & drop PDFs or folders anywhere on this page.",
                                 "Local documents"), 1)
        acts = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(button(" Import PDFs", "file-plus", "Primary", color=pal.accent_text, slot=self.import_files))
        row.addWidget(button(" Import folder", "folder", color=pal.muted, slot=self.import_folder))
        acts.addLayout(row)
        acts.addStretch(1)
        top.addLayout(acts)
        root.addLayout(top)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        # ---------------------------------------------------------------- documents tab
        docs = QWidget()
        dl = QVBoxLayout(docs)
        dl.setContentsMargins(12, 12, 12, 12)
        frow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by title, author, journal, DOI, year…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        frow.addWidget(self.search, 2)
        self.coll_combo = QComboBox()
        self.coll_combo.currentIndexChanged.connect(self.refresh)
        frow.addWidget(self.coll_combo, 1)
        self.tag_combo = QComboBox()
        self.tag_combo.currentIndexChanged.connect(self.refresh)
        frow.addWidget(self.tag_combo, 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("Any status", None)
        for k, (t, _) in STATUS.items():
            self.status_combo.addItem(t, k)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        frow.addWidget(self.status_combo, 1)
        frow.addWidget(button(" Collection", "plus", color=pal.muted, tip="Create a new collection",
                              slot=self.new_collection))
        dl.addLayout(frow)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Title / label", "Authors", "Year", "Status", "Pages", "Tags"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.doubleClicked.connect(lambda *_: self.open_current())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.empty = EmptyState("library", "Your library is empty",
                                "Import PDFs of papers you have the right to use. They are copied into your local "
                                "library folder; nothing is uploaded anywhere.", "Import PDFs")
        self.empty.action.clicked.connect(self.import_files)
        ll.addWidget(self.table)
        ll.addWidget(self.empty)
        split.addWidget(left)
        split.addWidget(self._build_detail())
        split.setSizes([640, 380])
        dl.addWidget(split, 1)
        self.tabs.addTab(docs, "Documents")
        # ---------------------------------------------------------------- passage search
        srch = QWidget()
        sl = QVBoxLayout(srch)
        sl.setContentsMargins(12, 12, 12, 12)
        r = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Search passages across papers, e.g. “amount effect convective depletion”")
        self.q.returnPressed.connect(self.search_passages)
        r.addWidget(self.q, 1)
        self.mode = QComboBox()
        self.mode.addItems(["Hybrid", "Keyword", "Semantic"])
        r.addWidget(self.mode)
        r.addWidget(button("Search", "search", "Primary", color=pal.accent_text, slot=self.search_passages))
        sl.addLayout(r)
        self.embed_note = label("", "Faint", wrap=True)
        sl.addWidget(self.embed_note)
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        self.results = QWidget()
        self.results_lay = QVBoxLayout(self.results)
        self.results_lay.addStretch(1)
        self.results_area.setWidget(self.results)
        sl.addWidget(self.results_area, 1)
        self.tabs.addTab(srch, "Search passages")
        # ---------------------------------------------------------------- import log
        logw = QWidget()
        lgl = QVBoxLayout(logw)
        lgl.setContentsMargins(12, 12, 12, 12)
        lgl.addWidget(label("Every import attempt is recorded here, including duplicates, scanned PDFs without OCR "
                            "and failures, with a diagnostic message.", "Muted", wrap=True))
        self.log_table = QTableWidget(0, 4)
        self.log_table.setHorizontalHeaderLabels(["When", "File", "Result", "Diagnostics"])
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setWordWrap(True)
        lgl.addWidget(self.log_table, 1)
        self.tabs.addTab(logw, "Import log")

        # ---------------------------------------------------------------- progress
        prow = QHBoxLayout()
        self.prog_label = label("", "Muted")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(360)
        self.cancel_btn = button("Cancel", kind="Ghost", slot=self.cancel)
        prow.addWidget(self.prog_label, 1)
        prow.addWidget(self.progress)
        prow.addWidget(self.cancel_btn)
        self.prog_row = QWidget()
        self.prog_row.setLayout(prow)
        self.prog_row.hide()
        root.addWidget(self.prog_row)
        state.library_changed.connect(self.refresh_all)
        self.refresh_all()

    # ------------------------------------------------------------------ detail panel
    def _build_detail(self) -> QWidget:
        pal = self.state.pal
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        card = Card()
        self.detail_title = label("Select a document", "H2", wrap=True)
        card.lay.addWidget(self.detail_title)
        self.detail_status = Pill("", "")
        card.lay.addWidget(self.detail_status)
        self.detail_diag = label("", "Muted", wrap=True, selectable=True)
        card.lay.addWidget(self.detail_diag)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.f = {}
        for key, lbl in (("display_label", "Display label"), ("title", "Title"), ("authors", "Authors (; separated)"),
                         ("year", "Year"), ("journal", "Journal"), ("doi", "DOI"), ("tags", "Tags (comma separated)")):
            e = QLineEdit()
            self.f[key] = e
            form.addRow(lbl, e)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Your private notes on this paper")
        self.notes.setFixedHeight(80)
        form.addRow("Notes", self.notes)
        card.lay.addLayout(form)
        self.detail_colls = label("", "Faint", wrap=True)
        card.lay.addWidget(self.detail_colls)
        b1 = QHBoxLayout()
        b1.addWidget(button("Save changes", "check", "Primary", color=pal.accent_text, slot=self.save_detail))
        b1.addWidget(button(" Open PDF", "pdf", color=pal.muted, slot=self.open_current))
        card.lay.addLayout(b1)
        b2 = QHBoxLayout()
        b2.addWidget(button("Add to collection…", "plus", "Ghost", color=pal.muted, slot=self.add_to_collection))
        b2.addWidget(button("Use in chat scope", "filter", "Ghost", color=pal.muted, slot=self.use_in_scope))
        card.lay.addLayout(b2)
        b3 = QHBoxLayout()
        b3.addWidget(button("Re-process", "refresh", "Ghost", "Extract text again (e.g. after enabling OCR)",
                            pal.muted, self.reprocess))
        b3.addStretch(1)
        b3.addWidget(button("Remove", "trash", "Danger", color=pal.danger, slot=self.remove_selected))
        card.lay.addLayout(b3)
        card.lay.addStretch(1)
        sc.setWidget(card)
        self.detail = sc
        self._set_detail_enabled(False)
        return sc

    def _set_detail_enabled(self, on: bool) -> None:
        self.detail.widget().setEnabled(on)

    # ------------------------------------------------------------------ data
    def refresh_all(self) -> None:
        cur_c = self.coll_combo.currentData()
        self.coll_combo.blockSignals(True)
        self.coll_combo.clear()
        self.coll_combo.addItem("All collections", None)
        for c in self.ctx.repo.collections():
            if c["name"] != "All papers":
                self.coll_combo.addItem(f"{c['name']} ({c['n']})", c["id"])
        i = self.coll_combo.findData(cur_c)
        self.coll_combo.setCurrentIndex(max(0, i))
        self.coll_combo.blockSignals(False)
        cur_t = self.tag_combo.currentData()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("Any tag", None)
        for t in self.ctx.repo.tags():
            self.tag_combo.addItem(f"#{t}", t)
        self.tag_combo.setCurrentIndex(max(0, self.tag_combo.findData(cur_t)))
        self.tag_combo.blockSignals(False)
        self.refresh()
        self.refresh_log()
        self.embed_note.setText(f"Retrieval: {self.ctx.search.embedder_status}. Hybrid combines BM25 keyword "
                                "ranking with vector similarity (reciprocal-rank fusion).")

    def refresh(self) -> None:
        docs = self.ctx.repo.documents(self.search.text().strip(), self.coll_combo.currentData(),
                                       self.tag_combo.currentData(), self.status_combo.currentData())
        self.docs = docs
        total = self.ctx.repo.counts().get("total", 0)
        self.table.setVisible(bool(total))
        self.empty.setVisible(not total)
        self.table.setRowCount(len(docs))
        for r, d in enumerate(docs):
            name = d.get("display_label") or d.get("title") or d["filename"]
            it = QTableWidgetItem(name)
            it.setData(Qt.ItemDataRole.UserRole, d["id"])
            it.setToolTip(f"{d['filename']}\n{d.get('status_detail') or ''}")
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem((d.get("authors") or "")[:60]))
            self.table.setItem(r, 2, QTableWidgetItem(str(d.get("year") or "")))
            st = STATUS.get(d["status"], (d["status"], ""))[0]
            if d.get("ocr_used"):
                st += " (OCR)"
            self.table.setItem(r, 3, QTableWidgetItem(st))
            self.table.setItem(r, 4, QTableWidgetItem(str(d.get("page_count") or "")))
            self.table.setItem(r, 5, QTableWidgetItem(", ".join(d.get("tags", []))))

    def refresh_log(self) -> None:
        rows = self.ctx.repo.import_log(300)
        self.log_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.log_table.setItem(i, 0, QTableWidgetItem(time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))))
            self.log_table.setItem(i, 1, QTableWidgetItem(Path(r["path"] or "").name))
            self.log_table.setItem(i, 2, QTableWidgetItem(r["status"]))
            self.log_table.setItem(i, 3, QTableWidgetItem(r["message"] or ""))
        self.log_table.resizeColumnsToContents()
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _selected(self) -> None:
        ids = self.selected_ids()
        if not ids:
            self.current_id = None
            self._set_detail_enabled(False)
            return
        self.current_id = ids[0]
        d = self.ctx.repo.document(ids[0])
        if not d:
            return
        self._set_detail_enabled(True)
        self.detail_title.setText(d.get("display_label") or d.get("title") or d["filename"])
        t, s = STATUS.get(d["status"], (d["status"], ""))
        self.detail_status.set_state(s, t + (" · OCR used" if d.get("ocr_used") else "") +
                                     (" · scanned" if d.get("is_scanned") else ""))
        self.detail_diag.setText(f"{d['filename']} · {d.get('page_count') or '?'} pages\n{d.get('status_detail') or ''}")
        for k, e in self.f.items():
            if k == "tags":
                e.setText(", ".join(d.get("tags", [])))
            else:
                e.setText("" if d.get(k) is None else str(d.get(k)))
        guessed = (d.get("metadata") or {}).get("guessed", {})
        for k in ("title", "authors", "year", "doi"):
            g = guessed.get(k)
            self.f[k].setToolTip(f"Auto-detected ({g['method']}, confidence {g['confidence']}) — please verify"
                                 if g else "")
        self.notes.setPlainText(d.get("notes") or "")
        self.detail_colls.setText("Collections: " + ", ".join(c["name"] for c in d.get("collections", [])))
        self.state.source_selected.emit({"doc_id": d["id"], "title": self.detail_title.text(),
                                         "authors": d.get("authors"), "year": d.get("year"), "page": 1,
                                         "section": "", "excerpt": ""})

    def save_detail(self) -> None:
        if not self.current_id:
            return
        vals = {k: e.text().strip() for k, e in self.f.items()}
        year = vals.pop("year")
        tags = vals.pop("tags")
        try:
            vals["year"] = int(year) if year else None
        except ValueError:
            self.state.toast.emit("Year must be a number such as 2021.", "warn")
            return
        vals["notes"] = self.notes.toPlainText()
        self.ctx.repo.update_document(self.current_id, **vals)
        self.ctx.repo.set_tags(self.current_id, [t for t in tags.split(",")])
        self.state.toast.emit("Document details saved.", "ok")
        cur = self.current_id
        self.state.library_changed.emit()
        self._reselect(cur)

    def _reselect(self, doc_id: int) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == doc_id:
                self.table.selectRow(r)
                break

    # ------------------------------------------------------------------ actions
    def _menu(self, pos) -> None:
        if not self.selected_ids():
            return
        m = QMenu(self)
        m.addAction("Open PDF", self.open_current)
        m.addAction("Add to collection…", self.add_to_collection)
        m.addAction("Use in chat scope", self.use_in_scope)
        m.addAction("Re-process", self.reprocess)
        m.addSeparator()
        m.addAction("Remove from library…", self.remove_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_current(self) -> None:
        if self.current_id:
            self.state.open_pdf.emit(self.current_id, 1)

    def new_collection(self) -> None:
        name, ok = QInputDialog.getText(self, "New collection", "Collection name:")
        if ok and name.strip():
            cid = self.ctx.repo.create_collection(name)
            ids = self.selected_ids()
            if ids and confirm(self, "Add papers", f"Add the {len(ids)} selected paper(s) to '{name}'?", "Add"):
                self.ctx.repo.add_to_collection(ids, cid)
            self.state.library_changed.emit()

    def add_to_collection(self) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        colls = [c for c in self.ctx.repo.collections() if c["name"] != "All papers"]
        names = [c["name"] for c in colls] + ["➕ New collection…"]
        name, ok = QInputDialog.getItem(self, "Add to collection", "Collection:", names, 0, False)
        if not ok:
            return
        if name.startswith("➕"):
            name, ok = QInputDialog.getText(self, "New collection", "Collection name:")
            if not ok or not name.strip():
                return
        cid = self.ctx.repo.create_collection(name)
        self.ctx.repo.add_to_collection(ids, cid)
        self.state.toast.emit(f"Added {len(ids)} paper(s) to '{name}'.", "ok")
        self.state.library_changed.emit()

    def use_in_scope(self) -> None:
        ids = self.selected_ids()
        if ids:
            self.state.scope_docs = set(ids)
            self.state.scope_changed.emit()
            self.state.toast.emit(f"Chat scope limited to {len(ids)} selected paper(s). Clear it in the context panel.",
                                  "info")

    def remove_selected(self) -> None:
        ids = self.selected_ids()
        if not ids or self.task:
            return
        if not confirm(self, "Remove papers", f"Remove {len(ids)} paper(s) from the library?\n\nThe copy in the "
                       "library folder, its passages, embeddings and literature record will be deleted. "
                       "Your original file elsewhere is not touched.", "Remove", danger=True):
            return
        for i in ids:
            self.ctx.importer.remove(i)
        self.state.toast.emit(f"Removed {len(ids)} paper(s).", "ok")
        self.state.scope_docs -= set(ids)
        self.state.library_changed.emit()

    def reprocess(self) -> None:
        ids = self.selected_ids()
        if not ids or self.task:
            return
        docs = [self.ctx.repo.document(i) for i in ids]

        def work(t):
            out = []
            for k, d in enumerate(docs):
                if t.cancelled():
                    break
                t.progress(k, len(docs), d["filename"])
                out.append(self.ctx.importer.process(d["id"], Path(d["stored_path"]), d["filename"]))
            return out
        self._start(work, "Re-processing")

    # ------------------------------------------------------------------ import
    def import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Import PDFs", str(Path.home()), "PDF files (*.pdf)")
        if files:
            self.import_paths([Path(f) for f in files])

    def import_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Import all PDFs in a folder (including subfolders)")
        if d:
            self.import_paths([Path(d)])

    def import_paths(self, paths: list[Path]) -> None:
        if self.task:
            self.state.toast.emit("An import is already running.", "warn")
            return
        cid = self.coll_combo.currentData()
        self._start(lambda t: self.ctx.importer.import_paths(paths, cid, progress=t.progress, cancel=t.cancelled),
                    "Importing")

    def _start(self, fn, verb: str) -> None:
        self.prog_row.show()
        self.progress.setRange(0, 0)
        self.prog_label.setText(f"{verb}…")
        self.task = run_task(fn, on_result=self._import_done, on_error=self._import_error,
                             on_progress=lambda d, n, m: self._prog(verb, d, n, m))

    def _prog(self, verb, done, total, msg) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.prog_label.setText(f"{verb} {min(done + 1, total)}/{total}: {msg}" if msg != "done" else "Finishing…")

    def cancel(self) -> None:
        if self.task:
            self.task.cancel()
            self.prog_label.setText("Cancelling after the current file…")

    def _import_done(self, results) -> None:
        self.task = None
        self.prog_row.hide()
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        if not results:
            self.state.toast.emit("No PDF files were found.", "warn")
        else:
            parts = [f"{v} {k.replace('_', ' ')}" for k, v in counts.items()]
            kind = "ok" if set(counts) <= {"indexed", "duplicate"} else "warn"
            self.state.toast.emit("Import finished: " + ", ".join(parts) +
                                  (". See the Import log for details." if kind == "warn" else "."), kind)
        self.state.library_changed.emit()

    def _import_error(self, exc) -> None:
        self.task = None
        self.prog_row.hide()
        self.state.toast.emit(f"Import failed: {exc}", "error")
        self.state.library_changed.emit()

    # ------------------------------------------------------------------ passage search
    def search_passages(self) -> None:
        q = self.q.text().strip()
        if not q:
            return
        mode = self.mode.currentText().lower()
        filt = SearchFilters(doc_ids=self.state.scope_doc_ids())
        run_task(lambda t: self.ctx.search.search(q, mode, 15, filt), on_result=self._show_results,
                 on_error=lambda e: self.state.toast.emit(f"Search failed: {e}", "error"))

    def _show_results(self, chunks) -> None:
        while self.results_lay.count() > 1:
            w = self.results_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not chunks:
            self.results_lay.insertWidget(0, label("No matching passages in the current scope.", "Muted"))
            return
        for i, c in enumerate(chunks, 1):
            cit = {"n": i, "doc_id": c.doc_id, "chunk_id": c.id, "title": c.title, "authors": c.authors,
                   "year": c.year, "page": c.page, "section": c.section, "excerpt": c.text}
            card = SourceCard(cit, self.state.pal)
            card.open_requested.connect(lambda cc: self.state.open_pdf.emit(int(cc["doc_id"]), int(cc["page"])))
            card.selected.connect(self.state.source_selected.emit)
            self.results_lay.insertWidget(self.results_lay.count() - 1, card)

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.import_paths(paths)

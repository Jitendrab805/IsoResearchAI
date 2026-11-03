"""Literature-review workspace."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QProgressBar, QScrollArea,
                               QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...export.exporters import markdown_to_docx, write_table, write_text
from ...research.literature import FIELDS, THEMES, LiteratureService
from ..state import AppState
from ..theme import markdown_css
from ..widgets.common import Banner, PageHeader, button, confirm, label
from ..widgets.markdown_view import MarkdownView
from ..workers import run_task

CONF_COLORS = {"high": "#4cc98d", "medium": "#2cc5b4", "low": "#f0b44c", "not_found": "#5d676d", "user": "#9db4ff"}


class LiteraturePage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.lit = LiteratureService(self.ctx.db, self.ctx.search, self.ctx.llm, self.ctx.settings)
        self.task = None
        self.current: int | None = None
        self._loading = False
        self.draft_md = ""
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(10)
        root.addWidget(PageHeader("Literature Review", "Structured, editable records for each paper with explicit "
                                  "confidence; comparison tables; theme-organised drafts with traceable citations.",
                                  "Synthesis"))
        split = QSplitter(Qt.Orientation.Horizontal)
        # ---------------------------------------------------------------- paper list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(label("Papers (tick to include)", "Muted"))
        self.papers = QListWidget()
        self.papers.currentItemChanged.connect(self._current_changed)
        ll.addWidget(self.papers, 1)
        r = QHBoxLayout()
        r.addWidget(button("All", kind="Chip", slot=lambda: self._check_all(True)))
        r.addWidget(button("None", kind="Chip", slot=lambda: self._check_all(False)))
        r.addStretch(1)
        ll.addLayout(r)
        split.addWidget(left)
        # ---------------------------------------------------------------- tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._record_tab(), "Paper record")
        self.tabs.addTab(self._table_tab(), "Comparison table")
        self.tabs.addTab(self._draft_tab(), "Review draft")
        split.addWidget(self.tabs)
        split.setSizes([280, 900])
        root.addWidget(split, 1)
        prow = QHBoxLayout()
        self.prog_label = label("", "Muted")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(320)
        prow.addWidget(self.prog_label, 1)
        prow.addWidget(self.progress)
        prow.addWidget(button("Stop", "stop", "Ghost", color=pal.muted, slot=self.cancel))
        self.prog_row = QWidget()
        self.prog_row.setLayout(prow)
        self.prog_row.hide()
        root.addWidget(self.prog_row)
        state.library_changed.connect(self.refresh_papers)
        self.refresh_papers()

    # ------------------------------------------------------------------ tabs
    def _record_tab(self) -> QWidget:
        pal = self.state.pal
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        b = QHBoxLayout()
        self.rec_title = label("Select a paper", "H2", wrap=True)
        b.addWidget(self.rec_title, 1)
        b.addWidget(button("Scan (no AI)", "search", color=pal.muted,
                           tip="Metadata, DOI pattern and keyword scan — runs without a model", slot=self.scan_checked))
        b.addWidget(button("Extract with local AI", "sparkle", "Primary", color=pal.accent_text,
                           tip="Uses the local model on retrieved passages of each ticked paper",
                           slot=self.extract_checked))
        lay.addLayout(b)
        lay.addWidget(label("Confidence: high/medium/low = how directly the passages state it; not_found = absent; "
                            "keyword scan = term is mentioned somewhere (not proof it was used). Double-click a value "
                            "to edit — your edits are never overwritten.", "Faint", wrap=True))
        self.rec = QTableWidget(0, 5)
        self.rec.setHorizontalHeaderLabels(["Field", "Value", "Confidence", "Method", "Pages"])
        self.rec.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rec.verticalHeader().setVisible(False)
        self.rec.setWordWrap(True)
        self.rec.itemChanged.connect(self._rec_edited)
        lay.addWidget(self.rec, 1)
        return w

    def _table_tab(self) -> QWidget:
        pal = self.state.pal
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        f = QHBoxLayout()
        self.flt = {}
        for key, ph in (("isotope_vars", "Isotope variable (e.g. d-excess)"), ("model", "Model (e.g. IsoRSM)"),
                        ("region", "Region"), ("obs_type", "Observation type (e.g. vapour)")):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.setClearButtonEnabled(True)
            self.flt[key] = e
            f.addWidget(e)
        self.ymin, self.ymax = QSpinBox(), QSpinBox()
        for s, v in ((self.ymin, 1950), (self.ymax, 2035)):
            s.setRange(1900, 2100)
            s.setValue(v)
            s.setPrefix("≥ " if s is self.ymin else "≤ ")
        f.addWidget(self.ymin)
        f.addWidget(self.ymax)
        lay.addLayout(f)
        b = QHBoxLayout()
        self.cols_btn = button("Columns", "panel", color=pal.muted)
        self.col_menu = QMenu(self.cols_btn)
        self.col_actions = {}
        default = {"title", "authors", "year", "region", "model", "isotope_vars", "observations", "validation", "findings"}
        for key, lbl, _ in FIELDS:
            a = self.col_menu.addAction(lbl)
            a.setCheckable(True)
            a.setChecked(key in default)
            self.col_actions[key] = a
        self.cols_btn.setMenu(self.col_menu)
        b.addWidget(self.cols_btn)
        b.addWidget(button("Build table", "refresh", "Primary", color=pal.accent_text, slot=self.build_table))
        b.addStretch(1)
        b.addWidget(button("Export CSV", "export", color=pal.muted, slot=lambda: self.export_table("csv")))
        b.addWidget(button("Export Excel", "export", color=pal.muted, slot=lambda: self.export_table("xlsx")))
        lay.addLayout(b)
        self.cmp = QTableWidget(0, 0)
        self.cmp.setWordWrap(True)
        self.cmp.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cmp.verticalHeader().setVisible(False)
        self.cmp.setAlternatingRowColors(True)
        lay.addWidget(self.cmp, 1)
        self.cmp_note = label("Tick papers on the left, then Build table. Run Scan or AI extraction first to fill "
                              "the records.", "Faint", wrap=True)
        lay.addWidget(self.cmp_note)
        self.table_data = ([], [])
        return w

    def _draft_tab(self) -> QWidget:
        pal = self.state.pal
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(label("Themes (each becomes a section synthesising across the ticked papers):", "Muted"))
        tl = QHBoxLayout()
        tl.setSpacing(6)
        self.theme_checks = []
        col = QVBoxLayout()
        for i, (t, q) in enumerate(THEMES):
            cb = QCheckBox(t)
            cb.setChecked(True)
            cb.query = q
            self.theme_checks.append(cb)
            col.addWidget(cb)
        tl.addLayout(col)
        custom = QVBoxLayout()
        self.custom_theme = QLineEdit()
        self.custom_theme.setPlaceholderText("Optional extra theme, e.g. “Moisture sources of Andaman rainfall”")
        custom.addWidget(self.custom_theme)
        custom.addStretch(1)
        tl.addLayout(custom, 1)
        lay.addLayout(tl)
        b = QHBoxLayout()
        b.addWidget(button("Generate draft with local AI", "sparkle", "Primary", color=pal.accent_text,
                           slot=self.generate_draft))
        b.addStretch(1)
        b.addWidget(button("Copy Markdown", "copy", color=pal.muted, slot=self._copy_draft))
        b.addWidget(button("Export Markdown", "export", color=pal.muted, slot=lambda: self.export_draft("md")))
        b.addWidget(button("Export DOCX", "export", color=pal.muted, slot=lambda: self.export_draft("docx")))
        lay.addLayout(b)
        self.draft_banner = Banner("Drafts are produced only from passages of the ticked papers. Sentences without a "
                                   "citation are marked ⚠ [unsupported — verify]. Always check every citation "
                                   "against the PDF before using the text.")
        lay.addWidget(self.draft_banner)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        self.draft_view = MarkdownView()
        self.draft_view.linkActivated.connect(lambda u: None)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.addWidget(self.draft_view)
        hl.addStretch(1)
        sc.setWidget(holder)
        lay.addWidget(sc, 1)
        return w

    # ------------------------------------------------------------------ papers
    def refresh_papers(self) -> None:
        checked = set(self.checked_ids())
        self.papers.blockSignals(True)
        self.papers.clear()
        for d in self.ctx.repo.documents():
            if d["status"] not in ("indexed",):
                continue
            name = d.get("display_label") or d.get("title") or d["filename"]
            it = QListWidgetItem(f"{name}" + (f" ({d['year']})" if d.get("year") else ""))
            it.setData(Qt.ItemDataRole.UserRole, d["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if d["id"] in checked else Qt.CheckState.Unchecked)
            self.papers.addItem(it)
        self.papers.blockSignals(False)

    def checked_ids(self) -> list[int]:
        return [self.papers.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.papers.count())
                if self.papers.item(i).checkState() == Qt.CheckState.Checked]

    def _check_all(self, on: bool) -> None:
        for i in range(self.papers.count()):
            self.papers.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _current_changed(self, it, _prev=None) -> None:
        if it is None:
            return
        self.current = it.data(Qt.ItemDataRole.UserRole)
        self.show_record(self.current)

    def show_record(self, doc_id: int) -> None:
        self._loading = True
        rec = self.lit.get(doc_id)
        doc = self.ctx.repo.document(doc_id) or {}
        self.rec_title.setText(doc.get("display_label") or doc.get("title") or doc.get("filename", ""))
        self.rec.setRowCount(len(FIELDS))
        for r, (key, lbl, _) in enumerate(FIELDS):
            f = rec.fields.get(key, {})
            k = QTableWidgetItem(lbl)
            k.setFlags(Qt.ItemFlag.ItemIsEnabled)
            v = QTableWidgetItem(str(f.get("value", "")))
            v.setData(Qt.ItemDataRole.UserRole, key)
            conf = f.get("confidence", "not_found")
            c = QTableWidgetItem(conf)
            c.setForeground(QColor(CONF_COLORS.get(conf, "#8d989e")))
            c.setFlags(Qt.ItemFlag.ItemIsEnabled)
            m = QTableWidgetItem(f.get("method", ""))
            m.setFlags(Qt.ItemFlag.ItemIsEnabled)
            p = QTableWidgetItem(", ".join(map(str, f.get("pages", []))))
            p.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for col, item in enumerate((k, v, c, m, p)):
                self.rec.setItem(r, col, item)
        self.rec.resizeRowsToContents()
        self._loading = False

    def _rec_edited(self, it: QTableWidgetItem) -> None:
        if self._loading or it.column() != 1 or self.current is None:
            return
        self.lit.edit_field(self.current, it.data(Qt.ItemDataRole.UserRole), it.text().strip())
        self.show_record(self.current)
        self.state.library_changed.emit()

    # ------------------------------------------------------------------ actions
    def _targets(self) -> list[int]:
        ids = self.checked_ids()
        if not ids and self.current:
            ids = [self.current]
        if not ids:
            self.state.toast.emit("Tick one or more papers (or select one) first.", "warn")
        return ids

    def scan_checked(self) -> None:
        ids = self._targets()
        if ids:
            self._run(lambda t: [self.lit.scan(i) for i in ids], "Scanning", len(ids))

    def extract_checked(self) -> None:
        ids = self._targets()
        if not ids:
            return
        if not self.state.model_status.get("ready"):
            self.state.toast.emit("The local AI model is not ready. Use 'Scan (no AI)' or set up a model in Settings.",
                                  "warn")
            return

        def work(t):
            errors = []
            for k, i in enumerate(ids):
                if t.cancelled():
                    break
                t.progress(k, len(ids), f"paper {k + 1}")
                try:
                    self.lit.extract_with_llm(i, cancel=t.cancel_event)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"doc {i}: {exc}")
            return errors
        self._run(work, "Extracting with local AI", len(ids))

    def _run(self, fn, verb: str, n: int) -> None:
        if self.task:
            return
        self.prog_row.show()
        self.progress.setRange(0, 0)
        self.prog_label.setText(verb + "…")
        self.task = run_task(fn, on_result=self._done, on_error=self._err,
                             on_progress=lambda d, tot, m: (self.progress.setRange(0, tot), self.progress.setValue(d),
                                                            self.prog_label.setText(f"{verb}: {m}")))

    def _done(self, out) -> None:
        self.task = None
        self.prog_row.hide()
        if isinstance(out, list) and out and isinstance(out[0], str):
            self.state.toast.emit(f"Finished with {len(out)} problem(s): {out[0][:140]}", "warn")
        else:
            self.state.toast.emit("Literature records updated.", "ok")
        if self.current:
            self.show_record(self.current)
        self.state.library_changed.emit()

    def _err(self, exc) -> None:
        self.task = None
        self.prog_row.hide()
        self.state.toast.emit(f"{type(exc).__name__}: {exc}", "error")

    def cancel(self) -> None:
        if self.task:
            self.task.cancel()

    # ------------------------------------------------------------------ table
    def build_table(self) -> None:
        ids = self.checked_ids()
        if not ids:
            self.state.toast.emit("Tick the papers to compare.", "warn")
            return
        cols = [k for k, a in self.col_actions.items() if a.isChecked()]
        filters = {k: e.text().strip() for k, e in self.flt.items()}
        filters["year_min"] = self.ymin.value() if self.ymin.value() > 1950 else None
        filters["year_max"] = self.ymax.value() if self.ymax.value() < 2035 else None
        headers, rows, _ = self.lit.table(ids, cols, filters)
        self.table_data = (headers, rows)
        self.cmp.setColumnCount(len(headers))
        self.cmp.setHorizontalHeaderLabels(headers)
        self.cmp.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(v)
                it.setToolTip(v)
                self.cmp.setItem(r, c, it)
        self.cmp.resizeColumnsToContents()
        for c in range(len(headers)):
            self.cmp.setColumnWidth(c, min(self.cmp.columnWidth(c), 320))
        self.cmp.resizeRowsToContents()
        self.cmp_note.setText(f"{len(rows)} of {len(ids)} ticked paper(s) match the filters. Values marked by "
                              "'keyword scan' are mentions only — check the Paper record tab.")

    def export_table(self, fmt: str) -> None:
        headers, rows = self.table_data
        if not headers:
            self.state.toast.emit("Build the table first.", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export comparison table",
                                              str(self.ctx.paths.exports_dir / f"literature_comparison.{fmt}"),
                                              f"*.{fmt}")
        if not path:
            return
        p = Path(path)
        if p.exists() and not confirm(self, "Overwrite?", f"{p.name} exists. Overwrite?", "Overwrite", True):
            return
        write_table(p, headers, rows, overwrite=True)
        self.state.toast.emit(f"Table exported: {p.name}", "ok")

    # ------------------------------------------------------------------ draft
    def generate_draft(self) -> None:
        ids = self.checked_ids()
        if not ids:
            self.state.toast.emit("Tick the papers to include in the review.", "warn")
            return
        if not self.state.model_status.get("ready"):
            self.state.toast.emit("Drafting needs the local AI model. Set it up in Settings → AI model.", "warn")
            return
        themes = [(cb.text(), cb.query) for cb in self.theme_checks if cb.isChecked()]
        if self.custom_theme.text().strip():
            themes.append((self.custom_theme.text().strip(), self.custom_theme.text().strip()))
        if not themes:
            return
        self.tabs.setCurrentIndex(2)
        self._run(lambda t: self.lit.draft_review(ids, themes, t.progress, t.cancel_event), "Drafting", len(themes))
        self.task.signals.result.disconnect()
        self.task.signals.result.connect(self._draft_done)

    def _draft_done(self, md: str) -> None:
        self.task = None
        self.prog_row.hide()
        self.draft_md = md
        self.draft_view.set_markdown(md, self.state.pal.text, markdown_css(self.state.pal))
        self.state.toast.emit("Draft ready. Check every citation before use.", "ok")

    def _copy_draft(self) -> None:
        if self.draft_md:
            QGuiApplication.clipboard().setText(self.draft_md)
            self.state.toast.emit("Draft copied as Markdown.", "ok")

    def export_draft(self, fmt: str) -> None:
        if not self.draft_md:
            self.state.toast.emit("Generate a draft first.", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export review draft",
                                              str(self.ctx.paths.exports_dir / f"literature_review_draft.{fmt}"),
                                              f"*.{fmt}")
        if not path:
            return
        p = Path(path)
        if p.exists() and not confirm(self, "Overwrite?", f"{p.name} exists. Overwrite?", "Overwrite", True):
            return
        if fmt == "docx":
            markdown_to_docx(self.draft_md, p, overwrite=True)
        else:
            write_text(p, self.draft_md, overwrite=True)
        self.state.toast.emit(f"Draft exported: {p.name}", "ok")


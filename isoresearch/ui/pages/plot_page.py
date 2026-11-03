"""Scientific Plot Advisor: plan, check, preview and export publication figures."""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ...plotting.catalog import BY_ID, CATALOG, PlotSpec, check_support, default_options
from ...plotting.render import build_script, export_figure, render
from ...retrieval.search import SearchFilters
from ..state import AppState
from ..widgets.common import Card, PageHeader, Pill, button, label
from ..workers import run_task


class PlotPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.spec: PlotSpec | None = None
        self.opts: dict = {}
        self.result: dict | None = None
        self.current_fig = None
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(10)
        root.addWidget(PageHeader("Plot Advisor", "Plan publication-quality isotope figures: the scientific question, "
                                  "what the plot can and cannot show, whether your data support it — then preview it "
                                  "from your own data and export the figure with its script.", "Figures"))
        split = QSplitter(Qt.Orientation.Horizontal)
        self.catalog = QListWidget()
        fam = None
        for p in CATALOG:
            if p.family != fam:
                fam = p.family
                h = QListWidgetItem(fam.upper())
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                f = QFont()
                f.setBold(True)
                f.setPointSizeF(8)
                h.setFont(f)
                self.catalog.addItem(h)
            it = QListWidgetItem(p.title)
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            self.catalog.addItem(it)
        self.catalog.currentItemChanged.connect(self._pick)
        self.catalog.setMinimumWidth(230)
        split.addWidget(self.catalog)
        # ---------------------------------------------------------------- explanation
        self.explain_scroll = QScrollArea()
        self.explain_scroll.setWidgetResizable(True)
        self.explain_scroll.setMinimumWidth(340)
        self.explain_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ex = QWidget()
        self.ex_lay = QVBoxLayout(ex)
        self.ex_lay.setSpacing(10)
        self.title = label("Choose a plot", "H2", wrap=True)
        self.ex_lay.addWidget(self.title)
        self.explain = label("", wrap=True, selectable=True)
        self.explain.setTextFormat(Qt.TextFormat.RichText)
        self.ex_lay.addWidget(self.explain)
        self.opt_card = Card(flat=True)
        self.opt_form = QFormLayout()
        self.opt_card.lay.addWidget(label("Options", "Muted"))
        self.opt_card.lay.addLayout(self.opt_form)
        self.ex_lay.addWidget(self.opt_card)
        self.support_card = Card(flat=True)
        self.support_card.lay.addWidget(label("Can your current data support this plot?", "Muted"))
        self.support_pill = Pill("", "")
        self.support_card.lay.addWidget(self.support_pill)
        self.support_text = label("", wrap=True)
        self.support_card.lay.addWidget(self.support_text)
        self.support_card.lay.addWidget(button("Open Data Analysis to load/map data", kind="Link",
                                               slot=lambda: self.state.navigate.emit("data")))
        self.ex_lay.addWidget(self.support_card)
        self.papers_card = Card(flat=True)
        self.papers_card.lay.addWidget(label("Relevant papers in your library", "Muted"))
        self.papers_box = QVBoxLayout()
        self.papers_card.lay.addLayout(self.papers_box)
        self.ex_lay.addWidget(self.papers_card)
        self.ex_lay.addStretch(1)
        self.explain_scroll.setWidget(ex)
        split.addWidget(self.explain_scroll)
        # ---------------------------------------------------------------- preview
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.render_btn = button("Preview from my data", "plot", "Primary", color=pal.accent_text,
                                 slot=self.preview)
        bar.addWidget(self.render_btn)
        bar.addWidget(button("Show script", "copy", color=pal.muted, slot=self.show_script))
        bar.addStretch(1)
        rl.addLayout(bar)
        bar = QHBoxLayout()
        bar.addWidget(label("Export:", "Muted"))
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        bar.addWidget(self.dpi)
        self.fmt_checks = {}
        for f in ("png", "svg", "pdf"):
            cb = QCheckBox(f.upper())
            cb.setChecked(True)
            self.fmt_checks[f] = cb
            bar.addWidget(cb)
        bar.addWidget(button("Export figure + script", "export", color=pal.muted, slot=self.export))
        bar.addStretch(1)
        export_bar = bar
        self.fig = Figure(figsize=(7, 4.6), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.preview_layout = rl
        self.canvas.setMinimumSize(320, 260)
        rl.addWidget(self.canvas, 1)
        self.stats = label("Statistics will appear here after the preview.", "Muted", wrap=True, selectable=True)
        rl.addWidget(self.stats)
        rl.addLayout(export_bar)
        rl.addWidget(button("Ask the assistant about this plot", "chat-plus", "Ghost", color=pal.muted,
                            slot=self.ask))
        split.addWidget(right)
        split.setSizes([250, 420, 720])
        split.setStretchFactor(2, 1)
        root.addWidget(split, 1)
        state.dataset_changed.connect(self._update_support)
        self.catalog.setCurrentRow(1)

    # ------------------------------------------------------------------ selection
    def _pick(self, it, _prev=None) -> None:
        if not it or not it.data(Qt.ItemDataRole.UserRole):
            return
        self.spec = BY_ID[it.data(Qt.ItemDataRole.UserRole)]
        self.opts = default_options(self.spec)
        s = self.spec
        pal = self.state.pal
        self.title.setText(s.title)
        from ...analysis.dataset import ROLES

        req = [r for r in s.required_for(self.opts)] + [e for e in s.extras_required]
        req_txt = ", ".join(f"{ROLES.get(r, (r, '', None))[0]} [{ROLES.get(r, ('', '', None))[1] or '–'}]"
                            for r in req if "{" not in r) or "see options"
        rows = [("Scientific question", s.question), ("Why this plot", s.why), ("Required variables (units)", req_txt),
                ("Expected interpretation", s.interpretation), ("Alternative explanations", s.alternatives),
                ("Confounding factors", s.confounders), ("Statistics & uncertainty", s.statistics)]
        if s.data_quality:
            rows.append(("Data quality", s.data_quality))
        self.explain.setText("".join(f"<p><span style='color:{pal.accent};font-weight:600'>{k}</span><br>{v}</p>"
                                     for k, v in rows if v))
        while self.opt_form.rowCount():
            self.opt_form.removeRow(0)
        for name, choices in s.options.items():
            cb = QComboBox()
            cb.addItems([str(c) for c in choices])
            cb.currentTextChanged.connect(lambda v, n=name: self._opt(n, v))
            self.opt_form.addRow(name, cb)
        self.opt_card.setVisible(bool(s.options))
        self._update_support()
        self._find_papers()

    def _opt(self, name: str, value: str) -> None:
        self.opts[name] = int(value) if value.isdigit() else value
        self._update_support()

    def _update_support(self) -> None:
        if not self.spec:
            return
        df = self.state.mapped_frame()
        if df is None:
            self.support_pill.set_state("warn", "No dataset loaded")
            self.support_text.setText("Load and map a dataset in Data Analysis. The advisor never invents values: "
                                      "plots are drawn only from your file.")
            self.render_btn.setEnabled(False)
            return
        avail = {c: int(df[c].notna().sum()) for c in df.columns}
        ok, msgs = check_support(self.spec, self.opts, avail, set(self.state.extras()))
        self.support_pill.set_state("ok" if ok else "error", "Supported by your data" if ok else "Not supported yet")
        synth = " ⚠ The loaded file is marked SYNTHETIC." if self.state.dataset.synthetic else ""
        self.support_text.setText("<br>".join(msgs) + (f"<br><b>{synth}</b>" if synth else ""))
        self.render_btn.setEnabled(ok)

    def _find_papers(self) -> None:
        while self.papers_box.count():
            w = self.papers_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        q = self.spec.keywords + " " + self.spec.title
        run_task(lambda t: self.ctx.search.hybrid(q, k=5, filters=SearchFilters(doc_ids=self.state.scope_doc_ids())),
                 on_result=self._show_papers, on_error=lambda e: None)

    def _show_papers(self, chunks) -> None:
        if not chunks:
            self.papers_box.addWidget(label("No matching passages in your library.", "Faint"))
            return
        seen = set()
        for c in chunks:
            if c.doc_id in seen:
                continue
            seen.add(c.doc_id)
            b = button(f"{c.label()}", kind="Link", tip=c.text[:300])
            b.clicked.connect(lambda _=False, d=c.doc_id, p=c.page: self.state.open_pdf.emit(d, p))
            self.papers_box.addWidget(b)

    # ------------------------------------------------------------------ render / export
    def preview(self) -> None:
        df = self.state.mapped_frame()
        if df is None or not self.spec:
            return
        spec, opts, extras = self.spec, dict(self.opts), self.state.extras()
        self.stats.setText("Rendering…")
        run_task(lambda t: render(spec, df, opts, extras), on_result=self._rendered,
                 on_error=lambda e: self.stats.setText(f"Could not draw the plot: {type(e).__name__}: {e}"))

    def _rendered(self, out) -> None:
        fig, result = out
        self.current_fig, self.result = fig, result
        idx = self.preview_layout.indexOf(self.canvas)
        new = FigureCanvasQTAgg(fig)
        new.setMinimumSize(320, 260)
        self.preview_layout.insertWidget(idx, new, 1)
        self.canvas.setParent(None)
        self.canvas.deleteLater()
        self.canvas = new
        self.canvas.draw_idle()
        synth = "\n⚠ SYNTHETIC data — not for publication." if self.state.dataset.synthetic else ""
        self.stats.setText("\n".join(result.get("stats", []) + [""] + result.get("notes", [])) + synth)

    def _script(self) -> str:
        ds = self.state.dataset
        return build_script(self.spec, self.opts, self.state.mapping, str(ds.path) if ds else "your_data.csv",
                            extras_mapping=self.state.extras_mapping)

    def show_script(self) -> None:
        if not self.spec:
            return
        d = QDialog(self)
        d.setWindowTitle("Plotting script (not executed automatically)")
        d.resize(860, 700)
        lay = QVBoxLayout(d)
        lay.addWidget(label("This script reads your original data file and reproduces the figure. Review it before "
                            "running it yourself.", "Muted", wrap=True))
        ed = QPlainTextEdit(self._script())
        ed.setReadOnly(True)
        ed.setFont(QFont("Consolas", 9))
        lay.addWidget(ed, 1)
        lay.addWidget(button("Copy script", "copy", "Primary", color=self.state.pal.accent_text,
                             slot=lambda: QGuiApplication.clipboard().setText(ed.toPlainText())))
        d.exec()

    def export(self) -> None:
        if self.current_fig is None or not self.spec:
            self.state.toast.emit("Preview the plot first.", "warn")
            return
        fmts = tuple(f for f, cb in self.fmt_checks.items() if cb.isChecked())
        if not fmts:
            return
        ds = self.state.dataset
        out = export_figure(self.current_fig, self.result, self.spec, self.opts, self.state.mapping, str(ds.path),
                            self.ctx.paths.figures_dir, fmts, self.dpi.value(),
                            extras_mapping=self.state.extras_mapping, synthetic=ds.synthetic)
        import json
        import time

        self.ctx.db.execute("INSERT INTO figures(title, plot_type, folder, config_json, created_at) VALUES (?,?,?,?,?)",
                            (self.spec.title, self.spec.id, out["folder"], json.dumps({"options": self.opts}),
                             time.time()))
        self.state.toast.emit(f"Exported {len(out['files'])} file(s) + script + config.", "ok")
        QDesktopServices.openUrl(QUrl.fromLocalFile(out["folder"]))

    def ask(self) -> None:
        if not self.spec:
            return
        prof = self.ctx.settings.profile
        self.state.ask_in_chat.emit(
            f"I am planning the plot '{self.spec.title}' to answer: {self.spec.question} My study: "
            f"{prof.get('primary_location', '')} {prof.get('primary_observations', '')}. Using my library, which "
            f"interpretations, confounders and statistics should I consider, and how did published studies present it?")
        self.state.navigate.emit("chat")


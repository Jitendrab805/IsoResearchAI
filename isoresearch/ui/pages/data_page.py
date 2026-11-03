"""Local dataset analysis workspace (CSV / Excel / NetCDF) — originals are never modified."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QPlainTextEdit,
                               QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...analysis import dataset as D
from ...core.paths import resource_path
from ...export.exporters import write_text
from ...plotting import recipes
from ..state import AppState
from ..widgets.common import Banner, EmptyState, PageHeader, Pill, button, confirm, label
from ..workers import run_task

ARRAY_ROLES = ["avg_kernel", "apriori", "model_profile", "pressure", "retrieval"]
SEV_COLORS = {"warning": "#f0b44c", "info": "#8d989e", "ok": "#4cc98d"}


def example_dir() -> Path:
    here = Path(__file__).resolve().parents[3] / "examples"
    return here if here.exists() else resource_path("..", "examples")


class DataPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(PageHeader("Data Analysis", "Inspect CSV, Excel and NetCDF files locally. Files are opened "
                                 "read-only; mappings, derived variables and plots work on an in-memory copy, and every "
                                 "step is logged for reproducibility.", "Local datasets"), 1)
        col = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(button(" Open dataset", "folder", "Primary", color=pal.accent_text, slot=self.open_file))
        row.addWidget(button("Load synthetic example", "data", color=pal.muted, slot=self.load_example))
        col.addLayout(row)
        col.addStretch(1)
        top.addLayout(col)
        root.addLayout(top)
        self.file_row = QHBoxLayout()
        self.file_pill = Pill("No dataset loaded", "")
        self.file_row.addWidget(self.file_pill)
        self.file_row.addStretch(1)
        root.addLayout(self.file_row)
        self.synth_banner = Banner("This file is marked SYNTHETIC. Its values are artificial and must not be used as "
                                   "observations.")
        self.synth_banner.hide()
        root.addWidget(self.synth_banner)
        self.empty = EmptyState("data", "No dataset open", "Open your rainfall isotope, meteorological or model output "
                                "file, or load the synthetic example to explore the workflow.")
        root.addWidget(self.empty, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._preview_tab(), "Preview")
        self.tabs.addTab(self._vars_tab(), "Variables && coverage")
        self.tabs.addTab(self._mapping_tab(), "Variable mapping")
        self.tabs.addTab(self._qc_tab(), "Quality control && statistics")
        self.tabs.addTab(self._plot_tab(), "Quick plots")
        self.tabs.addTab(self._log_tab(), "Transformation log")
        self.tabs.hide()
        root.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------ tabs
    def _preview_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        l.addWidget(self.preview)
        self.preview_note = label("", "Faint")
        l.addWidget(self.preview_note)
        return w

    def _vars_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        self.vars_table = QTableWidget(0, 9)
        self.vars_table.setHorizontalHeaderLabels(["Column", "Type", "Units", "Missing", "Missing %", "Min", "Max",
                                                   "Mean", "Std"])
        self.vars_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vars_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        l.addWidget(self.vars_table, 1)
        self.coverage = label("", "Muted", wrap=True, selectable=True)
        l.addWidget(self.coverage)
        return w

    def _mapping_tab(self):
        pal = self.state.pal
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addWidget(label("Suggested automatically from column names, units and value ranges — please confirm. "
                              "Mappings only rename columns in memory.", "Muted", wrap=True))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        h = QHBoxLayout(inner)
        self.map_form = QFormLayout()
        self.map_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.combos: dict[str, QComboBox] = {}
        for role, (lbl, unit, _) in D.ROLES.items():
            if role in ARRAY_ROLES and role not in ("pressure",):
                continue
            cb = QComboBox()
            self.combos[role] = cb
            self.map_form.addRow(f"{lbl}" + (f" [{unit}]" if unit else ""), cb)
        h.addLayout(self.map_form, 1)
        arr = QFormLayout()
        arr.addRow(label("Arrays for averaging-kernel comparisons (NetCDF)", "Muted"))
        self.array_combos: dict[str, QComboBox] = {}
        for role in ARRAY_ROLES:
            cb = QComboBox()
            self.array_combos[role] = cb
            arr.addRow(role, cb)
        h.addLayout(arr, 1)
        sc.setWidget(inner)
        outer.addWidget(sc, 1)
        r = QHBoxLayout()
        r.addWidget(button("Apply mapping", "check", "Primary", color=pal.accent_text, slot=self.apply_mapping))
        r.addWidget(button("Derive d-excess = δ²H − 8·δ¹⁸O", "plus", color=pal.muted, slot=self.derive_dexcess))
        r.addStretch(1)
        r.addWidget(button("Save mapped copy as CSV…", "export", color=pal.muted, slot=self.save_copy))
        outer.addLayout(r)
        return w

    def _qc_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(label("Automatic checks flag issues only; nothing is removed or corrected.", "Muted"))
        self.qc_table = QTableWidget(0, 3)
        self.qc_table.setHorizontalHeaderLabels(["Severity", "Variable", "Issue"])
        self.qc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.qc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        l.addWidget(self.qc_table, 1)
        self.stats_text = QPlainTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(220)
        l.addWidget(self.stats_text)
        return w

    def _plot_tab(self):
        pal = self.state.pal
        w = QWidget()
        l = QVBoxLayout(w)
        r = QHBoxLayout()
        self.qp_kind = QComboBox()
        self.qp_kind.addItems(["Time series", "Scatter (x vs y)", "Correlation matrix", "Model evaluation (obs vs sim)"])
        r.addWidget(self.qp_kind)
        self.qp_x, self.qp_y = QComboBox(), QComboBox()
        r.addWidget(label("x"))
        r.addWidget(self.qp_x)
        r.addWidget(label("y"))
        r.addWidget(self.qp_y)
        r.addWidget(button("Plot", "plot", "Primary", color=pal.accent_text, slot=self.quick_plot))
        r.addStretch(1)
        r.addWidget(button("More plots in Plot Advisor →", kind="Link",
                           slot=lambda: self.state.navigate.emit("plots")))
        l.addLayout(r)
        self.fig = Figure(figsize=(7, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        l.addWidget(self.canvas, 1)
        self.qp_stats = label("", "Muted", wrap=True, selectable=True)
        l.addWidget(self.qp_stats)
        return w

    def _log_tab(self):
        pal = self.state.pal
        w = QWidget()
        l = QVBoxLayout(w)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        l.addWidget(self.log_view, 1)
        l.addWidget(button("Export log…", "export", color=pal.muted, slot=self.export_log))
        return w

    # ------------------------------------------------------------------ loading
    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open dataset", str(Path.home()),
                                              "Data files (*.csv *.tsv *.txt *.xlsx *.xlsm *.nc *.nc4);;All files (*)")
        if path:
            self.load(Path(path))

    def load_example(self) -> None:
        p = example_dir() / "synthetic_rainfall_isotopes.csv"
        if not p.exists():
            self.state.toast.emit("Example file not found. Run examples/make_synthetic_data.py.", "warn")
            return
        self.load(p)

    def load(self, path: Path) -> None:
        self.file_pill.set_state("accent", f"Loading {path.name}…")
        run_task(lambda t: D.load(path), on_result=self._loaded,
                 on_error=lambda e: (self.file_pill.set_state("error", f"Could not open {path.name}"),
                                     self.state.toast.emit(f"Could not open file: {e}", "error")))

    def _loaded(self, ds) -> None:
        st = self.state
        st.dataset = ds
        st.mapping = D.detect_roles(ds)
        st.extras_mapping = {r: c for r, c in st.mapping.items() if r in ARRAY_ROLES}
        if "pressure" in st.mapping and st.mapping["pressure"] not in ds.df.columns:
            st.extras_mapping["pressure"] = st.mapping["pressure"]
        if "retrieval" in ds.extras:
            st.extras_mapping.setdefault("retrieval", "retrieval")
        st.derived = {}
        st.transform_log = D.TransformLog(ds.path, ds.sha256)
        st.transform_log.add("auto-detect mapping (suggestion)", mapping=st.mapping)
        self.empty.hide()
        self.tabs.show()
        self.file_pill.set_state("ok", f"{ds.path.name} · {ds.kind.upper()} · {len(ds.df)} rows · "
                                 f"{len(ds.df.columns)} columns" + (f" · dims {ds.dims}" if ds.dims else ""))
        self.synth_banner.setVisible(ds.synthetic)
        self._fill_preview(ds)
        self._fill_vars(ds)
        self._fill_mapping(ds)
        self._refresh_after_mapping()
        st.dataset_changed.emit()
        self.state.toast.emit(f"Loaded {ds.path.name} (read-only).", "ok")

    def _fill_preview(self, ds) -> None:
        df = ds.df.head(300)
        self.preview.setColumnCount(len(df.columns))
        self.preview.setHorizontalHeaderLabels([str(c) for c in df.columns])
        self.preview.setRowCount(len(df))
        for r in range(len(df)):
            for c, col in enumerate(df.columns):
                v = df.iat[r, c]
                self.preview.setItem(r, c, QTableWidgetItem("" if pd.isna(v) else str(v)))
        self.preview.resizeColumnsToContents()
        self.preview_note.setText(f"Showing first {len(df)} of {len(ds.df)} rows. " + " ".join(ds.notes))

    def _fill_vars(self, ds) -> None:
        s = D.summary(ds)
        cols = s["columns"]
        self.vars_table.setRowCount(len(cols))
        for r, c in enumerate(cols):
            vals = [c["column"], c["dtype"], c.get("units", ""), c["missing"], c["missing_pct"],
                    c.get("min", ""), c.get("max", ""), c.get("mean", ""), c.get("std", "")]
            for k, v in enumerate(vals):
                self.vars_table.setItem(r, k, QTableWidgetItem(f"{v:.4g}" if isinstance(v, float) else str(v)))
        cov = [f"Time coverage of '{k}': {v['start']} → {v['end']} ({v['n']} stamps)" for k, v in
               s["time_coverage"].items()]
        if s["dims"]:
            cov.append("Dimensions: " + ", ".join(f"{k}={v}" for k, v in s["dims"].items()))
        if s["coords"]:
            cov.append("Coordinates: " + "; ".join(f"{k} {v['dims']} [{v['units']}] {v['min']}…{v['max']}"
                                                    for k, v in s["coords"].items()))
        self.coverage.setText("\n".join(cov) or "No time column detected.")

    def _fill_mapping(self, ds) -> None:
        cols = list(ds.df.columns)
        arrays = list(ds.extras.keys())
        for role, cb in self.combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("— not available —", "")
            for c in cols + ([a for a in arrays if role == "pressure"]):
                cb.addItem(c, c)
            cur = self.state.mapping.get(role, "")
            cb.setCurrentIndex(max(0, cb.findData(cur)))
            cb.blockSignals(False)
        for role, cb in self.array_combos.items():
            cb.clear()
            cb.addItem("— not available —", "")
            for a in arrays + cols:
                cb.addItem(a, a)
            cb.setCurrentIndex(max(0, cb.findData(self.state.extras_mapping.get(role, ""))))

    # ------------------------------------------------------------------ mapping
    def apply_mapping(self) -> None:
        st = self.state
        if st.dataset is None:
            return
        st.mapping = {r: cb.currentData() for r, cb in self.combos.items() if cb.currentData()}
        st.extras_mapping = {r: cb.currentData() for r, cb in self.array_combos.items() if cb.currentData()}
        dup = [c for c in set(st.mapping.values()) if list(st.mapping.values()).count(c) > 1]
        if dup:
            self.state.toast.emit(f"Column(s) {', '.join(dup)} mapped to more than one variable — please check.", "warn")
        st.transform_log.add("set variable mapping (user)", mapping=st.mapping, arrays=st.extras_mapping)
        self._refresh_after_mapping()
        st.dataset_changed.emit()
        self.state.toast.emit("Mapping applied (original file unchanged).", "ok")

    def derive_dexcess(self) -> None:
        st = self.state
        df = st.mapped_frame()
        if df is None:
            return
        pairs = [s for s in ("", "_sim") if f"d18o{s}" in df and f"d2h{s}" in df]
        if not pairs:
            self.state.toast.emit("Map both δ18O and δ2H first.", "warn")
            return
        if not confirm(self, "Derive d-excess", "Compute d = δ²H − 8·δ¹⁸O for " +
                       " and ".join("observed" if s == "" else "simulated" for s in pairs) +
                       " values?\n\nThis adds a derived column in memory only; rows missing either isotope stay "
                       "missing (no infilling). The step is recorded in the transformation log.", "Derive"):
            return
        for s in pairs:
            st.derived[f"dexcess{s}"] = D.derive_dexcess(df, s)
            st.transform_log.add("derive", variable=f"dexcess{s}", formula=f"d2h{s} - 8*d18o{s}")
        self._refresh_after_mapping()
        st.dataset_changed.emit()
        self.state.toast.emit("Derived d-excess added (in memory).", "ok")

    def save_copy(self) -> None:
        df = self.state.mapped_frame()
        if df is None:
            return
        src = self.state.dataset.path
        default = src.with_name(src.stem + "_mapped.csv")
        path, _ = QFileDialog.getSaveFileName(self, "Save mapped copy", str(default), "CSV (*.csv)")
        if not path:
            return
        p = Path(path)
        if p.resolve() == src.resolve():
            self.state.toast.emit("Refusing to overwrite the original data file. Choose a new name.", "error")
            return
        if p.exists() and not confirm(self, "Overwrite?", f"{p.name} already exists. Overwrite it?", "Overwrite", True):
            return
        with open(p, "w", encoding="utf-8", newline="") as fh:
            if self.state.dataset.synthetic:
                fh.write("# SYNTHETIC DATA — derived from a synthetic example file\n")
            fh.write(f"# Derived from {src.name} (sha256 {self.state.dataset.sha256[:16]}…) by IsoResearch AI\n")
            df.to_csv(fh, index=False)
        self.state.transform_log.add("export mapped copy", file=str(p))
        self._refresh_log()
        self.state.toast.emit(f"Saved {p.name}", "ok")

    def _refresh_after_mapping(self) -> None:
        df = self.state.mapped_frame()
        if df is None:
            return
        issues = D.qc_report(df)
        self.qc_table.setRowCount(len(issues))
        for r, i in enumerate(issues):
            sev = QTableWidgetItem(i["severity"])
            sev.setForeground(QColor(SEV_COLORS.get(i["severity"], "#8d989e")))
            self.qc_table.setItem(r, 0, sev)
            self.qc_table.setItem(r, 1, QTableWidgetItem(i["variable"]))
            self.qc_table.setItem(r, 2, QTableWidgetItem(i["issue"]))
        num = df.select_dtypes("number")
        txt = num.describe().T.round(3).to_string() if not num.empty else "No numeric mapped variables."
        self.stats_text.setPlainText("Descriptive statistics of mapped variables\n\n" + txt)
        roles = [c for c in df.columns]
        for cb in (self.qp_x, self.qp_y):
            cur = cb.currentText()
            cb.clear()
            cb.addItems(roles)
            if cur in roles:
                cb.setCurrentText(cur)
        if "d18o" in roles:
            self.qp_y.setCurrentText("d18o")
        if "time" in roles:
            self.qp_x.setCurrentText("time")
        self._refresh_log()

    def _refresh_log(self) -> None:
        if self.state.transform_log:
            self.log_view.setPlainText(self.state.transform_log.as_text())

    def export_log(self) -> None:
        if not self.state.transform_log:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export transformation log",
                                              str(self.ctx.paths.exports_dir / "transformation_log.txt"), "*.txt")
        if path:
            p = Path(path)
            if p.exists() and not confirm(self, "Overwrite?", f"{p.name} exists. Overwrite?", "Overwrite", True):
                return
            write_text(p, self.state.transform_log.as_text(), overwrite=True)

    # ------------------------------------------------------------------ quick plots
    def quick_plot(self) -> None:
        df = self.state.mapped_frame()
        if df is None:
            return
        kind = self.qp_kind.currentIndex()
        x, y = self.qp_x.currentText(), self.qp_y.currentText()
        self.fig.clear()
        stats = ""
        try:
            if kind == 0:
                ax = self.fig.add_subplot(111)
                recipes._style(ax)
                d = df[["time", y]].dropna().sort_values("time") if "time" in df else None
                if d is None:
                    raise ValueError("Map a time column first.")
                ax.plot(d["time"], d[y], "o-", ms=3, lw=0.8, color=recipes.PALETTE[0])
                ax.set_ylabel(recipes._lab(y))
                self.fig.autofmt_xdate()
                stats = f"{y}: n = {len(d)}, mean = {d[y].mean():.3g}, sd = {d[y].std():.3g}"
            elif kind == 1:
                ax = self.fig.add_subplot(111)
                recipes._style(ax)
                d = df[[x, y]].dropna()
                ax.scatter(d[x], d[y], s=16, color=recipes.PALETTE[0], alpha=0.8)
                ax.set_xlabel(recipes._lab(x))
                ax.set_ylabel(recipes._lab(y))
                if len(d) >= 3 and x != "time":
                    o = recipes._ols(d[x].astype(float), d[y].astype(float))
                    stats = (f"n = {o['n']}, OLS slope = {o['slope']:.4g} ± {o['slope_ci']:.2g}, "
                             f"r = {o['r']:.2f}, p = {o['p']:.2g}")
            elif kind == 2:
                num = df.select_dtypes("number")
                c = num.corr()
                ax = self.fig.add_subplot(111)
                im = ax.imshow(c.values, cmap="RdBu_r", vmin=-1, vmax=1)
                ax.set_xticks(range(len(c)), c.columns, rotation=60, ha="right", fontsize=7)
                ax.set_yticks(range(len(c)), c.columns, fontsize=7)
                for i in range(len(c)):
                    for j in range(len(c)):
                        if np.isfinite(c.values[i, j]):
                            ax.text(j, i, f"{c.values[i, j]:.2f}", ha="center", va="center", fontsize=6)
                self.fig.colorbar(im, ax=ax, shrink=0.8, label="Pearson r (pairwise complete)")
                stats = "Pairwise-complete Pearson correlations; not adjusted for autocorrelation or multiple testing."
            else:
                var = y.replace("_sim", "")
                if f"{var}_sim" not in df or var not in df:
                    raise ValueError("Choose y = an observed isotope variable that also has a mapped *_sim column.")
                res = recipes.obs_vs_sim(df, self.fig, {"var": var})
                stats = " · ".join(res["stats"])
        except Exception as exc:  # noqa: BLE001
            self.fig.clear()
            stats = f"Cannot draw this plot: {exc}"
        self.canvas.draw_idle()
        self.qp_stats.setText(stats)
        self.state.transform_log.add("quick plot (no data change)", kind=self.qp_kind.currentText(), x=x, y=y)
        self._refresh_log()


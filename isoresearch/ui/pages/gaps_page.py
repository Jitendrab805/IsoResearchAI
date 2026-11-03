"""Research gap finder."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                               QProgressBar, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ...export.exporters import write_text
from ...research.gaps import PROVISIONAL_NOTE, GapService
from ...research.literature import LiteratureService
from ..state import AppState
from ..widgets.common import Banner, Card, EmptyState, PageHeader, Pill, button, confirm, label
from ..workers import run_task

KIND = {"explicit": ("Author-stated", "ok"), "inferred": ("AI-inferred", "accent"),
        "combination": ("Underexplored combination", "warn")}
CONF = {"high": "ok", "medium": "accent", "low": "warn"}


class GapCard(Card):
    def __init__(self, g: dict, page: "GapsPage"):
        super().__init__(spacing=6)
        pal = page.state.pal
        top = QHBoxLayout()
        k, s = KIND.get(g["kind"], (g["kind"], ""))
        top.addWidget(Pill(k, s))
        top.addWidget(Pill(f"evidence: {g['confidence']}", CONF.get(g["confidence"], "")))
        top.addWidget(Pill(g["status"], "" if g["status"] == "provisional" else "ok"))
        top.addStretch(1)
        top.addWidget(button("Discuss in chat", "chat-plus", "Ghost", color=pal.muted,
                             slot=lambda: page.state.ask_in_chat.emit(
                                 f"Critically assess this provisional research gap using my library: {g['title']}. "
                                 f"{g.get('description', '')}")))
        top.addWidget(button("Mark verified", "check", "Ghost", "Use after checking the wider literature", pal.muted,
                             slot=lambda: page.set_status(g["id"], "verified")))
        top.addWidget(button("", "trash", "Ghost", "Delete", pal.muted, slot=lambda: page.delete(g["id"])))
        self.lay.addLayout(top)
        self.lay.addWidget(label(f"<b>{_e(g['title'])}</b>", wrap=True))
        for key, name in (("description", "What"), ("why_matters", "Why it matters"), ("hypothesis", "Hypothesis")):
            if g.get(key):
                self.lay.addWidget(label(f"<span style='color:{pal.muted}'>{name}:</span> {_e(g[key])}", wrap=True))
        for q in g.get("questions", []):
            self.lay.addWidget(label(f"<span style='color:{pal.accent}'>Research question:</span> {_e(q)}", wrap=True))
        if g.get("supporting"):
            row = QHBoxLayout()
            row.addWidget(label("Supporting papers:", "Faint"))
            for s_ in g["supporting"][:6]:
                pages = s_.get("pages") or [1]
                b = button(f"{s_['label'][:55]}" + (f" p.{pages[0]}" if s_.get("pages") else ""), kind="Link")
                b.clicked.connect(lambda _=False, d=s_["doc_id"], p=pages[0]: page.state.open_pdf.emit(d, p))
                row.addWidget(b)
            row.addStretch(1)
            self.lay.addLayout(row)
        if g.get("needed"):
            self.lay.addWidget(label(f"Needed to validate: {_e(g['needed'])}", "Faint", wrap=True))


def _e(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class GapsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.lit = LiteratureService(self.ctx.db, self.ctx.search, self.ctx.llm, self.ctx.settings)
        self.svc = GapService(self.ctx.db, self.lit, self.ctx.llm)
        self.task = None
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(10)
        root.addWidget(PageHeader("Research Gap Finder", "Compares objectives, regions, observations, models and "
                                  "methods across papers. Author-stated gaps, underexplored combinations and AI-inferred "
                                  "gaps are kept separate.", "Questions"))
        root.addWidget(Banner(PROVISIONAL_NOTE + " Confidence describes the amount of local evidence, not the "
                              "probability of novelty."))
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(label("Papers to compare", "Muted"))
        self.papers = QListWidget()
        ll.addWidget(self.papers, 1)
        self.use_llm = QCheckBox("Include AI-inferred gaps (local model)")
        self.use_llm.setChecked(True)
        ll.addWidget(self.use_llm)
        ll.addWidget(button("Analyse ticked papers", "gap", "Primary", color=pal.accent_text, slot=self.analyse))
        ll.addWidget(label("Tip: run 'Extract with local AI' in Literature Review first — author-stated limitations "
                           "and future work come from those records.", "Faint", wrap=True))
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem("All types", None)
        for k, (t, _) in KIND.items():
            self.kind.addItem(t, k)
        self.kind.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.kind)
        bar.addStretch(1)
        bar.addWidget(button("Export Markdown", "export", color=pal.muted, slot=self.export))
        bar.addWidget(button("Clear all", "trash", "Danger", color=pal.danger, slot=self.clear))
        rl.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QWidget()
        self.inner_lay = QVBoxLayout(self.inner)
        self.inner_lay.setSpacing(10)
        self.scroll.setWidget(self.inner)
        rl.addWidget(self.scroll, 1)
        split.addWidget(right)
        split.setSizes([300, 900])
        root.addWidget(split, 1)
        prow = QHBoxLayout()
        self.prog_label = label("", "Muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(280)
        prow.addWidget(self.prog_label, 1)
        prow.addWidget(self.progress)
        prow.addWidget(button("Stop", "stop", "Ghost", color=pal.muted, slot=lambda: self.task and self.task.cancel()))
        self.prog_row = QWidget()
        self.prog_row.setLayout(prow)
        self.prog_row.hide()
        root.addWidget(self.prog_row)
        state.library_changed.connect(self.refresh_papers)
        self.refresh_papers()
        self.refresh()

    def refresh_papers(self) -> None:
        self.papers.clear()
        for d in self.ctx.repo.documents(status="indexed"):
            it = QListWidgetItem(d.get("display_label") or d.get("title") or d["filename"])
            it.setData(Qt.ItemDataRole.UserRole, d["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.papers.addItem(it)

    def refresh(self) -> None:
        while self.inner_lay.count():
            w = self.inner_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        kind = self.kind.currentData()
        gaps = [g for g in self.svc.list() if kind is None or g["kind"] == kind]
        if not gaps:
            self.inner_lay.addWidget(EmptyState("gap", "No gaps analysed yet",
                                                "Tick papers and press Analyse. Works without AI (author-stated "
                                                "limitations and combination analysis); the local model adds "
                                                "inferred gaps and testable questions."))
        for g in gaps:
            self.inner_lay.addWidget(GapCard(g, self))
        self.inner_lay.addStretch(1)

    def analyse(self) -> None:
        ids = [self.papers.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.papers.count())
               if self.papers.item(i).checkState() == Qt.CheckState.Checked]
        if len(ids) < 1 or self.task:
            self.state.toast.emit("Tick at least one indexed paper.", "warn")
            return
        use_llm = self.use_llm.isChecked()
        if use_llm and not self.state.model_status.get("ready"):
            self.state.toast.emit("Local model not ready — running the no-AI analysis only.", "warn")
            use_llm = False
        self.prog_row.show()
        self.prog_label.setText("Analysing papers…")
        profile = self.ctx.settings.profile
        self.task = run_task(lambda t: self.svc.analyse(ids, profile, use_llm, t.cancel_event),
                             on_result=self._done, on_error=self._err)

    def _done(self, gaps) -> None:
        self.task = None
        self.prog_row.hide()
        if gaps:
            self.state.toast.emit(f"{len(gaps)} provisional gap(s) recorded.", "ok")
        else:
            self.state.toast.emit("No gaps could be derived from the current records. Run 'Extract with local AI' in "
                                  "Literature Review, or fill the limitations / further-work / model / region fields.",
                                  "warn")
        self.refresh()

    def _err(self, exc) -> None:
        self.task = None
        self.prog_row.hide()
        self.state.toast.emit(f"Gap analysis failed: {exc}", "error")
        self.refresh()

    def set_status(self, gid: int, status: str) -> None:
        if confirm(self, "Mark verified", "Only mark a gap as verified after checking the wider literature "
                   "(not just this library). Continue?", "Mark verified"):
            self.svc.set_status(gid, status)
            self.refresh()

    def delete(self, gid: int) -> None:
        self.svc.delete(gid)
        self.refresh()

    def clear(self) -> None:
        if confirm(self, "Clear gaps", "Delete all recorded gaps?", "Delete all", True):
            self.svc.clear()
            self.refresh()

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export gaps", str(self.ctx.paths.exports_dir / "research_gaps.md"),
                                              "Markdown (*.md)")
        if path:
            p = Path(path)
            if p.exists() and not confirm(self, "Overwrite?", f"{p.name} exists. Overwrite?", "Overwrite", True):
                return
            write_text(p, self.svc.export_markdown(), overwrite=True)
            self.state.toast.emit(f"Exported {p.name}", "ok")

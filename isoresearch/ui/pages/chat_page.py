"""Research chat workspace (welcome screen + cited, streaming conversation)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QStackedWidget, QVBoxLayout, QWidget)

from ...llm.ollama_client import LLMCancelled, LLMUnavailable
from ...retrieval.search import SearchFilters
from ..icons import logo_pixmap
from ..state import AppState
from ..widgets.chat_widgets import ChatView, ComposerInput, MessageBubble, ThinkingDots
from ..widgets.common import Pill, button, label
from ..workers import run_task

SUGGESTIONS = [
    ("Amount effect", "What evidence in my library supports or questions the amount effect in tropical "
                      "island rainfall, and on what timescales?"),
    ("d-excess", "What controls d-excess of monsoon rainfall over the Bay of Bengal and Andaman Sea?"),
    ("Model evaluation", "How have isotope-enabled regional models such as IsoRSM been evaluated against "
                         "rainfall isotope observations, and which metrics were used?"),
    ("Satellites", "How should averaging kernels and a priori profiles be used when comparing model output "
                   "with satellite vapour isotope retrievals?"),
    ("Upstream convection", "Do rainfall isotopes reflect local rainfall or upstream convection along "
                            "back trajectories during the Indian summer monsoon?"),
    ("Plot design", "Which plots would best show whether IsoRSM reproduces event-scale δ18O variability "
                    "at Port Blair, and what statistics should accompany them?"),
]


class SuggestionCard(QFrame):
    def __init__(self, title: str, text: str, pal, on_click):
        super().__init__()
        self.setObjectName("Suggestion")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.text = text
        self.on_click = on_click
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        lay.addWidget(label(title.upper(), "Eyebrow"))
        t = label(text, wrap=True)
        lay.addWidget(t)
        self.setToolTip("Click to ask this question")

    def mousePressEvent(self, e):  # noqa: N802
        self.on_click(self.text)


class ChatPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.conv_id: int | None = None
        self.task = None
        self.stream_bubble: MessageBubble | None = None
        self.stream_text = ""
        self.turn = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_stream)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # ---------------- header
        self.header = QWidget()
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(24, 14, 20, 10)
        self.title = label("New research chat", "H2")
        hl.addWidget(self.title)
        self.scope_pill = Pill("Scope: whole library", "accent")
        hl.addWidget(self.scope_pill)
        hl.addStretch(1)
        pal = state.pal
        self.rename_btn = button("", "edit", "Ghost", "Rename conversation", pal.muted, self.rename)
        hl.addWidget(self.rename_btn)
        exp = button(" Export", "export", "Ghost", "Export conversation", pal.muted)
        menu = QMenu(exp)
        menu.addAction("Markdown (.md)", lambda: self.export("md"))
        menu.addAction("Plain text (.txt)", lambda: self.export("txt"))
        exp.setMenu(menu)
        hl.addWidget(exp)
        ctx_btn = button("", "panel", "Ghost", "Show/hide research context panel (Ctrl+Shift+P)", pal.muted,
                         lambda: self.window().toggle_context())
        hl.addWidget(ctx_btn)
        root.addWidget(self.header)

        self.stack = QStackedWidget()
        self.welcome = self._build_welcome()
        self.view = ChatView()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.view)
        root.addWidget(self.stack, 1)

        # ---------------- composer
        comp_wrap = QWidget()
        cw = QHBoxLayout(comp_wrap)
        cw.setContentsMargins(24, 6, 24, 16)
        self.composer = QFrame()
        self.composer.setObjectName("Composer")
        self.composer.setMaximumWidth(900)
        cl = QVBoxLayout(self.composer)
        cl.setContentsMargins(14, 10, 10, 8)
        cl.setSpacing(6)
        self.input = ComposerInput()
        self.input.submitted.connect(self.send)
        self.input.focus_changed.connect(self._focus)
        cl.addWidget(self.input)
        row = QHBoxLayout()
        self.model_pill = Pill("Model: checking…", "")
        row.addWidget(self.model_pill)
        self.hint = label("Answers cite passages from your local PDFs. Code is never executed automatically.", "Faint")
        row.addWidget(self.hint, 1)
        self.stop_btn = button("", "stop", "Stop", "Stop generating", pal.text, self.stop)
        self.stop_btn.hide()
        row.addWidget(self.stop_btn)
        self.send_btn = button("", "send", "Send", "Send (Enter)", pal.accent_text, self.send)
        row.addWidget(self.send_btn)
        cl.addLayout(row)
        cw.addStretch(1)
        cw.addWidget(self.composer, 100)
        cw.addStretch(1)
        root.addWidget(comp_wrap)

        state.model_status_changed.connect(self._model_status)
        state.scope_changed.connect(self._scope_label)
        state.ask_in_chat.connect(self.ask_external)
        self._scope_label()
        self._model_status(state.model_status)

    # ------------------------------------------------------------------ welcome
    def _build_welcome(self) -> QWidget:
        pal = self.state.pal
        w = QWidget()
        outer = QHBoxLayout(w)
        col = QWidget()
        col.setMaximumWidth(880)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(24, 28, 24, 12)
        lay.setSpacing(10)
        lg = QLabel()
        lg.setPixmap(logo_pixmap(56))
        lay.addWidget(lg)
        lay.addWidget(label("PRIVATE RESEARCH WORKSTATION", "Eyebrow"))
        lay.addWidget(label("What are you investigating today?", "Hero"))
        lay.addWidget(label("IsoResearch AI answers from the papers in your local library and cites the exact page. "
                            "Everything — papers, embeddings, chats and the AI model — stays on this computer.",
                            "PageSubtitle", wrap=True))
        lay.addSpacing(6)
        self.checklist = QHBoxLayout()
        self.check_model = Pill("AI model: checking", "")
        self.check_lib = Pill("Library: –", "")
        self.check_off = Pill("Strict offline", "ok")
        for p in (self.check_model, self.check_lib, self.check_off):
            self.checklist.addWidget(p)
        self.checklist.addStretch(1)
        lay.addLayout(self.checklist)
        lay.addSpacing(10)
        lay.addWidget(label("Suggested research questions", "Muted"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, (t, q) in enumerate(SUGGESTIONS):
            grid.addWidget(SuggestionCard(t, q, pal, self.ask_external), i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        outer.addStretch(1)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        return w

    def refresh_welcome(self) -> None:
        c = self.ctx.repo.counts()
        n = c.get("total", 0)
        self.check_lib.set_state("ok" if n else "warn", f"Library: {n} paper(s), {c.get('chunks', 0)} passages")
        self.check_off.set_state("ok" if self.ctx.settings.strict_offline else "warn",
                                 "Strict offline: ON" if self.ctx.settings.strict_offline else "Strict offline: OFF")

    def showEvent(self, e):  # noqa: N802
        self.refresh_welcome()
        super().showEvent(e)

    # ------------------------------------------------------------------ status
    def _model_status(self, st: dict) -> None:
        if st.get("ready"):
            self.model_pill.set_state("ok", f"● {st.get('model')} · local")
            self.check_model.set_state("ok", f"AI model ready: {st.get('model')}")
        elif st.get("running"):
            self.model_pill.set_state("warn", "● Ollama running · no model selected/downloaded")
            self.check_model.set_state("warn", "AI model: choose/download a model in Settings")
        else:
            self.model_pill.set_state("error", "● Local AI offline — library search only")
            self.check_model.set_state("error", "AI model: Ollama not running")

    def _scope_label(self) -> None:
        ids = self.state.scope_doc_ids()
        txt = "Scope: whole library" if ids is None else f"Scope: {len(ids)} paper(s)"
        if self.state.topic:
            txt += f" · topic: {self.state.topic[:30]}"
        self.scope_pill.setText(txt)

    def _focus(self, on: bool) -> None:
        self.composer.setProperty("focus", "true" if on else "false")
        self.composer.style().unpolish(self.composer)
        self.composer.style().polish(self.composer)

    # ------------------------------------------------------------------ conversations
    def new_chat(self) -> None:
        if self.task:
            self.stop()
        self.conv_id = None
        self.view.clear()
        self.title.setText("New research chat")
        self.stack.setCurrentIndex(0)
        self.refresh_welcome()
        self.state.sources_changed.emit([])
        self.input.setFocus()

    def load_conversation(self, cid: int) -> None:
        if self.task:
            self.stop()
        conv = self.ctx.chat.store.get(cid)
        if not conv:
            return
        self.conv_id = cid
        self.title.setText(conv["title"])
        self.view.clear()
        pal = self.state.pal
        last_cits: list = []
        for m in self.ctx.chat.store.messages(cid):
            b = MessageBubble(m["role"], m["content"], pal, m["citations"], m.get("model") or "", m["created_at"])
            self._wire(b)
            self.view.add(b, align_right=m["role"] == "user")
            if m["role"] == "assistant":
                last_cits = m["citations"]
        self.stack.setCurrentIndex(1)
        self.state.sources_changed.emit(last_cits)

    def rename(self) -> None:
        if not self.conv_id:
            return
        t, ok = QInputDialog.getText(self, "Rename conversation", "Title:", text=self.title.text())
        if ok and t.strip():
            self.ctx.chat.store.rename(self.conv_id, t)
            self.title.setText(t.strip())
            self.state.conversations_changed.emit()

    def export(self, fmt: str) -> None:
        if not self.conv_id:
            self.state.toast.emit("Nothing to export yet — start a conversation first.", "warn")
            return
        default = str(self.ctx.paths.exports_dir / f"conversation_{self.conv_id}.{fmt}")
        path, _ = QFileDialog.getSaveFileName(self, "Export conversation", default,
                                              "Markdown (*.md)" if fmt == "md" else "Text (*.txt)")
        if not path:
            return
        Path(path).write_text(self.ctx.chat.store.export(self.conv_id, fmt), encoding="utf-8")
        self.state.toast.emit(f"Exported to {Path(path).name}", "ok")

    # ------------------------------------------------------------------ sending
    def ask_external(self, text: str) -> None:
        self.input.setPlainText(text)
        self.send()

    def _wire(self, b: MessageBubble) -> None:
        b.open_source.connect(lambda c: self.state.open_pdf.emit(int(c["doc_id"]), int(c["page"])))
        b.select_source.connect(self.state.source_selected.emit)
        b.action.connect(self._bubble_action)

    def _bubble_action(self, key: str) -> None:
        if key == "settings":
            self.state.navigate.emit("settings")
        elif key == "library":
            self.state.navigate.emit("library")

    def _filters(self) -> SearchFilters:
        return SearchFilters(doc_ids=self.state.scope_doc_ids(), year_min=self.state.year_min,
                             year_max=self.state.year_max)

    def send(self) -> None:
        q = self.input.toPlainText().strip()
        if not q or self.task:
            return
        self.input.clear()
        if self.conv_id is None:
            self.conv_id = self.ctx.chat.store.create(scope={"collections": self.state.scope_collections})
            self.state.conversations_changed.emit()
        self.stack.setCurrentIndex(1)
        pal = self.state.pal
        ub = MessageBubble("user", q, pal)
        self.view.add(ub, align_right=True)
        self.thinking = ThinkingDots("Searching your library")
        self.view.add(self.thinking)
        self._busy(True)
        filters = self._filters()
        topic = self.state.topic
        cid = self.conv_id
        self.task = run_task(lambda t: self.ctx.chat.prepare(cid, q, filters, topic),
                             on_result=self._prepared, on_error=self._failed)

    def _prepared(self, turn) -> None:
        self.turn = turn
        self.state.sources_changed.emit([{"n": i, "doc_id": c.doc_id, "chunk_id": c.id, "title": c.title,
                                          "authors": c.authors, "year": c.year, "page": c.page,
                                          "section": c.section, "excerpt": c.text[:400], "used": True}
                                         for i, c in enumerate(turn.sources, 1)])
        self.thinking.set_base(f"Found {len(turn.sources)} passage(s) · generating with the local model")
        self.stream_text = ""
        self.task = run_task(self._stream_worker, on_token=self._token, on_result=self._done, on_error=self._failed)

    def _stream_worker(self, t):
        for piece in self.ctx.chat.stream(self.turn, cancel=t.cancel_event):
            t.token(piece)
        return True

    def _token(self, piece: str) -> None:
        if self.stream_bubble is None:
            self.thinking.deleteLater()
            self.thinking = None
            self.stream_bubble = MessageBubble("assistant", "", self.state.pal, model=self.ctx.llm.model)
            self.stream_bubble.set_status("generating…")
            self._wire(self.stream_bubble)
            self.view.add(self.stream_bubble)
        self.stream_text += piece
        if not self._render_timer.isActive():
            self._render_timer.start(70)

    def _render_stream(self) -> None:
        if self.stream_bubble:
            self.stream_bubble.set_text(self.stream_text + " ▍")

    def _done(self, _=None, stopped: bool = False) -> None:
        self._render_timer.stop()
        text = self.stream_text
        if stopped:
            text += "\n\n> ⏹ Generation stopped by user; the answer above is incomplete."
        if not text.strip():
            self._failed(RuntimeError("The model returned an empty response."))
            return
        final, report = self.ctx.chat.finalize(self.turn, text)
        if self.stream_bubble is None:
            self._token("")
        b = self.stream_bubble
        b.set_text(final)
        b.set_status("")
        cits = []
        for c in report.citations:
            d = c.to_dict()
            d["used"] = c.n in report.used
            cits.append(d)
        b.set_citations(cits)
        self.state.sources_changed.emit(cits)
        conv = self.ctx.chat.store.get(self.turn.conv_id)
        if conv:
            self.title.setText(conv["title"])
        self.state.conversations_changed.emit()
        self._reset()

    def _failed(self, exc) -> None:
        if isinstance(exc, LLMCancelled):
            if self.stream_text.strip():
                self._done(stopped=True)
            else:
                self._cleanup_thinking()
                self.view.add(MessageBubble("error", "Generation stopped before any text was produced.", self.state.pal))
                self._reset()
            return
        self._cleanup_thinking()
        pal = self.state.pal
        if isinstance(exc, LLMUnavailable):
            msg = (f"**The local AI model is not available**, so no answer was generated "
                   f"(IsoResearch AI never fabricates responses).\n\n{exc}\n\n"
                   "You can still browse and search your library below, or fix the model in Settings → AI model.")
        else:
            msg = f"**Something went wrong:** {type(exc).__name__}: {exc}"
        b = MessageBubble("error", msg, pal)
        b.add_action("Open AI model settings", "settings", primary=True)
        self.view.add(b)
        if self.turn is not None and self.turn.sources:
            lines = ["Most relevant passages in your library for this question (keyword + semantic search, "
                     "**no AI interpretation**):", ""]
            cits = []
            for i, c in enumerate(self.turn.sources[:6], 1):
                lines.append(f"**[S{i}] {c.label()}** — {c.section or ''}\n\n> {c.text[:420]}…\n")
                cits.append({"n": i, "doc_id": c.doc_id, "chunk_id": c.id, "title": c.title, "authors": c.authors,
                             "year": c.year, "page": c.page, "section": c.section, "excerpt": c.text[:400],
                             "used": True})
            lb = MessageBubble("library", "\n".join(lines), pal, cits)
            self._wire(lb)
            self.view.add(lb)
        self._reset()

    def _cleanup_thinking(self) -> None:
        if getattr(self, "thinking", None):
            self.thinking.deleteLater()
            self.thinking = None
        if self.stream_bubble is not None and not self.stream_text.strip():
            self.stream_bubble.deleteLater()
            self.stream_bubble = None

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.stop_btn.setEnabled(False)

    def _reset(self) -> None:
        self.task = None
        self.stream_bubble = None
        self.turn = None
        self._busy(False)

    def _busy(self, on: bool) -> None:
        self.send_btn.setVisible(not on)
        self.stop_btn.setVisible(on)
        self.stop_btn.setEnabled(True)
        self.send_btn.setEnabled(not on)

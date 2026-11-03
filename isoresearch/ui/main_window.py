"""Main window: sidebar navigation, workspace stack, context panel and status bar."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..core import offline
from .context_panel import ContextPanel
from .icons import icon, logo_icon, logo_pixmap
from .pages.chat_page import ChatPage
from .pages.data_page import DataPage
from .pages.gaps_page import GapsPage
from .pages.history_page import HistoryPage
from .pages.library_page import LibraryPage
from .pages.literature_page import LiteraturePage
from .pages.plot_page import PlotPage
from .pages.references_page import ReferencesPage
from .pages.settings_page import SettingsPage
from .pdf_viewer import open_pdf
from .state import AppState
from .theme import arrow_assets, qpalette, stylesheet
from .widgets.common import Pill, Toast, label
from .workers import cancel_all, run_task, wait_all

NAV = [
    ("RESEARCH", None, None),
    ("history", "Chat History", "history"),
    ("library", "Research Library", "library"),
    ("literature", "Literature Review", "review"),
    ("gaps", "Research Gap Finder", "gap"),
    ("ANALYSIS", None, None),
    ("plots", "Plot Advisor", "plot"),
    ("data", "Data Analysis", "data"),
    ("references", "Reference Manager", "references"),
    ("SYSTEM", None, None),
    ("settings", "Settings", "settings"),
]


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.setWindowTitle(f"{APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1080, 660))
        self.setAcceptDrops(True)
        central = QWidget()
        central.setObjectName("Workspace")
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = self._build_sidebar()
        h.addWidget(self.sidebar)
        self._context_wanted = True
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.stack = QStackedWidget()
        self.pages = {
            "chat": ChatPage(state), "history": HistoryPage(state), "library": LibraryPage(state),
            "literature": LiteraturePage(state), "gaps": GapsPage(state), "plots": PlotPage(state),
            "data": DataPage(state), "references": ReferencesPage(state),
            "settings": SettingsPage(state, on_theme=self.apply_theme),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.split.addWidget(self.stack)
        self.context = ContextPanel(state)
        self.split.addWidget(self.context)
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([1060, 340])
        h.addWidget(self.split, 1)
        self.setCentralWidget(central)
        self._build_statusbar()

        self.pages["history"].open_conversation.connect(self.open_conversation)
        state.toast.connect(self.toast)
        state.open_pdf.connect(self.open_pdf)
        state.navigate.connect(self.navigate)
        state.ask_in_chat.connect(lambda _: self.navigate("chat"))
        state.model_status_changed.connect(self._status_pill)
        state.library_changed.connect(self._lib_status)
        self._shortcuts()
        self.apply_theme()
        self.navigate("chat")
        QTimer.singleShot(150, self.check_model)
        QTimer.singleShot(400, self._ensure_index)
        self.model_timer = QTimer(self)
        self.model_timer.timeout.connect(self.check_model)
        self.model_timer.start(60_000)

    # ------------------------------------------------------------------ layout
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(236)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(2)
        brand = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(logo_pixmap(34))
        brand.addWidget(lg)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("IsoResearch AI", "BrandName"))
        names.addWidget(label("ISOTOPE WORKSTATION", "BrandSub"))
        brand.addLayout(names)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(16)
        self.new_chat_btn = QPushButton("  New Research Chat")
        self.new_chat_btn.setObjectName("NewChat")
        self.new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_btn.setToolTip("Start a new conversation (Ctrl+N)")
        self.new_chat_btn.clicked.connect(self.new_chat)
        lay.addWidget(self.new_chat_btn)
        lay.addSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, ico in NAV:
            if text is None:
                lay.addWidget(label(key, "NavSection"))
                continue
            b = QPushButton("  " + text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            b.setProperty("ico", ico)
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)
        self.side_offline = Pill("", "ok")
        lay.addWidget(self.side_offline)
        self.side_model = Pill("AI: checking…", "")
        self.side_model.setWordWrap(True)
        lay.addWidget(self.side_model)
        return side

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.sb_model = QLabel()
        self.sb_lib = QLabel()
        self.sb_embed = QLabel()
        self.sb_ver = QLabel(f"v{__version__}")
        for w in (self.sb_model, self.sb_lib, self.sb_embed):
            sb.addWidget(w)
        sb.addPermanentWidget(self.sb_ver)
        self._lib_status()

    def _shortcuts(self) -> None:
        for seq, fn in ((QKeySequence.StandardKey.New, self.new_chat),
                        (QKeySequence("Ctrl+L"), lambda: self.navigate("library")),
                        (QKeySequence("Ctrl+,"), lambda: self.navigate("settings")),
                        (QKeySequence("Ctrl+Shift+P"), self.toggle_context)):
            a = QAction(self)
            a.setShortcut(seq)
            a.triggered.connect(fn)
            self.addAction(a)

    def toggle_context(self) -> None:
        self._context_wanted = not self._context_wanted
        self.context.setVisible(self._context_wanted and self.stack.currentWidget() is self.pages["chat"])

    def apply_theme(self) -> None:
        pal = self.state.pal
        app = QApplication.instance()
        app.setPalette(qpalette(pal))
        arrows = arrow_assets(pal, self.ctx.paths.home / "ui-cache")
        app.setStyleSheet(stylesheet(pal, float(self.ctx.settings.get("ui.font_scale", 1.0)), arrows))
        for key, b in self.nav_buttons.items():
            b.setIcon(icon(b.property("ico"), pal.muted, pal.accent))
        self.new_chat_btn.setIcon(icon("chat-plus", pal.accent_text))
        self.side_offline.set_state("ok" if self.ctx.settings.strict_offline else "warn",
                                    "🛡 Strict offline" if self.ctx.settings.strict_offline else "Offline guard OFF")
        self.state.theme_changed.emit()

    # ------------------------------------------------------------------ navigation
    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[key])
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        else:
            self.nav_group.setExclusive(False)
            for b in self.nav_buttons.values():
                b.setChecked(False)
            self.nav_group.setExclusive(True)
        self.context.setVisible(key == "chat" and self._context_wanted)

    def new_chat(self) -> None:
        self.pages["chat"].new_chat()
        self.navigate("chat")

    def open_conversation(self, cid: int) -> None:
        self.pages["chat"].load_conversation(cid)
        self.navigate("chat")

    def open_pdf(self, doc_id: int, page: int) -> None:
        d = self.ctx.repo.document(doc_id)
        if not d:
            self.toast("That document is no longer in the library.", "warn")
            return
        excerpt = ""
        open_pdf(self, d["stored_path"], page, d.get("display_label") or d.get("title") or d["filename"], excerpt)

    def toast(self, text: str, kind: str = "ok") -> None:
        Toast(self.centralWidget(), text, kind)

    # ------------------------------------------------------------------ status
    def check_model(self) -> None:
        run_task(lambda t: self.ctx.llm.status(), on_result=self._model_result,
                 on_error=lambda e: self._model_result({"ready": False, "running": False, "error": str(e),
                                                        "models": []}))

    def _model_result(self, st: dict) -> None:
        self.state.model_status = st
        self.state.model_status_changed.emit(st)

    def _status_pill(self, st: dict) -> None:
        if st.get("ready"):
            self.side_model.set_state("ok", f"AI: {st.get('model')} (verified local)")
            self.sb_model.setText(f"● Local model verified: {st.get('model')} via Ollama {st.get('version', '')}")
        elif st.get("running"):
            self.side_model.set_state("warn", "AI: no model selected")
            self.sb_model.setText("● Ollama running — select/download a model in Settings")
        else:
            self.side_model.set_state("error", "AI: offline (library only)")
            self.sb_model.setText("● Local AI not reachable — AI features disabled; library tools still work")

    def _lib_status(self) -> None:
        c = self.ctx.repo.counts()
        self.sb_lib.setText(f"   Library: {c.get('total', 0)} papers · {c.get('chunks', 0)} passages")
        self.sb_embed.setText(f"   {self.ctx.search.embedder_status.split('(')[0].strip()}"
                              f"   ·   offline guard: {'on' if offline.is_enabled() else 'off'}")

    def _ensure_index(self) -> None:
        if self.ctx.search.index.needs_rebuild or len(self.ctx.search.index) != self.ctx.repo.counts().get("chunks", 0):
            self.toast("Rebuilding the search index in the background…", "info")
            run_task(lambda t: self.ctx.search.ensure_index(), on_result=lambda _: self._lib_status(),
                     on_error=lambda e: self.toast(f"Index rebuild failed: {e}", "error"))

    # ------------------------------------------------------------------ drag & drop / close
    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        from pathlib import Path

        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        pdfs = [p for p in paths if p.is_dir() or p.suffix.lower() == ".pdf"]
        if pdfs:
            self.navigate("library")
            self.pages["library"].import_paths(pdfs)
        elif paths:
            self.navigate("data")
            self.pages["data"].load(paths[0])

    def closeEvent(self, e):  # noqa: N802
        cancel_all()
        wait_all(3000)
        super().closeEvent(e)

"""Chat history: search, reopen, rename, export and delete conversations."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

from ..state import AppState
from ..widgets.common import EmptyState, PageHeader, button, confirm


class HistoryPage(QWidget):
    open_conversation = Signal(int)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        pal = state.pal
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        root.addWidget(PageHeader("Chat History", "All conversations are stored locally in your database.",
                                  "Conversations"))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and message text…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        row.addWidget(button("Open", "chat-plus", "Primary", color=pal.accent_text, slot=self._open))
        row.addWidget(button("Rename", "edit", color=pal.muted, slot=self._rename))
        row.addWidget(button("Export", "export", color=pal.muted, slot=self._export))
        row.addWidget(button("Delete", "trash", "Danger", color=pal.danger, slot=self._delete))
        root.addLayout(row)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._open())
        root.addWidget(self.list, 1)
        self.empty = EmptyState("history", "No conversations yet", "Start a research chat; it will appear here.")
        root.addWidget(self.empty)
        state.conversations_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        convs = self.ctx.chat.store.list(self.search.text().strip())
        self.list.clear()
        for c in convs:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["updated_at"]))
            it = QListWidgetItem(f"{c['title']}\n{when} · {c['n_messages']} messages")
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.list.addItem(it)
        has = bool(convs) or bool(self.search.text())
        self.list.setVisible(has)
        self.empty.setVisible(not has)

    def _cid(self) -> int | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _open(self) -> None:
        cid = self._cid()
        if cid:
            self.open_conversation.emit(cid)

    def _rename(self) -> None:
        cid = self._cid()
        if not cid:
            return
        conv = self.ctx.chat.store.get(cid)
        t, ok = QInputDialog.getText(self, "Rename", "Title:", text=conv["title"])
        if ok and t.strip():
            self.ctx.chat.store.rename(cid, t)
            self.state.conversations_changed.emit()

    def _export(self) -> None:
        cid = self._cid()
        if not cid:
            return
        path, filt = QFileDialog.getSaveFileName(self, "Export conversation",
                                                 str(self.ctx.paths.exports_dir / f"conversation_{cid}.md"),
                                                 "Markdown (*.md);;Plain text (*.txt)")
        if path:
            fmt = "txt" if path.endswith(".txt") or "txt" in filt else "md"
            Path(path).write_text(self.ctx.chat.store.export(cid, fmt), encoding="utf-8")
            self.state.toast.emit(f"Exported {Path(path).name}", "ok")

    def _delete(self) -> None:
        cid = self._cid()
        if cid and confirm(self, "Delete conversation", "Delete this conversation permanently?", "Delete", True):
            self.ctx.chat.store.delete(cid)
            self.state.conversations_changed.emit()

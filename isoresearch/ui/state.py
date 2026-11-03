"""Shared GUI state and cross-page signals."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..context import AppContext
from ..ui.theme import Palette, palette


class AppState(QObject):
    library_changed = Signal()
    conversations_changed = Signal()
    model_status_changed = Signal(dict)
    sources_changed = Signal(list)  # list[dict] citations of the latest answer
    source_selected = Signal(dict)  # one citation dict
    dataset_changed = Signal()
    scope_changed = Signal()
    theme_changed = Signal()
    toast = Signal(str, str)  # text, kind
    open_pdf = Signal(int, int)  # doc_id, page
    ask_in_chat = Signal(str)  # prefill/send a question to the chat
    navigate = Signal(str)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.model_status: dict = {"ready": False, "running": False, "error": "Not checked yet", "models": []}
        # research scope for chat (None = whole library)
        self.scope_collections: list[int] = []
        self.scope_docs: set[int] = set()
        self.topic: str = ""
        self.year_min: int | None = None
        self.year_max: int | None = None
        # data workspace
        self.dataset = None  # LoadedDataset
        self.mapping: dict[str, str] = {}
        self.extras_mapping: dict[str, str] = {}
        self.transform_log = None
        self.derived: dict = {}  # role -> pandas Series computed on explicit request

    @property
    def pal(self) -> Palette:
        return palette(self.ctx.settings.get("ui.theme", "dark"))

    def scope_doc_ids(self) -> set[int] | None:
        """Documents in scope for retrieval, or None for the whole library."""
        ids: set[int] | None = None
        if self.scope_collections:
            ids = self.ctx.repo.doc_ids_in_collections(self.scope_collections)
        if self.scope_docs:
            ids = (ids & self.scope_docs) if ids is not None else set(self.scope_docs)
        return ids

    def mapped_frame(self):
        from ..analysis.dataset import apply_mapping

        if self.dataset is None:
            return None
        df = apply_mapping(self.dataset, self.mapping)
        for role, series in self.derived.items():
            df[role] = series.values if len(series) == len(df) else series
        return df

    def extras(self) -> dict:
        if self.dataset is None:
            return {}
        out = {}
        for role, name in self.extras_mapping.items():
            if name in self.dataset.extras:
                out[role] = self.dataset.extras[name]
            elif name in self.dataset.df.columns:
                out[role] = self.dataset.df[name].values
        return out

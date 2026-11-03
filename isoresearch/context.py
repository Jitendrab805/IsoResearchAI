"""Application context: wires settings, storage, retrieval, LLM and services.

Independent of the GUI so it can be used by tests and command-line tools.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .core import offline
from .core.db import Database
from .core.logging_setup import setup_logging
from .core.paths import AppPaths, default_data_home
from .core.repository import LibraryRepo
from .core.settings import Settings
from .ingest.importer import Importer
from .llm.ollama_client import OllamaClient
from .research.chat import ChatService
from .retrieval.search import SearchEngine

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    paths: AppPaths
    settings: Settings
    db: Database
    repo: LibraryRepo
    search: SearchEngine
    importer: Importer
    llm: OllamaClient
    chat: ChatService

    @classmethod
    def create(cls, enforce_offline: bool = True, home=None) -> "AppContext":
        paths = AppPaths(home or default_data_home()).ensure()
        setup_logging(paths.logs_dir)
        settings = Settings(paths)
        if enforce_offline:
            offline.apply(settings.strict_offline)
        db = Database(paths.database)
        search = SearchEngine(db, paths.index_dir, settings.get("retrieval.embedding_model"),
                              bool(settings.get("retrieval.use_sentence_transformers")), paths.models_dir)
        ctx = cls(paths, settings, db, LibraryRepo(db), search, None, None, None)  # type: ignore[arg-type]
        ctx.importer = ctx._make_importer()
        ctx.llm = ctx._make_llm()
        ctx.chat = ChatService(db, search, ctx.llm, settings)
        log.info("Context ready: data home set; embedder=%s", search.embedder.name)
        return ctx

    def _make_importer(self) -> Importer:
        s = self.settings
        return Importer(self.db, self.search, s.library_dir, ocr_enabled=bool(s.get("ocr.enabled")),
                        ocr_language=s.get("ocr.language", "eng"), tessdata=s.get("ocr.tessdata", ""),
                        chunk_chars=int(s.get("retrieval.chunk_chars", 1100)),
                        chunk_overlap=int(s.get("retrieval.chunk_overlap", 150)))

    def _make_llm(self) -> OllamaClient:
        s = self.settings
        return OllamaClient(s.get("llm.base_url"), s.get("llm.model", ""),
                            connect_timeout=float(s.get("llm.connect_timeout_s", 5)),
                            read_timeout=float(s.get("llm.read_timeout_s", 300)),
                            temperature=float(s.get("llm.temperature", 0.2)),
                            num_ctx=int(s.get("llm.num_ctx", 8192)),
                            require_loopback=lambda: self.settings.strict_offline)

    def reload_llm(self) -> None:
        new = self._make_llm()
        self.llm.__dict__.update(new.__dict__)  # keep the same object referenced by services

    def reload_importer(self) -> None:
        self.importer = self._make_importer()

    def reload_embedder(self) -> None:
        s = self.settings
        self.search.__init__(self.db, self.paths.index_dir, s.get("retrieval.embedding_model"),  # type: ignore[misc]
                             bool(s.get("retrieval.use_sentence_transformers")), self.paths.models_dir)
        self.importer.search = self.search

    def close(self) -> None:
        self.db.close()

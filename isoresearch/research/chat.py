"""Retrieval-augmented, citation-checked research chat with persistent history."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from ..core.db import Database, dumps, loads
from ..core.repository import Chunk, LibraryRepo
from ..llm.ollama_client import OllamaClient
from ..llm.prompts import format_sources, system_prompt
from ..retrieval.search import SearchEngine, SearchFilters
from .citations import CitationReport, references_markdown, validate

log = logging.getLogger(__name__)

FOLLOWUP_HINT = re.compile(r"^(and|but|so|what about|how about|why|explain|more|it|this|that|they|those|these)\b",
                           re.I)


class ConversationStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, title: str = "New research chat", scope: dict | None = None) -> int:
        now = time.time()
        return self.db.execute("INSERT INTO conversations(title, scope_json, created_at, updated_at) VALUES (?,?,?,?)",
                               (title, dumps(scope or {}), now, now))

    def list(self, search: str = "") -> list[dict]:
        if search:
            like = f"%{search}%"
            rows = self.db.query(
                "SELECT DISTINCT c.* FROM conversations c LEFT JOIN messages m ON m.conv_id=c.id "
                "WHERE c.title LIKE ? OR m.content LIKE ? ORDER BY c.updated_at DESC", (like, like))
        else:
            rows = self.db.query("SELECT * FROM conversations ORDER BY updated_at DESC")
        out = []
        for r in rows:
            d = dict(r)
            d["n_messages"] = self.db.one("SELECT COUNT(*) FROM messages WHERE conv_id=?", (r["id"],))[0]
            out.append(d)
        return out

    def get(self, cid: int) -> dict | None:
        r = self.db.one("SELECT * FROM conversations WHERE id=?", (cid,))
        return dict(r) if r else None

    def messages(self, cid: int) -> list[dict]:
        out = []
        for r in self.db.query("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (cid,)):
            d = dict(r)
            d["citations"] = loads(d.pop("citations_json"), [])
            out.append(d)
        return out

    def add(self, cid: int, role: str, content: str, citations: list[dict] | None = None,
            model: str = "") -> int:
        now = time.time()
        mid = self.db.execute("INSERT INTO messages(conv_id, role, content, citations_json, model, created_at) "
                              "VALUES (?,?,?,?,?,?)", (cid, role, content, dumps(citations or []), model, now))
        self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, cid))
        return mid

    def rename(self, cid: int, title: str) -> None:
        self.db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title.strip()[:200], time.time(), cid))

    def set_scope(self, cid: int, scope: dict) -> None:
        self.db.execute("UPDATE conversations SET scope_json=? WHERE id=?", (dumps(scope), cid))

    def delete(self, cid: int) -> None:
        self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))

    def export(self, cid: int, fmt: str = "md") -> str:
        conv = self.get(cid) or {"title": "Conversation"}
        lines = [f"# {conv['title']}" if fmt == "md" else conv["title"], ""]
        for m in self.messages(cid):
            who = {"user": "You", "assistant": "IsoResearch AI"}.get(m["role"], m["role"])
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["created_at"]))
            lines.append(f"## {who} — {stamp}" if fmt == "md" else f"[{who} — {stamp}]")
            lines.append(m["content"])
            lines.append("")
        text = "\n".join(lines)
        if fmt == "txt":
            text = re.sub(r"\*\*|__|`{1,3}|^#+\s*", "", text, flags=re.M)
        return text


@dataclass
class PreparedTurn:
    conv_id: int
    question: str
    sources: list[Chunk]
    messages: list[dict]
    insufficient: bool
    filters: SearchFilters | None = None
    notes: list[str] = field(default_factory=list)


class ChatService:
    def __init__(self, db: Database, search: SearchEngine, llm: OllamaClient, settings):
        self.db = db
        self.store = ConversationStore(db)
        self.repo = LibraryRepo(db)
        self.search = search
        self.llm = llm
        self.settings = settings

    # ------------------------------------------------------------ prepare
    def _previous_sources(self, cid: int, limit: int = 4) -> list[int]:
        for m in reversed(self.store.messages(cid)):
            if m["role"] == "assistant" and m["citations"]:
                used = [c for c in m["citations"] if c.get("used")]
                return [c["chunk_id"] for c in (used or m["citations"])][:limit]
        return []

    def prepare(self, cid: int, question: str, filters: SearchFilters | None = None,
                topic: str = "", history_turns: int = 6) -> PreparedTurn:
        history = [m for m in self.store.messages(cid) if m["role"] in ("user", "assistant")]
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        query = question
        notes = []
        if last_user and (len(question.split()) < 8 or FOLLOWUP_HINT.match(question.strip())):
            query = f"{last_user}\n{question}"  # follow-up: carry previous topic into retrieval
            notes.append("Follow-up detected: retrieval also used your previous question.")
        if topic:
            query += f"\n{topic}"
        k = int(self.settings.get("retrieval.top_k", 8))
        hits = self.search.hybrid(query, k=k, filters=filters)
        ids = {h.id for h in hits}
        allowed = filters.doc_ids if filters else None
        carry = [c for c in self.repo.chunks_by_ids(self._previous_sources(cid))
                 if c.id not in ids and (allowed is None or c.doc_id in allowed)]
        if carry:
            notes.append(f"Kept {len(carry)} passage(s) cited in the previous answer for context.")
        sources = hits + carry[: max(0, k + 3 - len(hits))]

        msgs = [{"role": "system", "content": system_prompt(self.settings.profile, topic)}]
        for m in history[-history_turns * 2:]:
            content = m["content"].split("\n\n**Sources (local library)**")[0]
            msgs.append({"role": m["role"], "content": content[:4000]})
        msgs.append({"role": "user", "content": f"{format_sources(sources)}\n\nQUESTION: {question}"})
        return PreparedTurn(cid, question, sources, msgs, insufficient=not sources, filters=filters, notes=notes)

    # ------------------------------------------------------------- answer
    def stream(self, turn: PreparedTurn, cancel: threading.Event | None = None) -> Iterator[str]:
        """Yield model tokens.  Raises LLM errors — never yields made-up text."""
        yield from self.llm.chat_stream(turn.messages, cancel=cancel)

    def finalize(self, turn: PreparedTurn, raw_answer: str, save_user: bool = True) -> tuple[str, CitationReport]:
        report = validate(raw_answer, turn.sources)
        text = report.text
        if turn.insufficient:
            text = ("> ⚠ **No relevant passages were found in the selected library scope.** "
                    "Anything below is general background, not literature evidence.\n\n" + text)
        elif report.uncited:
            text += ("\n\n> ⚠ This answer contains no citations to the retrieved passages. "
                     "Treat its claims as unverified interpretation.")
        if report.invalid:
            text += (f"\n\n> ⚠ Removed invalid citation marker(s) {', '.join(report.invalid)} "
                     "that did not match any provided source.")
        text += references_markdown(report)
        cits = []
        for c in report.citations:
            d = c.to_dict()
            d["used"] = c.n in report.used
            cits.append(d)
        if save_user:
            self.store.add(turn.conv_id, "user", turn.question)
        self.store.add(turn.conv_id, "assistant", text, cits, model=self.llm.model)
        conv = self.store.get(turn.conv_id)
        if conv and conv["title"] == "New research chat":
            self.store.rename(turn.conv_id, turn.question[:70])
        return text, report

    def ask(self, cid: int, question: str, filters: SearchFilters | None = None, topic: str = "",
            cancel: threading.Event | None = None) -> tuple[str, CitationReport]:
        """Blocking convenience wrapper (used by tests and batch tools)."""
        turn = self.prepare(cid, question, filters, topic)
        raw = "".join(self.stream(turn, cancel))
        return self.finalize(turn, raw)

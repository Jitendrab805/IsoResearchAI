"""SQLite storage with versioned migrations.

* One connection per thread (background workers get their own).
* WAL journal so the GUI can read while a worker writes.
* All queries are parameterized — never string-formatted with user data.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

log = logging.getLogger(__name__)

# Each migration is applied once, in order.  Never edit a released migration;
# append a new one instead.
MIGRATIONS: list[str] = [
    # ---- v1: core schema
    """
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY,
        sha256 TEXT NOT NULL UNIQUE,
        filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        display_label TEXT,
        title TEXT, authors TEXT, year INTEGER, journal TEXT, doi TEXT,
        page_count INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',      -- pending|processing|indexed|no_text|failed
        status_detail TEXT,
        is_scanned INTEGER DEFAULT 0,
        ocr_used INTEGER DEFAULT 0,
        metadata_json TEXT DEFAULT '{}',
        imported_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE collections (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT DEFAULT '',
        created_at REAL NOT NULL
    );
    CREATE TABLE document_collections (
        doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        PRIMARY KEY (doc_id, collection_id)
    );
    CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
    CREATE TABLE document_tags (
        doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (doc_id, tag_id)
    );
    CREATE TABLE chunks (
        id INTEGER PRIMARY KEY,
        doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page INTEGER NOT NULL,
        section TEXT,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL
    );
    CREATE INDEX idx_chunks_doc ON chunks(doc_id);
    CREATE VIRTUAL TABLE chunks_fts USING fts5(
        text, section, content='chunks', content_rowid='id', tokenize='unicode61'
    );
    CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, text, section) VALUES (new.id, new.text, new.section);
    END;
    CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, section) VALUES('delete', old.id, old.text, old.section);
    END;
    CREATE TABLE import_log (
        id INTEGER PRIMARY KEY, path TEXT, sha256 TEXT, doc_id INTEGER,
        status TEXT NOT NULL, message TEXT, created_at REAL NOT NULL
    );
    CREATE TABLE conversations (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, scope_json TEXT DEFAULT '{}',
        created_at REAL NOT NULL, updated_at REAL NOT NULL
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY,
        conv_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL, content TEXT NOT NULL,
        citations_json TEXT DEFAULT '[]', model TEXT, created_at REAL NOT NULL
    );
    CREATE TABLE paper_reviews (
        doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        fields_json TEXT NOT NULL DEFAULT '{}',
        updated_at REAL NOT NULL
    );
    CREATE TABLE gaps (
        id INTEGER PRIMARY KEY, created_at REAL NOT NULL,
        kind TEXT NOT NULL,                -- explicit|inferred|combination
        title TEXT NOT NULL, description TEXT, why_matters TEXT, hypothesis TEXT,
        questions_json TEXT DEFAULT '[]', supporting_json TEXT DEFAULT '[]',
        needed TEXT, confidence TEXT, status TEXT NOT NULL DEFAULT 'provisional'
    );
    CREATE TABLE datasets (
        id INTEGER PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
        sha256 TEXT, mapping_json TEXT DEFAULT '{}', imported_at REAL NOT NULL
    );
    CREATE TABLE transform_log (
        id INTEGER PRIMARY KEY, dataset_id INTEGER REFERENCES datasets(id) ON DELETE CASCADE,
        action TEXT NOT NULL, params_json TEXT DEFAULT '{}', created_at REAL NOT NULL
    );
    CREATE TABLE figures (
        id INTEGER PRIMARY KEY, title TEXT, plot_type TEXT, folder TEXT NOT NULL,
        config_json TEXT DEFAULT '{}', created_at REAL NOT NULL
    );
    """,
    # ---- v2: user notes on documents + helpful indexes
    """
    ALTER TABLE documents ADD COLUMN notes TEXT DEFAULT '';
    CREATE INDEX idx_messages_conv ON messages(conv_id);
    CREATE INDEX idx_documents_status ON documents(status);
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.migrate()

    # --------------------------------------------------------- connection
    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False,
                                   isolation_level=None)  # explicit transactions only
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        with self._write_lock:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.connect().execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.connect().execute(sql, tuple(params)).fetchone()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, tuple(params))
            return cur.lastrowid or cur.rowcount

    # ---------------------------------------------------------- migrations
    def schema_version(self) -> int:
        return int(self.connect().execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        conn = self.connect()
        current = self.schema_version()
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            log.info("Applying database migration v%d", version)
            with self._write_lock:
                conn.executescript("BEGIN;\n" + script + f"\nPRAGMA user_version = {version};\nCOMMIT;")
        if not self.one("SELECT 1 FROM collections WHERE name = ?", ("All papers",)):
            self.execute("INSERT INTO collections(name, description, created_at) VALUES (?,?,?)",
                         ("All papers", "Default collection", time.time()))


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default

# Architecture

```
isoresearch/
├── app.py                 entry point (QApplication, error handling, --smoke-test)
├── context.py             AppContext: wires settings, DB, search, importer, LLM, chat (GUI-independent)
├── core/
│   ├── paths.py           data-home locations (%APPDATA%\IsoResearchAI, ISORESEARCH_HOME override)
│   ├── settings.py        JSON settings + default research profile (atomic writes)
│   ├── db.py              SQLite (WAL, per-thread connections, versioned migrations, FTS5)
│   ├── repository.py      documents / collections / tags / chunks data access (parameterised SQL)
│   ├── offline.py         strict offline guard (socket connect + DNS patch, loopback only)
│   └── logging_setup.py   rotating JSON-lines logs, no private content
├── ingest/
│   ├── pdf_extract.py     PyMuPDF text + headings + page numbers, scanned detection, local Tesseract OCR,
│   │                      metadata/DOI/year guesses with confidence
│   ├── chunker.py         section-aware chunks that never cross a page (exact page citations)
│   └── importer.py        SHA-256 dedupe, copy to library, status tracking, never drops documents
├── retrieval/
│   ├── embeddings.py      sentence-transformers (local files only) or built-in lexical-hash embedder
│   ├── vector_index.py    persisted FAISS IndexIDMap2 (NumPy fallback), auto-rebuild on mismatch
│   └── search.py          BM25 (FTS5), vector search, hybrid (reciprocal-rank fusion), scope/year filters
├── llm/
│   ├── ollama_client.py   localhost-only client: status, streaming chat, cancel, timeouts, optional pull
│   └── prompts.py         domain/system prompt, evidence rules, untrusted <source> wrapping
├── research/
│   ├── citations.py       [S#] validation and reference lists
│   ├── chat.py            conversations (SQLite) + retrieval-augmented, follow-up-aware chat
│   ├── literature.py      structured records with confidence, comparison tables, themed drafts
│   └── gaps.py            explicit / combination / inferred gaps, evidence-based confidence
├── analysis/dataset.py    CSV/Excel/NetCDF loading, role detection, QC, transformation log
├── plotting/
│   ├── catalog.py         plot advisor knowledge base + data-support checks
│   ├── recipes.py         self-contained plotting functions (also copied into exported scripts)
│   └── render.py          render, export PNG/SVG/PDF + script + config
├── export/                Markdown/DOCX/CSV/XLSX/BibTeX/RIS writers, backup/restore/delete
└── ui/                    PySide6 GUI: theme, bundled SVG icons, background workers, pages, PDF viewer
```

## Threads
Long work (imports, OCR, indexing, generation, literature extraction, gap analysis, dataset loading, plot
rendering, backups) runs in `QThreadPool` workers (`ui/workers.py`). Workers report progress/tokens through Qt
signals and observe a cancellation event. SQLite uses one connection per thread and WAL mode so the GUI can
read while a worker writes. A test measures event-loop latency during a 25-PDF import.

## Data flow of a chat turn
1. `ChatService.prepare` builds the retrieval query (adds the previous question for short follow-ups and the
   active topic), runs hybrid search within the selected scope, adds passages cited in the previous answer.
2. Messages = system prompt (domain, evidence rules, research profile) + recent history + numbered `<source>`
   blocks + question.
3. Tokens stream from Ollama (`/api/chat`); the Stop button sets the cancel event.
4. `finalize` validates `[S#]` markers against the passages actually sent, flags invalid/uncited content,
   appends a reference list and stores the message with citation metadata (doc id, page, section, excerpt).

## Database migrations
`core/db.py::MIGRATIONS` is an append-only list; `PRAGMA user_version` records the applied version. Add a new
string to the list for schema changes — never edit a released one.

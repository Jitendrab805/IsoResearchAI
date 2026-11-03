"""Structured, privacy-conscious logging.

Logs go to ``<data home>/logs/isoresearch.log`` as JSON lines (rotated).  Code
in this project logs identifiers, counts and error types — never full paper
text, prompts or model answers.  ``redact`` truncates any free text that must
be mentioned.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def redact(text: str, keep: int = 40) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= keep else f"{text[:keep]}… [{len(text)} chars]"


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_isoresearch", False):
            root.removeHandler(h)
    fh = logging.handlers.RotatingFileHandler(
        logs_dir / "isoresearch.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    fh._isoresearch = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    if sys.stderr is not None:  # pythonw.exe (no console) has no stderr
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        sh._isoresearch = True  # type: ignore[attr-defined]
        root.addHandler(sh)
    root.setLevel(level)
    for noisy in ("urllib3", "matplotlib", "PIL", "sentence_transformers", "faiss", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def close_file_logs() -> None:
    """Release the log file (needed on Windows before deleting the logs folder)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_isoresearch", False):
            h.close()
            root.removeHandler(h)

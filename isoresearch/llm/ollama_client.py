"""Minimal Ollama client — localhost API only.

* Refuses any base URL that is not loopback while strict offline mode is on.
* Streams tokens from ``/api/chat``; generation can be cancelled at any time.
* Never fabricates output: on any failure it raises ``LLMUnavailable`` /
  ``LLMError`` and the caller shows an actionable message instead.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import dataclass
from typing import Callable, Iterator

import requests

from ..core import offline

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMCancelled(LLMError):
    pass


@dataclass
class ModelInfo:
    name: str
    size_bytes: int = 0
    parameter_size: str = ""
    quantization: str = ""
    family: str = ""

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1e9


SUGGESTED_MODELS = [
    # (name, approx download, note) — sizes are approximate and change between releases.
    ("llama3.1:8b", "≈4.9 GB", "Good general quality; comfortable with 16 GB RAM or 8 GB VRAM."),
    ("qwen2.5:7b", "≈4.7 GB", "Strong at structured/JSON output used by the literature extractor."),
    ("mistral:7b", "≈4.1 GB", "Fast, solid general model."),
    ("llama3.2:3b", "≈2.0 GB", "For laptops with 8 GB RAM; lower quality."),
    ("qwen2.5:14b", "≈9 GB", "Better reasoning; needs ~16–32 GB RAM or a 12 GB+ GPU."),
]


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "",
                 connect_timeout: float = 5, read_timeout: float = 300,
                 temperature: float = 0.2, num_ctx: int = 8192,
                 require_loopback: Callable[[], bool] = lambda: True):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.temperature = temperature
        self.num_ctx = num_ctx
        self._require_loopback = require_loopback
        self._session = requests.Session()
        self._session.trust_env = False  # never route localhost traffic via system proxies

    # ----------------------------------------------------------- helpers
    def _url(self, path: str) -> str:
        if self._require_loopback() and not offline.is_loopback_url(self.base_url):
            raise LLMUnavailable(
                f"Strict offline mode only allows a local (loopback) Ollama address; "
                f"'{self.base_url}' is not local. Change it in Settings → AI model.")
        return f"{self.base_url}{path}"

    @staticmethod
    def installed() -> bool:
        return shutil.which("ollama") is not None

    def _get(self, path: str, timeout: float | None = None) -> dict:
        try:
            r = self._session.get(self._url(path), timeout=(self.connect_timeout, timeout or self.connect_timeout))
        except requests.ConnectionError as exc:
            raise LLMUnavailable("Ollama is not running at " + self.base_url +
                                 ". Start the Ollama app (or run `ollama serve`) and try again.") from exc
        except requests.Timeout as exc:
            raise LLMUnavailable("Ollama did not respond in time.") from exc
        if r.status_code != 200:
            raise LLMError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    # -------------------------------------------------------------- api
    def is_running(self) -> bool:
        try:
            self._get("/api/version")
            return True
        except LLMError:
            return False

    def version(self) -> str:
        return self._get("/api/version").get("version", "?")

    def list_models(self) -> list[ModelInfo]:
        data = self._get("/api/tags")
        out = []
        for m in data.get("models", []):
            det = m.get("details") or {}
            out.append(ModelInfo(m.get("name") or m.get("model", "?"), int(m.get("size") or 0),
                                 det.get("parameter_size", ""), det.get("quantization_level", ""),
                                 det.get("family", "")))
        return out

    def status(self) -> dict:
        """Verified status for the UI.  ``ready`` is True only when a real
        round-trip to the local service succeeded and the model exists."""
        st = {"installed": self.installed(), "running": False, "version": "", "models": [],
              "model": self.model, "model_available": False, "ready": False, "error": ""}
        try:
            st["version"] = self.version()
            st["running"] = True
            st["models"] = [m.name for m in self.list_models()]
            st["model_available"] = bool(self.model) and (
                self.model in st["models"] or f"{self.model}:latest" in st["models"])
            st["ready"] = st["model_available"]
            if not self.model:
                st["error"] = "No model selected."
            elif not st["model_available"]:
                st["error"] = f"Model '{self.model}' is not downloaded in Ollama."
        except LLMError as exc:
            st["error"] = str(exc)
        return st

    def chat_stream(self, messages: list[dict], cancel: threading.Event | None = None,
                    options: dict | None = None, fmt: str | None = None) -> Iterator[str]:
        if not self.model:
            raise LLMUnavailable("No local model is selected. Choose one in Settings → AI model.")
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "options": {"temperature": self.temperature, "num_ctx": self.num_ctx, **(options or {})}}
        if fmt:
            payload["format"] = fmt
        try:
            resp = self._session.post(self._url("/api/chat"), json=payload, stream=True,
                                      timeout=(self.connect_timeout, self.read_timeout))
        except requests.ConnectionError as exc:
            raise LLMUnavailable("Could not reach the local Ollama service at " + self.base_url +
                                 ". Is Ollama running?") from exc
        except requests.Timeout as exc:
            raise LLMUnavailable("The local model did not start responding before the timeout.") from exc
        with resp:
            if resp.status_code == 404:
                raise LLMUnavailable(f"Model '{self.model}' was not found in Ollama. "
                                     f"Download it with: ollama pull {self.model}")
            if resp.status_code != 200:
                raise LLMError(f"Ollama error HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if cancel is not None and cancel.is_set():
                        raise LLMCancelled("Generation stopped by user.")
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise LLMError(f"Model error: {data['error']}")
                    piece = (data.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
            except requests.exceptions.ChunkedEncodingError as exc:
                raise LLMError("The connection to Ollama was interrupted during generation.") from exc
            except requests.Timeout as exc:
                raise LLMError("The local model stopped responding (read timeout). "
                               "Try a smaller model or increase the timeout in Settings.") from exc

    def chat(self, messages: list[dict], cancel: threading.Event | None = None,
             options: dict | None = None, fmt: str | None = None) -> str:
        return "".join(self.chat_stream(messages, cancel, options, fmt))

    def test_connection(self) -> str:
        """Short real generation round-trip."""
        txt = self.chat([{"role": "user", "content": "Reply with exactly: OK"}],
                        options={"num_predict": 8, "temperature": 0})
        return txt.strip()

    def pull(self, name: str, progress: Callable[[str, float], None] | None = None,
             cancel: threading.Event | None = None) -> None:
        """Ask the local Ollama service to download a model.

        This is an *optional online feature*: the download is performed by the
        Ollama service (a separate program), and the UI only calls this after the
        user has explicitly approved it with online features enabled."""
        resp = self._session.post(self._url("/api/pull"), json={"name": name, "stream": True}, stream=True,
                                  timeout=(self.connect_timeout, 3600))
        with resp:
            if resp.status_code != 200:
                raise LLMError(f"Pull failed: HTTP {resp.status_code} {resp.text[:200]}")
            for line in resp.iter_lines(decode_unicode=True):
                if cancel is not None and cancel.is_set():
                    raise LLMCancelled("Download cancelled.")
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise LLMError(d["error"])
                frac = (d.get("completed", 0) / d["total"]) if d.get("total") else 0.0
                if progress:
                    progress(d.get("status", ""), frac)

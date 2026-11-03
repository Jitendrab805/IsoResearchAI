"""User-editable settings, stored as JSON in the data home (never in code).

Settings are a nested dictionary merged over ``DEFAULTS``; unknown keys from
older/newer versions are preserved.  Writes are atomic (temp file + replace).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .paths import AppPaths

log = logging.getLogger(__name__)

DEFAULT_PROFILE = {
    "research_area": "Water isotope hydrology and isotope-enabled regional atmospheric modelling.",
    "primary_location": "Port Blair, Andaman and Nicobar Islands, India.",
    "primary_observations": "Rainfall water isotopes from 2024–2026, including δ18O, δ2H, and derived d-excess when available.",
    "modelling_interests": "Isotope-enabled regional modelling, especially IsoRSM, with alternative models considered when appropriate.",
    "related_observations": "Rainfall amount, rainfall intensity, event evolution, meteorological variables, moisture transport, and back trajectories where available.",
    "scientific_objective": "Evaluate simulated rainfall isotope variability against observations, investigate physical processes controlling isotope variability, and identify defensible research questions.",
}

DEFAULTS: dict[str, Any] = {
    "ui": {"theme": "dark", "font_scale": 1.0},
    "storage": {"library_dir": ""},  # empty -> <data home>/library
    "privacy": {
        # Strict offline: block every application-initiated non-loopback connection.
        "strict_offline": True,
        # Optional online features (currently: asking Ollama to download a model).
        "allow_online_features": False,
    },
    "llm": {
        "backend": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "",
        "temperature": 0.2,
        "num_ctx": 8192,
        "connect_timeout_s": 5,
        "read_timeout_s": 300,
    },
    "retrieval": {
        # Name or local folder of a sentence-transformers model.  If it cannot be
        # loaded from local files, the built-in lexical-hash embedder is used.
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "use_sentence_transformers": True,
        "top_k": 8,
        "chunk_chars": 1100,
        "chunk_overlap": 150,
        "min_score": 0.0,
    },
    "ocr": {"enabled": True, "language": "eng", "tessdata": ""},
    "profile": copy.deepcopy(DEFAULT_PROFILE),
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        f = self.paths.settings_file
        if f.exists():
            try:
                self._data = _deep_merge(DEFAULTS, json.loads(f.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                log.error("Settings file unreadable (%s); using defaults. A copy was kept.", exc)
                try:
                    f.replace(f.with_suffix(".corrupt.json"))
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        with self._lock:
            self.paths.home.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.paths.home, prefix=".settings", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.paths.settings_file)

    # ------------------------------------------------------------- access
    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return copy.deepcopy(cur)

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            cur = self._data
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = value
        if save:
            self.save()

    def as_dict(self) -> dict:
        return copy.deepcopy(self._data)

    # --------------------------------------------------------- shortcuts
    @property
    def library_dir(self) -> Path:
        p = self.get("storage.library_dir") or ""
        path = Path(p).expanduser() if p else self.paths.default_library
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def strict_offline(self) -> bool:
        return bool(self.get("privacy.strict_offline", True))

    @property
    def profile(self) -> dict:
        return self.get("profile", {})

"""Resolve local storage locations.

Everything the application stores lives under a single *data home* directory:

* Windows:  %APPDATA%\\IsoResearchAI
* macOS:    ~/Library/Application Support/IsoResearchAI
* Linux:    $XDG_DATA_HOME/IsoResearchAI or ~/.local/share/IsoResearchAI

Set the ``ISORESEARCH_HOME`` environment variable to override it (used by the
test-suite and for portable installs).  The PDF library directory itself is
configurable in Settings and may live elsewhere.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_data_home() -> Path:
    env = os.environ.get("ISORESEARCH_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "IsoResearchAI").resolve()


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @property
    def settings_file(self) -> Path:
        return self.home / "settings.json"

    @property
    def database(self) -> Path:
        return self.home / "isoresearch.sqlite3"

    @property
    def default_library(self) -> Path:
        return self.home / "library"

    @property
    def index_dir(self) -> Path:
        return self.home / "index"

    @property
    def figures_dir(self) -> Path:
        return self.home / "figures"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def models_dir(self) -> Path:
        """Optional location for locally stored embedding models."""
        return self.home / "models"

    def ensure(self) -> "AppPaths":
        for p in (self.home, self.default_library, self.index_dir, self.figures_dir,
                  self.exports_dir, self.logs_dir, self.backups_dir, self.models_dir):
            p.mkdir(parents=True, exist_ok=True)
        return self


def resource_path(*parts: str) -> Path:
    """Path to bundled resources (works from source and from a PyInstaller build)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    if getattr(sys, "_MEIPASS", None):
        base = Path(sys._MEIPASS) / "isoresearch"  # type: ignore[attr-defined]
    return base.joinpath("resources", *parts)

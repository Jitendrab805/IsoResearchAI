"""Backup, restore and secure-ish deletion of local research data.

Backups are plain ZIP files containing the database (consistent snapshot via
SQLite's backup API), settings, vector index, figures and — optionally — the
PDF library.  Nothing leaves the computer unless the user moves the file.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from .. import __version__


def create_backup(paths, settings, dest: Path, include_pdfs: bool = True, progress=None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "isoresearch.sqlite3"
        src = sqlite3.connect(paths.database)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({"app": "IsoResearch AI", "version": __version__,
                                                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                    "include_pdfs": include_pdfs}))
            z.write(snap, "isoresearch.sqlite3")
            if paths.settings_file.exists():
                z.write(paths.settings_file, "settings.json")
            folders = [("index", paths.index_dir), ("figures", paths.figures_dir)]
            if include_pdfs:
                folders.append(("library", settings.library_dir))
            files = [(name, f, base) for name, base in folders if base.exists()
                     for f in base.rglob("*") if f.is_file()]
            for i, (name, f, base) in enumerate(files):
                z.write(f, f"{name}/{f.relative_to(base).as_posix()}")
                if progress:
                    progress(i + 1, len(files))
    return dest


def restore_backup(paths, settings, archive: Path) -> dict:
    """Restore into the current data home.  The caller must close the DB first
    and confirm with the user (this replaces current data)."""
    archive = Path(archive)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if "manifest.json" not in names or "isoresearch.sqlite3" not in names:
            raise ValueError("This file is not an IsoResearch AI backup.")
        manifest = json.loads(z.read("manifest.json"))
        for n in names:  # zip-slip protection
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Unsafe path in archive: {n}")
        safety = paths.backups_dir / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
        if paths.database.exists():
            shutil.copy2(paths.database, safety)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(paths.database) + suffix)
            if p.exists() and suffix:
                p.unlink()
        with z.open("isoresearch.sqlite3") as src, open(paths.database, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if "settings.json" in names:
            paths.settings_file.write_bytes(z.read("settings.json"))
        targets = {"index/": paths.index_dir, "figures/": paths.figures_dir, "library/": settings.library_dir}
        for n in names:
            for prefix, base in targets.items():
                if n.startswith(prefix) and not n.endswith("/"):
                    out = base / n[len(prefix):]
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    # stored PDF paths may differ if the library folder moved
    con = sqlite3.connect(paths.database)
    lib = settings.library_dir
    for doc_id, stored in con.execute("SELECT id, stored_path FROM documents").fetchall():
        candidate = lib / Path(stored).name
        if candidate.exists() and str(candidate) != stored:
            con.execute("UPDATE documents SET stored_path=? WHERE id=?", (str(candidate), doc_id))
    con.commit()
    con.close()
    manifest["safety_copy"] = str(safety)
    return manifest


def delete_all_data(paths, settings, include_library: bool = True) -> list[str]:
    """Delete local research data.  Settings file is kept unless the home is removed."""
    from ..core.logging_setup import close_file_logs

    close_file_logs()
    removed = []
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(paths.database) + suffix)
        if p.exists():
            p.unlink()
            removed.append(p.name)
    for d in [paths.index_dir, paths.figures_dir, paths.exports_dir, paths.logs_dir] + (
            [settings.library_dir] if include_library else []):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(str(d))
            d.mkdir(parents=True, exist_ok=True)
    return removed

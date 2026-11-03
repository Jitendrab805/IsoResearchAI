"""Persisted local vector index (FAISS inner-product; NumPy fallback).

The index records which embedder built it.  If the embedder changes or the
files are missing/corrupt, ``needs_rebuild`` is true and the app rebuilds it
from the chunks stored in SQLite.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

try:
    import faiss  # type: ignore

    HAVE_FAISS = True
except Exception:  # noqa: BLE001
    faiss = None
    HAVE_FAISS = False


class VectorIndex:
    def __init__(self, folder: Path, embedder_name: str, dim: int):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.embedder_name = embedder_name
        self.dim = dim
        self._lock = threading.RLock()
        self.needs_rebuild = False
        self._ids = np.zeros(0, dtype=np.int64)
        self._vecs = np.zeros((0, dim), dtype=np.float32)
        self._faiss = None
        self._load()

    @property
    def meta_file(self) -> Path:
        return self.folder / "index_meta.json"

    @property
    def data_file(self) -> Path:
        return self.folder / ("vectors.faiss" if HAVE_FAISS else "vectors.npz")

    def __len__(self) -> int:
        return int(self._faiss.ntotal) if self._faiss is not None else len(self._ids)

    # ---------------------------------------------------------------- io
    def _new_faiss(self):
        return faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    def _load(self) -> None:
        with self._lock:
            if HAVE_FAISS:
                self._faiss = self._new_faiss()
            meta = {}
            if self.meta_file.exists():
                try:
                    meta = json.loads(self.meta_file.read_text())
                except json.JSONDecodeError:
                    meta = {}
            if not self.data_file.exists():
                self.needs_rebuild = bool(meta)  # meta without data → corrupt
                return
            if meta.get("embedder") != self.embedder_name or meta.get("dim") != self.dim:
                log.info("Vector index built with a different embedder; rebuild required.")
                self.needs_rebuild = True
                return
            try:
                if HAVE_FAISS:
                    self._faiss = faiss.read_index(str(self.data_file))
                else:
                    z = np.load(self.data_file)
                    self._ids, self._vecs = z["ids"], z["vecs"]
            except Exception as exc:  # noqa: BLE001
                log.error("Vector index unreadable (%s); rebuild required.", type(exc).__name__)
                self.needs_rebuild = True
                if HAVE_FAISS:
                    self._faiss = self._new_faiss()

    def save(self) -> None:
        with self._lock:
            tmp = self.data_file.with_suffix(".tmp")
            if HAVE_FAISS:
                faiss.write_index(self._faiss, str(tmp))
            else:
                with open(tmp, "wb") as fh:
                    np.savez(fh, ids=self._ids, vecs=self._vecs)
            tmp.replace(self.data_file)
            self.meta_file.write_text(json.dumps({"embedder": self.embedder_name, "dim": self.dim,
                                                  "count": len(self), "faiss": HAVE_FAISS}))

    # ------------------------------------------------------------ mutate
    def clear(self) -> None:
        with self._lock:
            if HAVE_FAISS:
                self._faiss = self._new_faiss()
            self._ids = np.zeros(0, dtype=np.int64)
            self._vecs = np.zeros((0, self.dim), dtype=np.float32)
            self.needs_rebuild = False

    def add(self, ids: list[int], vecs: np.ndarray) -> None:
        if not ids:
            return
        vecs = np.ascontiguousarray(vecs, dtype=np.float32)
        arr = np.asarray(ids, dtype=np.int64)
        with self._lock:
            if HAVE_FAISS:
                self._faiss.add_with_ids(vecs, arr)
            else:
                self._ids = np.concatenate([self._ids, arr])
                self._vecs = np.vstack([self._vecs, vecs])

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        arr = np.asarray(ids, dtype=np.int64)
        with self._lock:
            if HAVE_FAISS:
                self._faiss.remove_ids(arr)
            else:
                keep = ~np.isin(self._ids, arr)
                self._ids, self._vecs = self._ids[keep], self._vecs[keep]

    # ------------------------------------------------------------- query
    def search(self, vec: np.ndarray, k: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        with self._lock:
            n = len(self)
            if n == 0:
                return []
            q = np.ascontiguousarray(vec.reshape(1, -1), dtype=np.float32)
            kk = n if allowed is not None else min(k, n)
            if HAVE_FAISS:
                if allowed is not None:
                    sel = faiss.IDSelectorBatch(np.asarray(sorted(allowed), dtype=np.int64))
                    params = faiss.SearchParameters(sel=sel)
                    scores, ids = self._faiss.search(q, min(k, n), params=params)
                else:
                    scores, ids = self._faiss.search(q, kk)
                return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]
            scores = self._vecs @ q[0]
            order = np.argsort(-scores)
            out = []
            for j in order:
                cid = int(self._ids[j])
                if allowed is None or cid in allowed:
                    out.append((cid, float(scores[j])))
                    if len(out) >= k:
                        break
            return out

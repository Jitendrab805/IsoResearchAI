"""Local text embeddings.

Preferred: a sentence-transformers model loaded **from local files only**
(``local_files_only=True``).  Install it once during setup with
``scripts/download_embedding_model.py`` (this step needs internet) or point
Settings → Retrieval to a folder that already contains the model.

Fallback: ``HashingEmbedder`` — a deterministic lexical embedding (hashed
word uni/bi-grams + character trigrams, TF-weighted, L2-normalised).  It needs
no download and works fully offline, but it captures *lexical* similarity, not
deep semantics.  The UI states which embedder is active.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-zα-ωδ0-9]+(?:[-'][a-z0-9]+)*", re.I)
STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were
which with we our these those their than then also can may into between using used based both such
not but however there been more most other each all any per via""".split())

# isotope notation normalisation so "δ18O", "delta 18O", "d18O" match
NORMALISE = [
    (re.compile(r"(δ|delta\s*|\bd)\s*18\s*o\b", re.I), " d18o "),
    (re.compile(r"(δ|delta\s*|\bd)\s*(2|d)\s*h\b|δd\b|delta\s*d\b", re.I), " d2h "),
    (re.compile(r"d[- ]?excess|deuterium excess", re.I), " dexcess "),
    (re.compile(r"17\s*o[- ]?excess", re.I), " o17excess "),
]


def normalise(text: str) -> str:
    for pat, rep in NORMALISE:
        text = pat.sub(rep, text)
    return text


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(normalise(text)) if t.lower() not in STOP and len(t) > 1]


class Embedder(Protocol):
    name: str
    dim: int
    semantic: bool

    def encode(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    semantic = False

    def __init__(self, dim: int = 768):
        self.dim = dim
        self.name = f"lexical-hash-{dim}"

    def _h(self, s: str) -> int:
        return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = tokenize(t)
            feats: dict[int, float] = {}
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                h = self._h(g)
                idx, sign = h % self.dim, (1.0 if (h >> 32) & 1 else -1.0)
                feats[idx] = feats.get(idx, 0.0) + sign
            for tok in toks:
                if len(tok) >= 5:
                    for k in range(len(tok) - 2):
                        h = self._h("#" + tok[k:k + 3])
                        idx = h % self.dim
                        feats[idx] = feats.get(idx, 0.0) + 0.3 * (1.0 if (h >> 32) & 1 else -1.0)
            for idx, v in feats.items():
                out[i, idx] = math.copysign(1 + math.log(abs(v)), v) if v else 0.0
            n = np.linalg.norm(out[i])
            if n > 0:
                out[i] /= n
        return out


class SentenceTransformerEmbedder:
    semantic = True

    def __init__(self, model_name_or_path: str, cache_dir: Path | None = None):
        from sentence_transformers import SentenceTransformer  # optional heavy dependency

        self.model = SentenceTransformer(model_name_or_path, cache_folder=str(cache_dir) if cache_dir else None,
                                         local_files_only=True, device="cpu")
        dim = None
        for name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):  # API differs across versions
            fn = getattr(self.model, name, None)
            if callable(fn):
                dim = fn()
                if dim:
                    break
        if not dim:
            dim = len(self.model.encode(["dimension probe"])[0])
        self.dim = int(dim)
        self.name = f"st:{Path(model_name_or_path).name}"

    def encode(self, texts: list[str]) -> np.ndarray:
        v = self.model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


def load_embedder(model: str, use_st: bool, models_dir: Path | None) -> tuple[Embedder, str]:
    """Return (embedder, human-readable status)."""
    if use_st and model:
        local = Path(model)
        candidates = [local] if local.exists() else []
        if models_dir is not None:
            candidates.append(models_dir / model.replace("/", "__"))
        try:
            for c in candidates:
                if c.exists():
                    e = SentenceTransformerEmbedder(str(c))
                    return e, f"Semantic embeddings: {c.name} (local files)"
            e = SentenceTransformerEmbedder(model, cache_dir=models_dir)
            return e, f"Semantic embeddings: {model} (local cache)"
        except ImportError:
            msg = "sentence-transformers not installed"
        except Exception as exc:  # noqa: BLE001 - model missing locally, offline, etc.
            msg = f"embedding model not available locally ({type(exc).__name__})"
        log.info("Falling back to lexical-hash embeddings: %s", msg)
        return HashingEmbedder(), f"Lexical-hash embeddings (fallback: {msg})"
    return HashingEmbedder(), "Lexical-hash embeddings (sentence-transformers disabled in Settings)"

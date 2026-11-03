"""One-time, OPTIONAL download of a sentence-transformers embedding model.

This is a separate setup step that needs internet.  It is never run by the
application itself.  The model is saved into the IsoResearch AI data folder
(models/<name>) and afterwards loaded with ``local_files_only=True``.

Usage (inside the virtual environment):
    python scripts/download_embedding_model.py
    python scripts/download_embedding_model.py --model sentence-transformers/all-MiniLM-L6-v2 --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isoresearch.core.paths import AppPaths, default_data_home  # noqa: E402
from isoresearch.core.settings import Settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2",
                    help="Hugging Face model id (default: all-MiniLM-L6-v2, ~90 MB)")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers is not installed. Install it first:\n"
              "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
              "  pip install -r requirements-embeddings.txt")
        return 1
    paths = AppPaths(default_data_home()).ensure()
    target = paths.models_dir / args.model.replace("/", "__")
    print(f"This will DOWNLOAD '{args.model}' from huggingface.co (internet required)\n"
          f"and save it to: {target}")
    if not args.yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return 0
    model = SentenceTransformer(args.model, device="cpu")
    model.save(str(target))
    s = Settings(paths)
    s.set("retrieval.embedding_model", args.model, save=False)
    s.set("retrieval.use_sentence_transformers", True)
    print("Done. Start IsoResearch AI; the search index is rebuilt automatically with the new embeddings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from isoresearch.retrieval.search import SearchEngine, SearchFilters


def _ids(chunks):
    return [c.doc_id for c in chunks]


def test_keyword_semantic_hybrid(app_ctx, pdfs):
    res = app_ctx.importer.import_paths([pdfs["a"], pdfs["b"]])
    a, b = res[0].doc_id, res[1].doc_id
    for mode in ("keyword", "semantic", "hybrid"):
        hits = app_ctx.search.search("averaging kernel a priori satellite retrieval", mode, 3)
        assert hits, mode
        assert hits[0].doc_id == b, mode
        hits = app_ctx.search.search("amount effect heavy convective rainfall depleted", mode, 3)
        assert hits[0].doc_id == a, mode
    # every hit carries provenance for citation
    h = app_ctx.search.hybrid("deuterium excess definition", 2)[0]
    assert h.page >= 1 and h.filename and h.doc_id and h.section is not None


def test_isotope_notation_normalisation(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    hits = app_ctx.search.semantic("d-excess", 3)
    assert any("Deuterium excess" in c.text for c in hits)


def test_scope_and_year_filters(app_ctx, pdfs):
    res = app_ctx.importer.import_paths([pdfs["a"], pdfs["b"]])
    a, b = res[0].doc_id, res[1].doc_id
    f = SearchFilters(doc_ids={a})
    for mode in ("keyword", "semantic", "hybrid"):
        assert set(_ids(app_ctx.search.search("averaging kernel satellite", mode, 5, f))) <= {a}
    assert app_ctx.search.hybrid("rainfall", 5, SearchFilters(doc_ids=set())) == []
    app_ctx.repo.update_document(b, year=2019)
    yr = SearchFilters(year_min=2023, year_max=2025)
    assert b not in _ids(app_ctx.search.hybrid("satellite averaging kernel", 5, yr))


def test_index_persists_and_rebuilds_on_embedder_change(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    n = len(app_ctx.search.index)
    assert n > 0
    # reopen: loads from disk without rebuild
    s2 = SearchEngine(app_ctx.db, app_ctx.paths.index_dir, "x", False)
    assert len(s2.index) == n and not s2.index.needs_rebuild
    # pretend the index was built by another embedder
    meta = app_ctx.paths.index_dir / "index_meta.json"
    meta.write_text(meta.read_text().replace("lexical-hash-768", "st:other-model"))
    s3 = SearchEngine(app_ctx.db, app_ctx.paths.index_dir, "x", False)
    assert s3.index.needs_rebuild
    assert s3.ensure_index() is True
    assert len(s3.index) == n and s3.semantic("amount effect", 1)


def test_corrupt_index_is_rebuilt(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    data = app_ctx.search.index.data_file
    data.write_bytes(b"garbage")
    s = SearchEngine(app_ctx.db, app_ctx.paths.index_dir, "x", False)
    assert s.index.needs_rebuild
    s.ensure_index()
    assert s.keyword("amount effect") and s.semantic("amount effect", 1)


def test_malformed_query_is_safe(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    for q in ['"unbalanced', "NEAR( AND OR", "δ18O*^", "", "   "]:
        app_ctx.search.keyword(q)
        app_ctx.search.hybrid(q or "x")


def test_sentence_transformer_wrapper_with_local_model(app_ctx, pdfs, monkeypatch, tmp_path):
    """Exercise the semantic-embedder code path with a stand-in model (no download)."""
    import sys
    import types

    import numpy as np

    from isoresearch.retrieval.embeddings import HashingEmbedder, load_embedder

    calls = {}

    class FakeST:
        def __init__(self, name, cache_folder=None, local_files_only=False, device=None):
            calls["local_files_only"] = local_files_only
            self.h = HashingEmbedder(64)

        def get_embedding_dimension(self):
            return 64

        def encode(self, texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False):
            return self.h.encode(list(texts))

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST))
    model_dir = tmp_path / "all-MiniLM-L6-v2"
    model_dir.mkdir()
    emb, status = load_embedder(str(model_dir), True, None)
    assert emb.semantic and emb.dim == 64 and "local files" in status
    assert calls["local_files_only"] is True  # never downloads at runtime
    assert np.isclose(np.linalg.norm(emb.encode(["δ18O"])[0]), 1.0)
    app_ctx.importer.import_paths([pdfs["a"]])
    s = SearchEngine(app_ctx.db, app_ctx.paths.index_dir, str(model_dir), True)
    assert s.index.needs_rebuild  # built by a different embedder
    s.ensure_index()
    assert s.semantic("amount effect", 2)


def test_missing_embedding_model_falls_back(monkeypatch):
    import sys
    import types

    from isoresearch.retrieval.embeddings import load_embedder

    class Boom:
        def __init__(self, *a, **k):
            raise OSError("not cached locally")

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=Boom))
    emb, status = load_embedder("sentence-transformers/all-MiniLM-L6-v2", True, None)
    assert not emb.semantic and "fallback" in status

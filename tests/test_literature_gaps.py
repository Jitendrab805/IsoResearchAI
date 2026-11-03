import json

import openpyxl
from docx import Document

from isoresearch.export.exporters import FileExistsRefused, markdown_to_docx, to_bibtex, to_ris, write_table
from isoresearch.research.gaps import GapService
from isoresearch.research.literature import LiteratureService, mark_unsupported
from mock_ollama import MockOllama


def _svc(ctx):
    return LiteratureService(ctx.db, ctx.search, ctx.llm, ctx.settings)


def test_scan_without_ai(app_ctx, pdfs):
    a = app_ctx.importer.import_file(pdfs["a"]).doc_id
    rec = _svc(app_ctx).scan(a)
    assert rec.fields["doi"]["value"] == "10.9999/synthetic.2024.001"
    assert rec.fields["doi"]["confidence"] == "high"
    assert "δ18O" in rec.value("isotope_vars") or "deuterium excess" in rec.value("isotope_vars").lower()
    assert rec.fields["model"]["confidence"] in ("not_found",)  # no model names in the text
    assert "precipitation" in rec.value("obs_types")


def _extract_reply(payload):
    user = payload["messages"][-1]["content"]
    if "Extract a structured literature record" in user:
        return json.dumps({
            "region": {"value": "island station", "confidence": "high", "sources": ["S1"]},
            "limitations": {"value": "only one monsoon season", "confidence": "high", "sources": ["S2"]},
            "future_work": {"value": "evaluate model against vapour isotopes", "confidence": "medium", "sources": ["S2"]},
            "doi": {"value": "10.1234/invented", "confidence": "high", "sources": ["S1"]},
            "journal": {"value": "", "confidence": "not_found", "sources": []},
            "findings": {"value": "negative slope with rainfall amount", "confidence": "high", "sources": []},
        })
    if "propose research gaps" in user:
        return json.dumps({"gaps": [
            {"title": "Vapour isotopes not used for evaluation", "kind": "inferred", "description": "d",
             "why_matters": "w", "hypothesis": "h", "questions": ["Q?"], "supporting_papers": ["P1"], "needed": "n"},
            {"title": "Unsupported gap", "kind": "inferred", "supporting_papers": ["P99"]}]})
    return "Heavy rain is depleted [S1]. This sentence has no citation at all here."


def test_llm_extraction_respects_evidence_rules(app_ctx, pdfs):
    a = app_ctx.importer.import_file(pdfs["a"]).doc_id
    svc = _svc(app_ctx)
    svc.edit_field(a, "relevance", "Highly relevant (my note)")
    with MockOllama(_extract_reply) as mo:
        app_ctx.settings.set("llm.base_url", mo.url)
        app_ctx.settings.set("llm.model", "mock")
        app_ctx.reload_llm()
        rec = svc.extract_with_llm(a)
    assert rec.value("region") == "island station" and rec.fields["region"]["pages"]
    assert rec.value("doi") == "10.9999/synthetic.2024.001"  # invented DOI rejected, text DOI kept
    assert rec.fields["findings"]["confidence"] == "low"  # no supporting source -> downgraded
    assert rec.fields["relevance"]["confidence"] == "user"  # user edit preserved
    assert rec.value("journal") == ""


def test_comparison_table_filters_and_exports(app_ctx, pdfs, tmp_path):
    ids = [r.doc_id for r in app_ctx.importer.import_paths([pdfs["a"], pdfs["b"]])]
    svc = _svc(app_ctx)
    for i in ids:
        svc.scan(i)
    svc.edit_field(ids[0], "model", "IsoRSM")
    headers, rows, kept = svc.table(ids, ["title", "model", "year"], {"model": "isorsm"})
    assert kept == [ids[0]] and headers[1] == "Model name"
    headers, rows, kept = svc.table(ids, ["title", "satellite"], {"obs_type": "satellite"})
    assert ids[1] in kept
    x = write_table(tmp_path / "t.xlsx", headers, rows)
    ws = openpyxl.load_workbook(x).active
    assert ws.cell(1, 1).value == "Full title" and ws.max_row == len(rows) + 1
    c = write_table(tmp_path / "t.csv", headers, rows)
    assert c.read_text(encoding="utf-8-sig").startswith("Full title")
    try:
        write_table(tmp_path / "t.csv", headers, rows)
    except FileExistsRefused:
        pass
    else:
        raise AssertionError("overwrite without confirmation must be refused")


def test_review_draft_marks_unsupported_and_exports_docx(app_ctx, pdfs, tmp_path):
    ids = [r.doc_id for r in app_ctx.importer.import_paths([pdfs["a"]])]
    with MockOllama(_extract_reply) as mo:
        app_ctx.settings.set("llm.base_url", mo.url)
        app_ctx.settings.set("llm.model", "mock")
        app_ctx.reload_llm()
        md = _svc(app_ctx).draft_review(ids, [("Precipitation isotopes", "amount effect rainfall")])
    assert "## Precipitation isotopes" in md and "[S1]" in md
    assert "unsupported — verify" in md
    assert "Sources (local library)" in md
    p = markdown_to_docx(md, tmp_path / "review.docx")
    text = "\n".join(par.text for par in Document(p).paragraphs)
    assert "Precipitation isotopes" in text and "[S1]" in text


def test_mark_unsupported():
    out = mark_unsupported("Rain was depleted during the event [S1]. The model is clearly wrong about all of it.")
    assert out.count("⚠") == 1


def test_gap_finder_separates_kinds(app_ctx, pdfs):
    ids = [r.doc_id for r in app_ctx.importer.import_paths([pdfs["a"], pdfs["b"]])]
    lit = _svc(app_ctx)
    lit.edit_field(ids[0], "limitations", "Only one monsoon season was sampled")
    lit.edit_field(ids[0], "model", "IsoRSM")
    lit.edit_field(ids[1], "satellite", "IASI")
    lit.edit_field(ids[1], "region", "India")
    lit.edit_field(ids[0], "region", "Andaman")
    with MockOllama(_extract_reply) as mo:
        app_ctx.settings.set("llm.base_url", mo.url)
        app_ctx.settings.set("llm.model", "mock")
        app_ctx.reload_llm()
        gaps = GapService(app_ctx.db, lit, app_ctx.llm).analyse(ids, app_ctx.settings.profile, use_llm=True)
    kinds = {g["kind"] for g in gaps}
    assert {"explicit", "combination", "inferred"} <= kinds
    explicit = [g for g in gaps if g["kind"] == "explicit"][0]
    assert explicit["supporting"][0]["doc_id"] == ids[0]
    assert not any(g["title"] == "Unsupported gap" for g in gaps)  # no traceable support -> discarded
    assert all(g["confidence"] in ("low", "medium", "high") for g in gaps)
    svc = GapService(app_ctx.db, lit, app_ctx.llm)
    assert all(g["status"] == "provisional" for g in svc.list())
    assert "Provisional" in svc.export_markdown()


def test_references_export(app_ctx, pdfs):
    app_ctx.importer.import_paths([pdfs["a"]])
    docs = app_ctx.repo.documents()
    bib = to_bibtex(docs)
    assert "@article{" in bib and "10.9999/synthetic.2024.001" in bib
    ris = to_ris(docs)
    assert "TY  - JOUR" in ris and "ER  - " in ris

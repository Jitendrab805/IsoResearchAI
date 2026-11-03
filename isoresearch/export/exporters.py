"""Exports: Markdown/TXT, DOCX, CSV/XLSX tables, BibTeX/RIS references.

Writers refuse to overwrite an existing file unless ``overwrite=True`` (the
GUI asks the user first).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path


class FileExistsRefused(FileExistsError):
    pass


def _guard(path: Path, overwrite: bool) -> Path:
    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsRefused(f"{path.name} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, text: str, overwrite: bool = False) -> Path:
    p = _guard(path, overwrite)
    p.write_text(text, encoding="utf-8")
    return p


def write_table(path: Path, headers: list[str], rows: list[list], overwrite: bool = False) -> Path:
    p = _guard(path, overwrite)
    if p.suffix.lower() in (".xlsx", ".xls"):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Comparison"
        ws.append(headers)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="0F766E")
        for r in rows:
            ws.append([("" if v is None else v) for v in r])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(12, max(len(str(c.value or ""))
                                                                                 for c in col[:50]) // 2))
            for c in col[1:]:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.freeze_panes = "A2"
        wb.save(p)
    else:
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            w.writerows(rows)
    return p


def markdown_to_docx(md: str, path: Path, overwrite: bool = False) -> Path:
    """Small Markdown → DOCX converter (headings, paragraphs, bullets, quotes, bold/italic, code)."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    p = _guard(path, overwrite)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    def add_runs(par, text: str) -> None:
        text = re.sub(r"\[(\[S\d+\])\]\(iso://cite/\d+\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
        text = re.sub(r"<[^>]+>", "", text)
        for tok in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)", text):
            if not tok:
                continue
            if tok.startswith("**") and tok.endswith("**"):
                par.add_run(tok[2:-2]).bold = True
            elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
                par.add_run(tok[1:-1]).italic = True
            elif tok.startswith("`"):
                r = par.add_run(tok[1:-1])
                r.font.name = "Consolas"
            else:
                par.add_run(tok)

    in_code, code_buf = False, []
    for line in md.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                par = doc.add_paragraph()
                r = par.add_run("\n".join(code_buf))
                r.font.name = "Consolas"
                r.font.size = Pt(9)
                code_buf = []
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(line)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            doc.add_heading(re.sub(r"[*`]", "", m.group(2)), level=min(len(m.group(1)), 3))
        elif re.match(r"^\s*[-*]\s+", line):
            add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", line))
        elif line.startswith(">"):
            par = doc.add_paragraph()
            add_runs(par, line.lstrip("> "))
            for r in par.runs:
                r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
                r.italic = True
        elif line.strip():
            add_runs(doc.add_paragraph(), line)
    doc.save(p)
    return p


# ------------------------------------------------------------- references
def _bibkey(doc: dict) -> str:
    words = (doc.get("authors") or "").split(";")[0].split(",")[0].split()
    first = re.sub(r"[^A-Za-z]", "", words[-1]) if words else ""
    return f"{first or 'anon'}{doc.get('year') or 'nd'}_{doc['id']}"


def to_bibtex(docs: list[dict]) -> str:
    out = []
    for d in docs:
        authors = " and ".join(a.strip() for a in (d.get("authors") or "").split(";") if a.strip())
        fields = {"title": d.get("title") or d.get("display_label") or d.get("filename"), "author": authors,
                  "year": d.get("year"), "journal": d.get("journal"), "doi": d.get("doi"),
                  "note": "Local file: " + d.get("filename", "")}
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        out.append(f"@article{{{_bibkey(d)},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def to_ris(docs: list[dict]) -> str:
    out = []
    for d in docs:
        lines = ["TY  - JOUR", f"TI  - {d.get('title') or d.get('display_label') or d.get('filename')}"]
        lines += [f"AU  - {a.strip()}" for a in (d.get("authors") or "").split(";") if a.strip()]
        if d.get("year"):
            lines.append(f"PY  - {d['year']}")
        if d.get("journal"):
            lines.append(f"JO  - {d['journal']}")
        if d.get("doi"):
            lines.append(f"DO  - {d['doi']}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def citation_text(d: dict) -> str:
    """Plain author–year reference string built only from stored fields."""
    authors = (d.get("authors") or "").replace(";", ",") or "[authors unknown]"
    year = d.get("year") or "n.d."
    title = d.get("title") or d.get("display_label") or d.get("filename")
    s = f"{authors} ({year}). {title}."
    if d.get("journal"):
        s += f" {d['journal']}."
    if d.get("doi"):
        s += f" https://doi.org/{d['doi']}"
    return s

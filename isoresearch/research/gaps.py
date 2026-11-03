"""Research-gap finder.

Three sources of candidate gaps, always kept separate and always *provisional*:

* explicit     — limitations / further work stated by the authors (from the
                 literature records, with the paper and pages).
* combination  — data/method combinations that are rare in the *local library*
                 (deterministic; says nothing about the wider literature).
* inferred     — gaps the local model proposes after comparing the papers.

Confidence reflects how much local evidence supports the gap
(number of supporting papers and whether authors state it), never a
probability that it is novel.
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from collections import defaultdict

from ..core.db import Database, dumps, loads
from ..llm.ollama_client import OllamaClient
from .literature import LiteratureService, parse_json_object

log = logging.getLogger(__name__)

PROVISIONAL_NOTE = ("Provisional: derived only from papers in your local library. Verify against the wider "
                    "literature (e.g. a database search) before claiming novelty.")


def evidence_confidence(n_papers: int, author_stated: bool) -> str:
    if author_stated and n_papers >= 2:
        return "high"
    if author_stated or n_papers >= 3:
        return "medium"
    return "low"


class GapService:
    def __init__(self, db: Database, lit: LiteratureService, llm: OllamaClient):
        self.db = db
        self.lit = lit
        self.llm = llm

    # ----------------------------------------------------------- storage
    def list(self) -> list[dict]:
        out = []
        for r in self.db.query("SELECT * FROM gaps ORDER BY id DESC"):
            d = dict(r)
            d["questions"] = loads(d.pop("questions_json"), [])
            d["supporting"] = loads(d.pop("supporting_json"), [])
            out.append(d)
        return out

    def add(self, g: dict) -> int:
        return self.db.execute(
            "INSERT INTO gaps(created_at, kind, title, description, why_matters, hypothesis, questions_json, "
            "supporting_json, needed, confidence, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), g["kind"], g["title"][:300], g.get("description", ""), g.get("why_matters", ""),
             g.get("hypothesis", ""), dumps(g.get("questions", [])), dumps(g.get("supporting", [])),
             g.get("needed", ""), g.get("confidence", "low"), "provisional"))

    def delete(self, gid: int) -> None:
        self.db.execute("DELETE FROM gaps WHERE id=?", (gid,))

    def clear(self) -> None:
        self.db.execute("DELETE FROM gaps")

    def set_status(self, gid: int, status: str) -> None:
        self.db.execute("UPDATE gaps SET status=? WHERE id=?", (status, gid))

    # ------------------------------------------------------ deterministic
    def _label(self, doc_id: int) -> str:
        rec = self.lit.get(doc_id)
        doc = self.lit.repo.document(doc_id) or {}
        t = doc.get("display_label") or rec.value("title") or doc.get("filename", f"doc {doc_id}")
        y = rec.value("year")
        return f"{t} ({y})" if y else t

    def explicit_gaps(self, doc_ids: list[int]) -> list[dict]:
        gaps = []
        for d in doc_ids:
            rec = self.lit.get(d)
            for key, label in (("limitations", "Author-stated limitation"), ("future_work", "Author-suggested further work")):
                f = rec.fields.get(key, {})
                if f.get("value") and f.get("confidence") not in ("not_found",) and f.get("method") != "keyword scan":
                    gaps.append({
                        "kind": "explicit", "title": f"{label}: {self._label(d)}",
                        "description": str(f["value"]),
                        "why_matters": "Stated by the authors themselves as unresolved.",
                        "hypothesis": "",
                        "questions": [],
                        "supporting": [{"doc_id": d, "label": self._label(d), "pages": f.get("pages", [])}],
                        "needed": "Check whether later papers (outside your library) have addressed this.",
                        "confidence": evidence_confidence(1, True)})
        return gaps

    def combination_gaps(self, doc_ids: list[int], min_dim_count: int = 1) -> list[dict]:
        dims = {"model": "model", "obs_types": "observation type", "region": "region",
                "isotope_vars": "isotope variable", "satellite": "satellite product"}
        per_doc: dict[int, dict[str, set[str]]] = {}
        for d in doc_ids:
            rec = self.lit.get(d)
            per_doc[d] = {k: {v.strip() for v in rec.value(k).split(";") if v.strip()} for k in dims}
        counts: dict[tuple, set[int]] = defaultdict(set)
        singles: dict[tuple[str, str], set[int]] = defaultdict(set)
        for d, sets in per_doc.items():
            for k, vals in sets.items():
                for v in vals:
                    singles[(k, v)].add(d)
            for (k1, k2) in itertools.combinations(dims, 2):
                for a in sets[k1]:
                    for b in sets[k2]:
                        counts[(k1, a, k2, b)].add(d)
        gaps = []
        interesting = [("model", "obs_types"), ("model", "region"), ("satellite", "region"),
                       ("model", "satellite"), ("isotope_vars", "region")]
        for k1, k2 in interesting:
            vals1 = [v for (k, v), s in singles.items() if k == k1 and len(s) >= min_dim_count]
            vals2 = [v for (k, v), s in singles.items() if k == k2 and len(s) >= min_dim_count]
            for a in vals1:
                for b in vals2:
                    together = counts.get((k1, a, k2, b), set()) or counts.get((k2, b, k1, a), set())
                    if len(together) == 0:
                        sup = sorted(singles[(k1, a)] | singles[(k2, b)])[:6]
                        gaps.append({
                            "kind": "combination",
                            "title": f"No paper in your library combines {dims[k1]} '{a}' with {dims[k2]} '{b}'",
                            "description": (f"'{a}' appears in {len(singles[(k1, a)])} paper(s) and '{b}' in "
                                            f"{len(singles[(k2, b)])}, but never together (based on keyword/extracted records)."),
                            "why_matters": "Underexplored data–method combinations can expose model or process "
                                           "understanding that single-dataset studies miss.",
                            "hypothesis": "",
                            "questions": [f"How does {a} perform/behave when assessed with {b}?"],
                            "supporting": [{"doc_id": d, "label": self._label(d), "pages": []} for d in sup],
                            "needed": "Literature search beyond the local library; confirm the records are correct "
                                      "(keyword-scan fields are only mentions).",
                            "confidence": "low"})
        return gaps[:40]

    # ---------------------------------------------------------- inferred
    def inferred_gaps(self, doc_ids: list[int], profile: dict, cancel: threading.Event | None = None) -> list[dict]:
        cols = ["title", "year", "region", "period", "objectives", "observations", "satellite", "model",
                "model_domain", "isotope_vars", "methods", "validation", "findings", "limitations", "future_work"]
        summary = []
        for i, d in enumerate(doc_ids, 1):
            rec = self.lit.get(d)
            summary.append({"paper": f"P{i}", **{c: rec.value(c)[:400] for c in cols}})
        prompt = (
            "Compare these structured records of papers from the user's LOCAL library and propose research gaps.\n"
            "Return ONLY JSON: {\"gaps\": [{\"title\", \"kind\": \"explicit\"|\"inferred\", \"description\", "
            "\"why_matters\", \"hypothesis\", \"questions\": [..], \"supporting_papers\": [\"P1\", ..], "
            "\"needed\"}]}\n"
            "Rules: 'explicit' only if an author-stated limitation/future-work field states it; otherwise 'inferred'. "
            "Look for inconsistencies between findings, and underexplored combinations of data, models, regions and "
            "methods. Every gap must list supporting papers that exist (P1..P%d). Do NOT claim novelty. Write "
            "testable research questions. Max 8 gaps.\n\nUSER PROFILE: %s\n\nRECORDS:\n%s"
            % (len(doc_ids), json.dumps(profile, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)))
        raw = self.llm.chat([{"role": "system", "content": "You are a rigorous research advisor in isotope hydrology."},
                             {"role": "user", "content": prompt}], cancel=cancel, fmt="json")
        data = parse_json_object(raw)
        out = []
        for g in data.get("gaps", [])[:8]:
            if not isinstance(g, dict) or not g.get("title"):
                continue
            refs = []
            for p in g.get("supporting_papers", []) or []:
                try:
                    idx = int(str(p).strip().lstrip("Pp")) - 1
                except ValueError:
                    continue
                if 0 <= idx < len(doc_ids):
                    refs.append(doc_ids[idx])
            if not refs:
                continue  # no traceable support → discard rather than present unsupported gap
            stated = g.get("kind") == "explicit" and any(
                self.lit.get(d).value("limitations") or self.lit.get(d).value("future_work") for d in refs)
            qs = g.get("questions") or []
            out.append({
                "kind": "explicit" if stated else "inferred", "title": str(g["title"]),
                "description": str(g.get("description", "")), "why_matters": str(g.get("why_matters", "")),
                "hypothesis": str(g.get("hypothesis", "")),
                "questions": [str(q) for q in (qs if isinstance(qs, list) else [qs])],
                "supporting": [{"doc_id": d, "label": self._label(d), "pages": []} for d in dict.fromkeys(refs)],
                "needed": str(g.get("needed", "")),
                "confidence": evidence_confidence(len(set(refs)), stated)})
        return out

    def analyse(self, doc_ids: list[int], profile: dict, use_llm: bool,
                cancel: threading.Event | None = None) -> list[dict]:
        for d in doc_ids:  # make sure every paper has at least the deterministic record
            if not self.lit.get(d).value("title"):
                self.lit.scan(d)
        gaps = self.explicit_gaps(doc_ids) + self.combination_gaps(doc_ids)
        if use_llm:
            gaps += self.inferred_gaps(doc_ids, profile, cancel)
        for g in gaps:
            g["id"] = self.add(g)
        return gaps

    def export_markdown(self) -> str:
        lines = ["# Research gaps (provisional)", "", f"> {PROVISIONAL_NOTE}", ""]
        for g in self.list():
            lines += [f"## {g['title']}", "",
                      f"- **Type:** {g['kind']}  ·  **Evidence confidence:** {g['confidence']}  ·  **Status:** {g['status']}",
                      f"- **Description:** {g['description']}"]
            if g.get("why_matters"):
                lines.append(f"- **Why it matters:** {g['why_matters']}")
            if g.get("hypothesis"):
                lines.append(f"- **Hypothesis:** {g['hypothesis']}")
            for q in g["questions"]:
                lines.append(f"- **Research question:** {q}")
            sup = "; ".join(s["label"] + (f" (p. {', '.join(map(str, s['pages']))})" if s.get("pages") else "")
                            for s in g["supporting"])
            lines += [f"- **Supporting papers:** {sup or 'none'}", f"- **Needed to validate:** {g.get('needed', '')}", ""]
        return "\n".join(lines)

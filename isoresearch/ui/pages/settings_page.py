"""Settings: AI model, privacy/offline, retrieval, OCR, storage/backup, appearance, research profile."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ...core import offline
from ...core.settings import DEFAULT_PROFILE
from ...export import backup
from ...ingest.pdf_extract import find_tessdata
from ...llm.ollama_client import SUGGESTED_MODELS
from ..state import AppState
from ..widgets.common import PageHeader, Pill, button, confirm, error_box, label
from ..workers import run_task

PROFILE_LABELS = {"research_area": "Research area", "primary_location": "Primary location of interest",
                  "primary_observations": "Primary observations", "modelling_interests": "Modelling interests",
                  "related_observations": "Related observations", "scientific_objective": "Scientific objective"}


class SettingsPage(QWidget):
    def __init__(self, state: AppState, on_theme=None):
        super().__init__()
        self.state = state
        self.ctx = state.ctx
        self.s = self.ctx.settings
        self.on_theme = on_theme
        pal = state.pal
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        body = QWidget()
        body.setMaximumWidth(980)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(14)
        root.addWidget(PageHeader("Settings", "All settings are stored locally in settings.json in your data folder.",
                                  "Configuration"))

        # ---------------------------------------------------------------- AI model
        g = QGroupBox("AI model (Ollama, local)")
        gl = QVBoxLayout(g)
        st_row = QHBoxLayout()
        self.model_pill = Pill("Not checked", "")
        st_row.addWidget(self.model_pill)
        st_row.addStretch(1)
        st_row.addWidget(button("Check status", "refresh", color=pal.muted, slot=self.check_status))
        st_row.addWidget(button("Test generation", "sparkle", color=pal.muted, slot=self.test_model))
        gl.addLayout(st_row)
        self.model_detail = label("", "Muted", wrap=True, selectable=True)
        gl.addWidget(self.model_detail)
        f = QFormLayout()
        self.base_url = QLineEdit(self.s.get("llm.base_url"))
        f.addRow("Ollama address", self.base_url)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(self.s.get("llm.model", ""))
        f.addRow("Model", self.model)
        self.temp = QDoubleSpinBox()
        self.temp.setRange(0, 1.5)
        self.temp.setSingleStep(0.05)
        self.temp.setValue(float(self.s.get("llm.temperature", 0.2)))
        f.addRow("Temperature", self.temp)
        self.ctxlen = QSpinBox()
        self.ctxlen.setRange(2048, 131072)
        self.ctxlen.setSingleStep(1024)
        self.ctxlen.setValue(int(self.s.get("llm.num_ctx", 8192)))
        f.addRow("Context window (tokens)", self.ctxlen)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(self.s.get("llm.read_timeout_s", 300)))
        f.addRow("Generation timeout", self.timeout)
        gl.addLayout(f)
        r = QHBoxLayout()
        r.addWidget(button("Save AI settings", "check", "Primary", color=pal.accent_text, slot=self.save_llm))
        self.pull_btn = button("Download a model via Ollama…", "export", color=pal.muted, slot=self.pull_model)
        r.addWidget(self.pull_btn)
        r.addStretch(1)
        gl.addLayout(r)
        guide = ("<b>First-time setup</b> (needs internet once):<br>"
                 "1. Install Ollama for Windows from ollama.com and start it (it runs at 127.0.0.1:11434).<br>"
                 "2. In a terminal run e.g. <code>ollama pull qwen2.5:7b</code> (≈4.7 GB).<br>"
                 "3. Press <i>Check status</i>, choose the model and <i>Save</i>.<br><br>"
                 "<b>Hardware:</b> RAM/VRAM use, disk space and speed depend on the model size and your hardware. "
                 "As a rough guide, 7–8B models (4–5 GB download) need ~8 GB free RAM or a 6–8 GB GPU; 3B models suit "
                 "8 GB laptops; 14B+ models need 16–32 GB RAM or a large GPU. Larger models follow the evidence rules "
                 "better.<br><br><b>Suggested models:</b><br>" +
                 "<br>".join(f"• <code>{n}</code> ({s_}) — {d}" for n, s_, d in SUGGESTED_MODELS))
        gl.addWidget(label(guide, wrap=True, selectable=True))
        root.addWidget(g)

        # ---------------------------------------------------------------- privacy
        g = QGroupBox("Privacy && offline mode")
        gl = QVBoxLayout(g)
        self.strict = QCheckBox("Strict offline mode (recommended)")
        self.strict.setToolTip("Blocks every application-initiated connection except loopback (127.0.0.1 / localhost)")
        self.strict.setChecked(self.s.strict_offline)
        self.strict.toggled.connect(self.toggle_strict)
        gl.addWidget(self.strict)
        self.online = QCheckBox("Allow optional online features (off by default)")
        self.online.setChecked(bool(self.s.get("privacy.allow_online_features")))
        self.online.toggled.connect(self.toggle_online)
        gl.addWidget(label("Strict offline blocks every application-initiated network connection except loopback "
                           "(127.0.0.1 / localhost), including DNS look-ups.", "Faint", wrap=True))
        gl.addWidget(self.online)
        gl.addWidget(label("The only optional online feature is asking the local Ollama service to download a model "
                           "after you confirm it.", "Faint", wrap=True))
        self.blocked = label("", "Faint")
        gl.addWidget(self.blocked)
        gl.addWidget(label(
            "<b>What stays local:</b> PDFs, extracted text, embeddings, index, chats, literature records, settings, "
            "figures and logs — all inside your data folder. There is no telemetry, analytics, account, API key or "
            "remote font/icon. The app binds no network server.<br><b>Outside the app's control:</b> the Ollama "
            "service is a separate program (model downloads you start with <code>ollama pull</code> are done by it); "
            "operating-system backups/sync (e.g. OneDrive folder redirection), antivirus scanning and disk encryption "
            "are managed by Windows and your institution. Store the data folder on an encrypted disk if your papers "
            "or data are confidential.", wrap=True))
        root.addWidget(g)

        # ---------------------------------------------------------------- retrieval
        g = QGroupBox("Retrieval && embeddings")
        gl = QVBoxLayout(g)
        self.embed_status = label(self.ctx.search.embedder_status, "Muted", wrap=True)
        gl.addWidget(self.embed_status)
        f = QFormLayout()
        self.use_st = QCheckBox("Use sentence-transformers model (local files only)")
        self.use_st.setChecked(bool(self.s.get("retrieval.use_sentence_transformers")))
        f.addRow("", self.use_st)
        self.embed_model = QLineEdit(self.s.get("retrieval.embedding_model"))
        f.addRow("Embedding model name or folder", self.embed_model)
        self.topk = QSpinBox()
        self.topk.setRange(2, 30)
        self.topk.setValue(int(self.s.get("retrieval.top_k", 8)))
        f.addRow("Passages per answer", self.topk)
        self.chunk = QSpinBox()
        self.chunk.setRange(300, 4000)
        self.chunk.setValue(int(self.s.get("retrieval.chunk_chars", 1100)))
        f.addRow("Chunk size (characters)", self.chunk)
        gl.addLayout(f)
        gl.addWidget(label("To install the semantic model once (needs internet): "
                           "<code>python scripts\\download_embedding_model.py</code>. Changing the embedder requires "
                           "an index rebuild (done automatically).", "Faint", wrap=True))
        r = QHBoxLayout()
        r.addWidget(button("Save && reload embedder", "check", "Primary", color=pal.accent_text, slot=self.save_retrieval))
        r.addWidget(button("Rebuild index", "refresh", color=pal.muted, slot=self.rebuild))
        r.addStretch(1)
        gl.addLayout(r)
        root.addWidget(g)

        # ---------------------------------------------------------------- OCR
        g = QGroupBox("OCR for scanned PDFs (local Tesseract)")
        gl = QVBoxLayout(g)
        f = QFormLayout()
        self.ocr = QCheckBox("Run OCR on pages without a text layer")
        self.ocr.setChecked(bool(self.s.get("ocr.enabled")))
        f.addRow("", self.ocr)
        self.ocr_lang = QLineEdit(self.s.get("ocr.language", "eng"))
        f.addRow("Language(s)", self.ocr_lang)
        self.tess = QLineEdit(self.s.get("ocr.tessdata", ""))
        self.tess.setPlaceholderText("Auto-detect (e.g. C:\\Program Files\\Tesseract-OCR\\tessdata)")
        f.addRow("tessdata folder", self.tess)
        gl.addLayout(f)
        found = find_tessdata(self.s.get("ocr.tessdata", ""))
        gl.addWidget(label(f"Tesseract language data: {found}" if found else
                           "Tesseract not found. Install it (e.g. the UB Mannheim Windows build) to enable OCR; "
                           "scanned PDFs are still kept and flagged without it.", "Faint", wrap=True))
        gl.addWidget(button("Save OCR settings", "check", color=pal.muted, slot=self.save_ocr))
        root.addWidget(g)

        # ---------------------------------------------------------------- storage
        g = QGroupBox("Storage, backup && deletion")
        gl = QVBoxLayout(g)
        gl.addWidget(label(f"Data folder: <code>{self.ctx.paths.home}</code><br>PDF library: "
                           f"<code>{self.s.library_dir}</code>", wrap=True, selectable=True))
        r = QHBoxLayout()
        r.addWidget(button("Open data folder", "folder", color=pal.muted,
                           slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.paths.home)))))
        r.addWidget(button("Change PDF library folder…", "folder", color=pal.muted, slot=self.change_library))
        r.addStretch(1)
        gl.addLayout(r)
        r = QHBoxLayout()
        self.inc_pdfs = QCheckBox("Include PDFs in backup")
        self.inc_pdfs.setChecked(True)
        r.addWidget(self.inc_pdfs)
        r.addWidget(button("Create backup…", "export", "Primary", color=pal.accent_text, slot=self.make_backup))
        r.addWidget(button("Restore backup…", "refresh", color=pal.muted, slot=self.restore))
        r.addStretch(1)
        r.addWidget(button("Delete all research data…", "trash", "Danger", color=pal.danger, slot=self.delete_all))
        gl.addLayout(r)
        root.addWidget(g)

        # ---------------------------------------------------------------- appearance
        g = QGroupBox("Appearance")
        f = QFormLayout(g)
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(self.s.get("ui.theme", "dark"))
        self.theme.currentTextChanged.connect(self.set_theme)
        f.addRow("Theme", self.theme)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.8, 1.6)
        self.scale.setSingleStep(0.05)
        self.scale.setValue(float(self.s.get("ui.font_scale", 1.0)))
        self.scale.valueChanged.connect(lambda v: (self.s.set("ui.font_scale", round(v, 2)),
                                                   self.on_theme and self.on_theme()))
        f.addRow("Text size", self.scale)
        root.addWidget(g)

        # ---------------------------------------------------------------- profile
        g = QGroupBox("My research profile (used to judge relevance — never treated as evidence)")
        gl = QVBoxLayout(g)
        f = QFormLayout()
        self.profile_edits = {}
        prof = self.s.profile
        for k, lbl in PROFILE_LABELS.items():
            e = QPlainTextEdit(prof.get(k, ""))
            e.setFixedHeight(54)
            self.profile_edits[k] = e
            f.addRow(lbl, e)
        gl.addLayout(f)
        r = QHBoxLayout()
        r.addWidget(button("Save profile", "check", "Primary", color=pal.accent_text, slot=self.save_profile))
        r.addWidget(button("Reset to initial profile", "refresh", "Ghost", color=pal.muted, slot=self.reset_profile))
        r.addStretch(1)
        gl.addLayout(r)
        root.addWidget(g)
        root.addWidget(label(f"Logs: {self.ctx.paths.logs_dir} (JSON lines; paper text, prompts and answers are not "
                             "logged).", "Faint", wrap=True, selectable=True))
        root.addStretch(1)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.addWidget(body)
        wl.addStretch(1)
        sc.setWidget(wrap)
        outer.addWidget(sc)
        state.model_status_changed.connect(self._show_status)
        self._refresh_privacy()
        self._show_status(state.model_status)

    # ------------------------------------------------------------------ model
    def check_status(self) -> None:
        self.model_pill.set_state("accent", "Checking…")
        run_task(lambda t: self.ctx.llm.status(), on_result=self._status_result,
                 on_error=lambda e: self._status_result({"ready": False, "running": False, "error": str(e),
                                                         "models": []}))

    def _status_result(self, st: dict) -> None:
        self.state.model_status = st
        self.state.model_status_changed.emit(st)

    def _show_status(self, st: dict) -> None:
        models = st.get("models", [])
        cur = self.model.currentText()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(cur or self.s.get("llm.model", ""))
        self.model.blockSignals(False)
        if st.get("ready"):
            self.model_pill.set_state("ok", f"Verified: '{st.get('model')}' is available locally")
        elif st.get("running"):
            self.model_pill.set_state("warn", "Ollama is running, but the selected model is not available")
        else:
            self.model_pill.set_state("error", "Local AI service not reachable")
        bits = []
        if st.get("version"):
            bits.append(f"Ollama {st['version']} at {self.ctx.llm.base_url}")
        bits.append(f"Ollama program on PATH: {'yes' if st.get('installed') else 'not found'}")
        if models:
            bits.append("Downloaded models: " + ", ".join(models))
        if st.get("error"):
            bits.append("⚠ " + st["error"])
        self.model_detail.setText("\n".join(bits))

    def save_llm(self) -> None:
        url = self.base_url.text().strip() or "http://127.0.0.1:11434"
        if self.s.strict_offline and not offline.is_loopback_url(url):
            error_box(self, "Not allowed in strict offline mode",
                      "The Ollama address must be on this computer (127.0.0.1 or localhost) while strict offline mode "
                      "is on.")
            return
        self.s.set("llm.base_url", url, save=False)
        self.s.set("llm.model", self.model.currentText().strip(), save=False)
        self.s.set("llm.temperature", round(self.temp.value(), 2), save=False)
        self.s.set("llm.num_ctx", self.ctxlen.value(), save=False)
        self.s.set("llm.read_timeout_s", self.timeout.value())
        self.ctx.reload_llm()
        self.state.toast.emit("AI settings saved.", "ok")
        self.check_status()

    def test_model(self) -> None:
        self.model_pill.set_state("accent", "Running a short test generation…")
        t0 = time.time()
        run_task(lambda t: self.ctx.llm.test_connection(),
                 on_result=lambda txt: (self.model_pill.set_state("ok", f"Model responded in {time.time() - t0:.1f}s: "
                                                                        f"“{txt[:40]}”"),
                                        self.check_status()),
                 on_error=lambda e: self.model_pill.set_state("error", f"Test failed: {e}"))

    def pull_model(self) -> None:
        if not self.s.get("privacy.allow_online_features"):
            error_box(self, "Online features are disabled",
                      "Downloading a model is an optional online feature and is disabled by default.\n\nEither run "
                      "`ollama pull <model>` yourself in a terminal, or enable 'Allow optional online features' "
                      "under Privacy.")
            return
        names = [f"{n}  ({s_})" for n, s_, _ in SUGGESTED_MODELS]
        choice, ok = QInputDialog.getItem(self, "Download model", "Model to download with Ollama:", names, 0, True)
        if not ok:
            return
        name = choice.split()[0]
        if not confirm(self, "Confirm download", f"Ask the local Ollama service to download '{name}'?\n\nThis "
                       "requires internet, can take a long time and uses several GB of disk space. The download is "
                       "performed by Ollama, not by IsoResearch AI.", "Download"):
            return
        self.model_pill.set_state("accent", f"Downloading {name}…")
        run_task(lambda t: self.ctx.llm.pull(name, progress=lambda s_, f_: t.progress(int(f_ * 100), 100, s_),
                                             cancel=t.cancel_event),
                 on_progress=lambda d, n, m: self.model_pill.set_state("accent", f"{m} {d}%"),
                 on_result=lambda _: (self.state.toast.emit(f"Downloaded {name}.", "ok"), self.check_status()),
                 on_error=lambda e: self.model_pill.set_state("error", f"Download failed: {e}"))

    # ------------------------------------------------------------------ privacy
    def toggle_strict(self, on: bool) -> None:
        if not on and not confirm(self, "Disable strict offline mode?",
                                  "With strict offline mode off, the app no longer blocks outbound connections "
                                  "(it still never uploads your papers or prompts by itself). Continue?", "Disable",
                                  True):
            self.strict.blockSignals(True)
            self.strict.setChecked(True)
            self.strict.blockSignals(False)
            return
        self.s.set("privacy.strict_offline", on)
        offline.apply(on)
        self._refresh_privacy()
        self.state.toast.emit("Strict offline mode " + ("enabled." if on else "disabled."), "ok" if on else "warn")

    def toggle_online(self, on: bool) -> None:
        self.s.set("privacy.allow_online_features", on)
        self._refresh_privacy()

    def _refresh_privacy(self) -> None:
        self.blocked.setText(f"Guard active: {offline.is_enabled()} · blocked connection attempts this session: "
                             f"{len(offline.blocked_attempts)}")
        self.pull_btn.setEnabled(bool(self.s.get("privacy.allow_online_features")))

    # ------------------------------------------------------------------ retrieval / ocr
    def save_retrieval(self) -> None:
        self.s.set("retrieval.use_sentence_transformers", self.use_st.isChecked(), save=False)
        self.s.set("retrieval.embedding_model", self.embed_model.text().strip(), save=False)
        self.s.set("retrieval.top_k", self.topk.value(), save=False)
        self.s.set("retrieval.chunk_chars", self.chunk.value())
        self.embed_status.setText("Loading embedder…")

        def work(t):
            self.ctx.reload_embedder()
            self.ctx.reload_importer()
            self.ctx.search.ensure_index(progress=lambda d, n: t.progress(d, n, "indexing"))
            return self.ctx.search.embedder_status
        run_task(work, on_result=lambda s_: (self.embed_status.setText(s_),
                                             self.state.toast.emit("Retrieval settings applied.", "ok"),
                                             self.state.library_changed.emit()),
                 on_error=lambda e: self.embed_status.setText(f"Failed: {e}"),
                 on_progress=lambda d, n, m: self.embed_status.setText(f"Re-indexing {d}/{n} passages…"))

    def rebuild(self) -> None:
        self.embed_status.setText("Rebuilding index…")
        run_task(lambda t: self.ctx.search.rebuild(progress=lambda d, n: t.progress(d, n, "")),
                 on_result=lambda n: self.embed_status.setText(f"Index rebuilt: {n} passages. "
                                                               f"{self.ctx.search.embedder_status}"),
                 on_error=lambda e: self.embed_status.setText(f"Rebuild failed: {e}"),
                 on_progress=lambda d, n, m: self.embed_status.setText(f"Rebuilding {d}/{n}…"))

    def save_ocr(self) -> None:
        self.s.set("ocr.enabled", self.ocr.isChecked(), save=False)
        self.s.set("ocr.language", self.ocr_lang.text().strip() or "eng", save=False)
        self.s.set("ocr.tessdata", self.tess.text().strip())
        self.ctx.reload_importer()
        self.state.toast.emit("OCR settings saved. Use Library → Re-process for already imported scanned PDFs.", "ok")

    # ------------------------------------------------------------------ storage
    def change_library(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for imported PDFs", str(self.s.library_dir))
        if not d:
            return
        if not confirm(self, "Change library folder", "New imports will be copied to:\n" + d + "\n\nAlready imported "
                       "PDFs stay where they are (their paths are remembered).", "Change"):
            return
        self.s.set("storage.library_dir", d)
        self.ctx.reload_importer()
        self.state.toast.emit("Library folder changed.", "ok")

    def make_backup(self) -> None:
        default = self.ctx.paths.backups_dir / f"isoresearch-backup-{time.strftime('%Y%m%d-%H%M')}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Create backup", str(default), "ZIP (*.zip)")
        if not path:
            return
        if Path(path).exists() and not confirm(self, "Overwrite?", "That backup file exists. Overwrite it?",
                                               "Overwrite", True):
            return
        inc = self.inc_pdfs.isChecked()
        self.state.toast.emit("Creating backup…", "info")
        run_task(lambda t: backup.create_backup(self.ctx.paths, self.s, Path(path), inc),
                 on_result=lambda p: self.state.toast.emit(f"Backup saved: {Path(p).name}", "ok"),
                 on_error=lambda e: error_box(self, "Backup failed", str(e)))

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", str(self.ctx.paths.backups_dir), "ZIP (*.zip)")
        if not path:
            return
        if not confirm(self, "Restore backup", "Restoring replaces your current library database, index, figures and "
                       "settings with the backup's contents. A safety copy of the current database is kept in the "
                       "backups folder. The app will close afterwards; start it again.", "Restore", True):
            return
        try:
            self.ctx.db.close()
            info = backup.restore_backup(self.ctx.paths, self.s, Path(path))
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Restore failed", str(exc))
            return
        error_box(self, "Restore complete", f"Restored backup from {info.get('created')}. IsoResearch AI will now "
                  "close — please start it again.")
        self.window().close()

    def delete_all(self) -> None:
        if not confirm(self, "Delete all research data", "Permanently delete the database (papers, chats, literature "
                       "records, gaps), the index, figures, exports, logs and the PDF copies in the library folder?\n\n"
                       "Your original PDF files elsewhere are not touched. This cannot be undone — make a backup "
                       "first if unsure.", "Continue", True):
            return
        word, ok = QInputDialog.getText(self, "Confirm deletion", "Type DELETE to confirm:")
        if not ok or word.strip() != "DELETE":
            self.state.toast.emit("Deletion cancelled.", "info")
            return
        self.ctx.db.close()
        removed = backup.delete_all_data(self.ctx.paths, self.s, include_library=True)
        error_box(self, "Data deleted", f"Removed {len(removed)} item(s). IsoResearch AI will now close; it starts "
                  "with an empty library next time.\n\nNote: copies in OS backups, sync folders or the recycle bin are "
                  "outside the app's control.")
        self.window().close()

    # ------------------------------------------------------------------ appearance / profile
    def set_theme(self, name: str) -> None:
        self.s.set("ui.theme", name)
        if self.on_theme:
            self.on_theme()

    def save_profile(self) -> None:
        self.s.set("profile", {k: e.toPlainText().strip() for k, e in self.profile_edits.items()})
        self.state.toast.emit("Research profile saved.", "ok")

    def reset_profile(self) -> None:
        for k, e in self.profile_edits.items():
            e.setPlainText(DEFAULT_PROFILE.get(k, ""))


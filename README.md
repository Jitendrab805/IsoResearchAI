# IsoResearch AI

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23925949.svg)](https://doi.org/10.5281/zenodo.23925949)

**A private desktop research workstation for water isotope hydrology, atmospheric water-vapour isotopes and
isotope-enabled climate modelling.**

IsoResearch AI reads *your own* PDF library, answers questions with citations to the exact paper and page,
builds structured literature reviews, proposes (provisional) research gaps, plans and draws publication-quality
isotope figures from your data, and inspects CSV / Excel / NetCDF datasets — all on your own computer.

- Desktop app (PySide6), its own window — no browser tab.
- Papers, extracted text, embeddings, chats, settings, figures and logs are stored locally.
- AI answers come from a **local** model served by [Ollama](https://ollama.com) on `127.0.0.1`. The app shows
  “verified local” only after a real round-trip to that service succeeds.
- **Strict offline mode is on by default**: every application-initiated network connection except loopback is
  blocked inside the app. No account, API key, telemetry, analytics or remote fonts.
- If no model is available, the app never invents an answer — it says so and shows the most relevant library
  passages instead (keyword + semantic search).

---

## 1. What you need

| | Minimum | Recommended |
|---|---|---|
| Windows | 10 or 11, 64-bit | 11 |
| Python | 3.10 – 3.13 | **3.12** from python.org |
| RAM | 8 GB (3B model) | 16 GB+ (7–8B model) |
| Disk | ~2 GB for the app + 2–10 GB per AI model | SSD |
| GPU | not required | NVIDIA/AMD GPU speeds up Ollama |

RAM, VRAM, disk use and speed depend on the model you choose and your hardware (see §4).

## 2. Install (one time, needs internet)

1. Install **Python 3.12** from <https://www.python.org/downloads/windows/>. During installation tick
   **“Add python.exe to PATH”**.
2. Unzip the `IsoResearchAI` folder somewhere you have write access, e.g. `C:\Users\<you>\IsoResearchAI`.
3. Double-click **`setup_windows.bat`**. It creates a private Python environment in `.venv`, installs the
   packages from `requirements.txt`, asks whether to add the *optional* semantic-embedding model, generates the
   synthetic example data and runs a start-up check.

Internet is needed only for this step (Python packages) and for downloading an AI model (next section).
After that IsoResearch AI works offline.

## 3. Start

Double-click **`IsoResearchAI.bat`** (no console window). If something goes wrong at start-up, use
`IsoResearchAI_debug.bat`, which keeps a console open with the error message.

From a terminal: `.venv\Scripts\python.exe -m isoresearch`

## 4. Set up the local AI model (Ollama)

1. Install **Ollama for Windows** from <https://ollama.com> and start it (it listens on `127.0.0.1:11434`).
2. Download a model **yourself** in a terminal (the app never downloads a model without your approval):

   | Model | Download | Suits |
   |---|---|---|
   | `qwen2.5:7b` | ≈4.7 GB | good default; reliable structured/JSON output for literature extraction |
   | `llama3.1:8b` | ≈4.9 GB | good general quality; 16 GB RAM or 8 GB VRAM |
   | `llama3.2:3b` | ≈2.0 GB | 8 GB laptops; lower quality |
   | `qwen2.5:14b` | ≈9 GB | better reasoning; 16–32 GB RAM or 12 GB+ GPU |

   ```
   ollama pull qwen2.5:7b
   ```
3. In IsoResearch AI open **Settings → AI model**, press **Check status**, choose the model, **Save AI
   settings**, then **Test generation**. The sidebar shows *“AI: qwen2.5:7b (verified local)”* when ready.

*(Optional online feature, off by default: with “Allow optional online features” enabled in Settings → Privacy,
the app can ask Ollama to download a model after you confirm. The download is done by Ollama itself.)*

## 5. Quick tour

| Area | What it does |
|---|---|
| **New Research Chat** | Ask questions; answers stream from the local model and cite passages as **[S1]** with title, authors, year and page. Click a citation to open the PDF at that page. Stop button, copy, export to Markdown/TXT. Follow-ups reuse context and previously cited passages. |
| **Research context panel** (right; `Ctrl+Shift+P`) | Active topic, year filter, collections in scope, selected documents, the passages behind the last answer and paper metadata. |
| **Research Library** | Import PDFs/folders (or drag & drop), SHA-256 duplicate detection, status per document, scanned-PDF detection + optional local OCR, tags, collections, display labels, notes, passage search (hybrid/keyword/semantic), import log with diagnostics. |
| **Literature Review** | Per-paper structured record (title … relevance to your PhD) with confidence, method and pages for every field; editable; comparison tables with filters; theme-organised review drafts with traceable citations; CSV/Excel/Markdown/DOCX export. |
| **Research Gap Finder** | Author-stated gaps, underexplored data/method combinations and AI-inferred gaps — kept separate, all *provisional*, with supporting papers and an evidence-based confidence. |
| **Plot Advisor** | 19 isotope plot types (dual-isotope/LMWL, d-excess, amount effect, event progression, lagged correlation, amount-weighted summaries, δ–ln q, profiles, trajectories, obs-vs-model, seasonal skill, Taylor, residuals, satellite & averaging-kernel comparisons). Explains the question, interpretation, alternatives, confounders and statistics; checks your data; previews from your file; exports PNG/SVG/PDF + the exact Python script + config. |
| **Data Analysis** | Open CSV/Excel/NetCDF read-only; preview, units, missing values, time coverage, dimensions; automatic variable detection with manual mapping; QC report; quick plots; explicit, logged derivations (e.g. d-excess); transformation log. |
| **Reference Manager** | Bibliographic table (auto-detected values highlighted until you confirm), copy citations, export BibTeX/RIS/CSV/Excel. |
| **Settings** | AI model, privacy/offline, embeddings & index rebuild, OCR, library folder, backup/restore, delete all data, theme, research profile. |

Try the workflow without real data: **Data Analysis → Load synthetic example** (clearly marked *SYNTHETIC* —
not real observations).

## 6. How evidence is handled

- Retrieved passages are sent to the model as numbered, *untrusted* `<source>` blocks with title, authors,
  year, page and section. Instructions found inside PDFs are ignored.
- The model must cite `[S#]`. After generation every marker is validated: markers that do not correspond to a
  provided passage are flagged as invalid and are **never** turned into references. Uncited answers and “no
  evidence found” cases are labelled.
- Literature fields that the model cannot tie to a passage are downgraded to *low* confidence; DOIs are accepted
  only if literally present in the PDF text; your edits are never overwritten.
- Gaps are *provisional* until you verify them against the wider literature — absence from your library is not
  novelty.
- Plots are drawn only from your file. Nothing is interpolated or imputed; missing variables are reported.
- Code shown in chat or in the Plot Advisor is **never executed automatically**.

## 7. Privacy & storage

Everything lives in one data folder: `%APPDATA%\IsoResearchAI` (database, index, settings, figures, exports,
logs, backups, models) and the PDF library folder (default `%APPDATA%\IsoResearchAI\library`, changeable).

- **Strict offline mode** (default on) blocks outbound connections and DNS look-ups from the app process
  except loopback; Hugging Face/transformers offline flags are set.
- The Ollama address must be loopback while strict mode is on. The app does not open any server port.
- Logs contain identifiers, counts and error types — not paper text, prompts or answers.
- **Backup & restore**: Settings → Storage (ZIP with database, settings, index, figures and optionally PDFs).
- **Delete all research data**: Settings → Storage (double confirmation).
- Outside the app’s control: the Ollama program, Windows backups/OneDrive folder redirection, antivirus, the
  recycle bin and disk encryption. Keep the data folder on an encrypted disk if your material is confidential.

## 8. Semantic embeddings (optional)

By default retrieval uses a built-in **lexical-hash embedding** (no download, isotope notation normalised:
δ18O/d18O/delta 18O …) combined with BM25 keyword search. For neural semantic search install the optional
package and model once (internet needed):

```
.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r requirements-embeddings.txt
.venv\Scripts\python.exe scripts\download_embedding_model.py
```

The model is stored in `%APPDATA%\IsoResearchAI\models` and always loaded with `local_files_only=True`.
The index is rebuilt automatically when the embedder changes.

## 9. OCR for scanned PDFs (optional)

Install Tesseract OCR for Windows (e.g. the UB Mannheim build). IsoResearch AI finds
`C:\Program Files\Tesseract-OCR\tessdata` automatically, or set the folder in Settings → OCR. Without OCR,
scanned PDFs are still kept, flagged *No text* and can be opened; use **Re-process** after installing OCR.

## 10. Standalone Windows executable

```
build_exe.bat
```
produces `dist\IsoResearchAI\IsoResearchAI.exe` (one-folder build; copy the whole folder). See
[docs/PACKAGING.md](docs/PACKAGING.md).

## 11. Tests

```
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```
The suite (61 tests) covers PDF ingestion and OCR, retrieval, citation validation, storage/migrations/backup,
plotting and exports, offline enforcement, the missing-model path, cancellation and GUI responsiveness. It uses
synthetic PDFs generated on the fly and a fake local Ollama server — no real papers and no internet.

## 12. More documentation

- [docs/EXAMPLE_QUESTIONS.md](docs/EXAMPLE_QUESTIONS.md) — research questions to try
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PACKAGING.md](docs/PACKAGING.md)

No research papers are distributed with this application. Import only papers you have the right to use.

## Citation

If you use **IsoResearch AI** in your research, workflows, or publications, please cite it as:

```bibtex
@software{Bhilala_IsoResearchAI_2026,
  author = {Bhilala, Jitendra},
  title = {{IsoResearch AI: Offline Local Scientific Research Workstation}},
  year = {2026},
  month = {11},
  version = {1.0.0},
  doi = {10.5281/zenodo.23925949},
  url = {[https://github.com/Jitendrab805/IsoResearchAI](https://github.com/Jitendrab805/IsoResearchAI)}
}


# Troubleshooting

Start with `IsoResearchAI_debug.bat` — it keeps a console window open so you can read error messages.
The log file is `%APPDATA%\IsoResearchAI\logs\isoresearch.log` (JSON lines, no paper text).

## Installation

| Symptom | Fix |
|---|---|
| `Python 3.10-3.13 was not found` | Install Python 3.12 from python.org and tick *Add python.exe to PATH*. Close and reopen the folder, run `setup_windows.bat` again. |
| `pip install` fails on `netCDF4`/`faiss-cpu` | You are probably on a Python version without pre-built wheels (e.g. a very new or 32-bit Python). Use 64-bit Python 3.12. |
| Setup fails behind a university proxy | Set `HTTPS_PROXY=http://proxy:port` in the same terminal before running setup (setup is the only step needing internet). |
| “Windows protected your PC” on the .exe | The self-built executable is unsigned. Click *More info → Run anyway*, or run from source with `IsoResearchAI.bat`. |
| Antivirus quarantines files in `dist\` | Add an exclusion for the folder or run from source. One-folder builds are flagged less often than one-file builds. |

## Start-up

| Symptom | Fix |
|---|---|
| Window does not appear | Run `IsoResearchAI_debug.bat`. If you see `qt.qpa.plugin` errors, reinstall PySide6: `.venv\Scripts\python.exe -m pip install --force-reinstall PySide6`. |
| Blurry text on a high-DPI screen | Windows → Display → Scaling. Adjust *Settings → Appearance → Text size* in the app. |
| “Settings file unreadable” in the log | The file was corrupted; it was renamed to `settings.corrupt.json` and defaults were used. Re-enter settings. |

## Local AI model

| Message | Meaning / fix |
|---|---|
| **Local AI not reachable** | Ollama is not running. Start the Ollama app (tray icon) or run `ollama serve`. Check <http://127.0.0.1:11434> in a browser shows “Ollama is running”. |
| **Ollama running — no model selected/downloaded** | Run `ollama pull qwen2.5:7b` (or another model), then Settings → AI model → Check status → choose → Save. |
| “only allows a local (loopback) Ollama address” | Strict offline mode permits only `127.0.0.1`/`localhost`. Use a local Ollama, or deliberately turn strict mode off. |
| Answers are slow | Use a smaller model (3B), close other programs, reduce *Context window*, or use a GPU. The first answer after start is slower while the model loads. |
| “did not start responding before the timeout” | Increase *Generation timeout* in Settings, or use a smaller model. |
| Literature extraction says “did not return JSON” | Use a model that follows instructions well (e.g. `qwen2.5:7b` or larger). |
| Answers ignore citations | Smaller models follow the evidence rules less reliably. The app flags uncited/invalid citations; prefer 7B+ models. |

## Library & search

| Symptom | Fix |
|---|---|
| Status **No text** | The PDF is scanned/image-only. Install Tesseract OCR, enable OCR in Settings, then select the paper → *Re-process*. |
| Status **Failed** | See the diagnostic in the detail panel / Import log (e.g. password-protected or damaged PDF). Remove the password or re-download the PDF. |
| “Duplicate … not imported again” | Same SHA-256 as an existing paper; the existing copy was added to the selected collection instead. |
| Wrong title/authors/year | Auto-detected values are guesses (highlighted in the Reference Manager). Edit them in the Library detail panel or Reference Manager. |
| Search misses obvious passages | Try *Keyword* mode for exact terms, or install the optional semantic embeddings (README §8). |
| “Rebuilding the search index…” at start | The index was missing, corrupt or built with another embedder; it is rebuilt from the database automatically. You can also use Settings → Rebuild index. |
| PDF does not open at the page | The built-in viewer needs QtPdf (part of PySide6). Use *Open in system viewer* as a fallback. If “PDF not found”, the library copy was moved/deleted — restore a backup or re-import. |

## Data & plots

| Symptom | Fix |
|---|---|
| Variables not detected | Map them manually in *Data Analysis → Variable mapping* and press *Apply mapping*. |
| Plot shows “Not supported yet” | The checklist lists missing variables or too few values. Nothing is invented to fill gaps. |
| Excel file opens the wrong sheet | Only the first sheet is read; save the sheet you need as its own file or CSV. |
| NetCDF variables with 2+ dimensions are not in the table | They are kept as arrays (e.g. averaging kernels) and can be mapped under *Arrays* for the averaging-kernel plot. |
| Exported script fails on another PC | Edit `DATA_FILE` at the top of `make_figure.py` to the file’s new location. |

## Backup / restore / delete

- Restoring replaces the current database; a safety copy `pre-restore-*.sqlite3` is kept in the backups folder.
  Restart the app after restoring.
- *Delete all research data* removes the database, index, figures, exports, logs and library copies. Original
  files elsewhere on your disk are not touched; copies in OneDrive, Windows backups or the recycle bin are
  outside the app’s control.

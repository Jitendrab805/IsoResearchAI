# Building a standalone Windows executable (PyInstaller)

The build must be done **on Windows** (PyInstaller does not cross-compile).

```
setup_windows.bat          # once, creates .venv
build_exe.bat              # installs PyInstaller into .venv and runs isoresearch.spec
```

Output: `dist\IsoResearchAI\` containing `IsoResearchAI.exe` and an `_internal` folder. Distribute or copy the
**whole folder** (zip it). Users do not need Python. Data still goes to `%APPDATA%\IsoResearchAI`.

Manual equivalent:
```
.venv\Scripts\python.exe -m pip install "pyinstaller>=6.6"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean isoresearch.spec
```

## Notes
- **One-folder** build (not one-file): starts faster and triggers fewer antivirus false positives.
- Size is roughly 400–800 MB depending on installed packages (Qt, SciPy, FAISS, PyMuPDF).
- The optional semantic-embedding stack (torch, sentence-transformers) is **excluded** by default. To bundle it,
  remove `torch`, `sentence_transformers` and `transformers` from `excludes` in `isoresearch.spec` (adds ~1 GB).
  Otherwise the frozen app uses the built-in lexical-hash embeddings.
- Ollama is a separate program and is not bundled; users install it and download a model themselves.
- Tesseract OCR is not bundled; install it separately if OCR is needed.
- The executable is unsigned. For institutional distribution, sign it with `signtool` and a code-signing
  certificate.
- Test the build with: `dist\IsoResearchAI\IsoResearchAI.exe --smoke-test` (opens and closes the window).

The spec file was validated by building and smoke-testing the frozen application on Linux; the Windows build
uses the same spec.

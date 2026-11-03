# PyInstaller spec for IsoResearch AI (one-folder build; faster start-up and fewer antivirus
# false positives than one-file).  Build with:  pyinstaller --noconfirm --clean isoresearch.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (collect_submodules("isoresearch") + collect_submodules("netCDF4") + collect_submodules("cftime")
          + ["PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSvg", "matplotlib.backends.backend_qtagg",
             "openpyxl", "docx", "markdown.extensions.fenced_code", "markdown.extensions.tables",
             "markdown.extensions.sane_lists", "markdown.extensions.nl2br"])

datas = [("isoresearch/resources", "isoresearch/resources"), ("examples", "examples"),
         ("config.example.json", ".")]
datas += collect_data_files("matplotlib", includes=["mpl-data/**"])
datas += collect_data_files("docx")
# PyMuPDF data (and, if the optional pymupdf-layout add-on happens to be installed, its model resources)
datas += collect_data_files("pymupdf")

# Large optional/unused stacks are excluded; remove "torch"/"sentence_transformers" from this list if you
# installed the optional semantic embeddings and want them inside the executable (adds ~1 GB).
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.Qt3DCore", "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
            "IPython", "jupyter", "pytest", "torch", "sentence_transformers", "transformers"]

a = Analysis(["launcher.py"], pathex=["."], binaries=[], datas=datas, hiddenimports=hidden, hookspath=[],
             runtime_hooks=[], excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="IsoResearchAI", debug=False, strip=False, upx=False,
          console=False, icon="isoresearch/resources/icons/isoresearch.ico")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="IsoResearchAI")

"""Built-in PDF viewer (QtPdf) that opens a paper at a cited page.  Falls back
to the system PDF viewer if QtPdf is unavailable."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout

from .widgets.common import button, label

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    HAVE_QTPDF = True
except ImportError:  # pragma: no cover
    HAVE_QTPDF = False


class PdfViewer(QDialog):
    def __init__(self, path: Path, page: int = 1, title: str = "", parent=None, excerpt: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"{title or Path(path).name} — p. {page}")
        self.resize(980, 860)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.path = Path(path)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(label(title or self.path.name, "H2"))
        bar.addStretch(1)
        bar.addWidget(QLabel("Page"))
        self.spin = QSpinBox()
        self.spin.setMinimum(1)
        bar.addWidget(self.spin)
        self.total = QLabel("")
        bar.addWidget(self.total)
        bar.addWidget(button("Zoom −", kind="Ghost", slot=lambda: self._zoom(1 / 1.2)))
        bar.addWidget(button("Zoom +", kind="Ghost", slot=lambda: self._zoom(1.2)))
        bar.addWidget(button("Open in system viewer", "open", slot=self.open_external))
        lay.addLayout(bar)
        if excerpt:
            ex = label(f"Cited passage (p. {page}): “{excerpt[:300]}…”", "Muted", wrap=True)
            lay.addWidget(ex)
        self.doc = QPdfDocument(self)
        self.doc.load(str(self.path))
        self.view = QPdfView(self)
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        lay.addWidget(self.view, 1)
        n = self.doc.pageCount()
        self.spin.setMaximum(max(1, n))
        self.total.setText(f"of {n}")
        self.spin.valueChanged.connect(self.goto)
        self.spin.setValue(min(max(1, page), max(1, n)))
        self.goto(self.spin.value())
        QShortcut(QKeySequence.StandardKey.Close, self, self.close)

    def goto(self, page: int) -> None:
        nav = self.view.pageNavigator()
        nav.jump(max(0, page - 1), QPointF(0, 0), nav.currentZoom())

    def _zoom(self, f: float) -> None:
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() * f)

    def open_external(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))


def open_pdf(parent, path: str, page: int = 1, title: str = "", excerpt: str = "") -> None:
    p = Path(path)
    if not p.exists():
        from .widgets.common import error_box

        error_box(parent, "PDF not found", f"The stored PDF is missing:\n{p}\n\nIt may have been moved or deleted. "
                  "Re-import the paper or restore a backup.")
        return
    if HAVE_QTPDF:
        v = PdfViewer(p, page, title, parent, excerpt)
        v.show()
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

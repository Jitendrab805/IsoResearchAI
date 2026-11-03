"""Bundled line icons (original 24×24 stroke drawings, rendered locally from
inline SVG — no icon fonts or remote assets)."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS: dict[str, str] = {
    "chat-plus": '<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z"/><path d="M12 9v6M9 12h6"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    "library": '<rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9" y="4" width="4" height="16" rx="1"/>'
               '<path d="M15.5 5.2l3.7-1 3 15.6-3.7.9z"/>',
    "review": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M3.5 6l1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2"/>',
    "gap": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/><path d="M8 10.5h5M10.5 8v5"/>',
    "plot": '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/><circle cx="7" cy="15" r=".6"/>',
    "data": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/>',
    "references": '<path d="M6 3h11a1 1 0 0 1 1 1v17l-6.5-4L5 21V4a1 1 0 0 1 1-1z"/><path d="M9 8h6M9 11.5h4"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1'
                'M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "send": '<path d="M4 12l16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5L20 4"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "export": '<path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file-plus": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "refresh": '<path d="M20 11A8 8 0 0 0 5.5 6.5L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8 8 0 0 0 14.5 4.5L21 15"/>'
               '<path d="M21 20v-5h-5"/>',
    "open": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4.5M12 17.5v.2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.2"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/>',
    "filter": '<path d="M4 5h16l-6 7.5V19l-4 2v-8.5z"/>',
    "tag": '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/>'
           '<path d="M9 2.5v3.5M15 2.5v3.5M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "pdf": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
           '<path d="M8.5 16v-4h1.3a1.2 1.2 0 0 1 0 2.4H8.5M13 12v4h.8a2 2 0 0 0 0-4z"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "book-open": '<path d="M3 5.5C5.5 4 8.5 4 12 6c3.5-2 6.5-2 9-.5V19c-2.5-1.5-5.5-1.5-9 .5-3.5-2-6.5-2-9-.5z"/>'
                 '<path d="M12 6v13.5"/>',
}

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#5eead4"/><stop offset="1" stop-color="#0f766e"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="16" fill="#0b1f1d"/>
<path d="M32 10C32 10 16 28 16 39a16 16 0 0 0 32 0C48 28 32 10 32 10z" fill="url(#g)"/>
<ellipse cx="32" cy="39" rx="21" ry="7" fill="none" stroke="#e6fffb" stroke-opacity=".75" stroke-width="2"
 transform="rotate(-25 32 39)"/>
<circle cx="50.5" cy="30.5" r="3" fill="#e6fffb"/>
<circle cx="32" cy="39" r="4.2" fill="#e6fffb"/>
</svg>"""


def _svg(name: str, color: str, stroke: float = 1.7) -> bytes:
    body = PATHS.get(name, PATHS["info"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def _render(data: bytes, size: int) -> QPixmap:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(data)).render(p, QRectF(0, 0, size, size))
    p.end()
    return QPixmap.fromImage(img)


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#8d989e", active: str | None = None, size: int = 40) -> QIcon:
    ic = QIcon()
    ic.addPixmap(_render(_svg(name, color), size), QIcon.Mode.Normal, QIcon.State.Off)
    if active:
        ic.addPixmap(_render(_svg(name, active), size), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_render(_svg(name, active), size), QIcon.Mode.Active, QIcon.State.Off)
    return ic


@lru_cache(maxsize=8)
def logo_pixmap(size: int = 64) -> QPixmap:
    return _render(LOGO_SVG.encode(), size)


def logo_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s))
    return ic

"""Small reusable UI building blocks."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..icons import icon


def label(text: str = "", name: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str = "", ico: str | None = None, kind: str | None = None, tip: str = "",
           color: str = "#8d989e", slot=None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if ico:
        b.setIcon(icon(ico, color))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


class Card(QFrame):
    def __init__(self, parent=None, flat: bool = False, padding: int = 16, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("CardFlat" if flat else "Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(spacing)


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Divider")


class Pill(QLabel):
    def __init__(self, text: str = "", state: str = ""):
        super().__init__(text)
        self.setObjectName("Pill")
        self.set_state(state)

    def set_state(self, state: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", eyebrow: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)
        if eyebrow:
            lay.addWidget(label(eyebrow.upper(), "Eyebrow"))
        lay.addWidget(label(title, "PageTitle"))
        if subtitle:
            lay.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)


class EmptyState(QFrame):
    def __init__(self, ico: str, title: str, text: str, action_text: str = "", color: str = "#5d676d"):
        super().__init__()
        self.setMinimumHeight(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 40, 24, 40)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(icon(ico, color).pixmap(44, 44))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "H2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        d = label(text, "Muted", wrap=True)
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setMaximumWidth(460)
        lay.addWidget(d, 0, Qt.AlignmentFlag.AlignCenter)
        self.action = None
        if action_text:
            self.action = button(action_text, kind="Primary")
            lay.addSpacing(6)
            lay.addWidget(self.action, 0, Qt.AlignmentFlag.AlignCenter)


class Banner(QFrame):
    closed = Signal()

    def __init__(self, text: str = "", kind: str = "warn", ico: str = "alert", color: str = "#f0b44c"):
        super().__init__()
        self.setObjectName("Banner" if kind == "warn" else "BannerInfo")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icon(ico, color).pixmap(18, 18))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        self.text = label(text, wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(False)
        lay.addWidget(self.text, 1)
        self.action_layout = QHBoxLayout()
        lay.addLayout(self.action_layout)

    def set_text(self, t: str) -> None:
        self.text.setText(t)


class Toast(QFrame):
    """Transient non-blocking notification anchored to the bottom of a window."""

    def __init__(self, parent: QWidget, text: str, kind: str = "ok", ms: int = 3200):
        super().__init__(parent)
        self.setObjectName("Toast")
        colors = {"ok": "#4cc98d", "warn": "#f0b44c", "error": "#f2777a", "info": "#2cc5b4"}
        icons_ = {"ok": "check", "warn": "alert", "error": "alert", "info": "info"}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 14, 9)
        ic = QLabel()
        ic.setPixmap(icon(icons_.get(kind, "info"), colors.get(kind, "#2cc5b4")).pixmap(18, 18))
        lay.addWidget(ic)
        t = label(text, wrap=True)
        t.setMaximumWidth(520)
        lay.addWidget(t)
        self.adjustSize()
        pw, ph = parent.width(), parent.height()
        self.move((pw - self.width()) // 2, ph - self.height() - 46)
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self.anim = QPropertyAnimation(eff, b"opacity", self)
        self.anim.setDuration(180)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.show()
        self.raise_()
        self.anim.start()
        QTimer.singleShot(ms, self._fade)

    def _fade(self):
        self.anim.setDirection(QPropertyAnimation.Direction.Backward)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()


def confirm(parent, title: str, text: str, ok: str = "Continue", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    yes = box.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    if danger:
        yes.setObjectName("Danger")
    box.exec()
    return box.clickedButton() is yes


def error_box(parent, title: str, text: str, detail: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setDetailedText(detail)
    box.exec()


def expanding(w: QWidget) -> QWidget:
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return w

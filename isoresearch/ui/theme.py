"""Dark / light themes (QSS built from design tokens).  System fonts only —
no remote fonts are ever loaded."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    warn: str
    danger: str
    ok: str
    user_bubble: str
    code_bg: str
    selection: str


DARK = Palette(
    name="dark", bg="#0e1113", sidebar="#0a0c0e", surface="#14181b", surface2="#1a1f23", surface3="#21272c",
    border="#252b30", border_strong="#323a40", text="#e4e8ea", muted="#8d989e", faint="#5d676d",
    accent="#2cc5b4", accent_hover="#47d6c6", accent_text="#03201d", accent_soft="rgba(44,197,180,0.13)",
    warn="#f0b44c", danger="#f2777a", ok="#4cc98d", user_bubble="#173533", code_bg="#0b0e10",
    selection="#1d4a46")

LIGHT = Palette(
    name="light", bg="#f4f6f7", sidebar="#eceff1", surface="#ffffff", surface2="#f7f9fa", surface3="#eef1f3",
    border="#dfe4e7", border_strong="#cbd2d6", text="#152024", muted="#5b686e", faint="#8a959b",
    accent="#0d7a70", accent_hover="#0a655d", accent_text="#ffffff", accent_soft="rgba(13,122,112,0.10)",
    warn="#b7791f", danger="#c53030", ok="#2f855a", user_bubble="#e3f2f0", code_bg="#f1f4f5",
    selection="#bfe3de")

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Inter", "Noto Sans", "DejaVu Sans", sans-serif'
MONO_STACK = '"Cascadia Code", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", monospace'


def palette(name: str) -> Palette:
    return LIGHT if name == "light" else DARK


def arrow_assets(p: Palette, folder) -> dict:
    """Write tiny chevron SVGs for combo/spin boxes (QSS needs image files) into a local cache folder."""
    from pathlib import Path

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, d in (("down", "M2 4l4 4 4-4"), ("up", "M2 8l4-4 4 4")):
        for tag, col in (("", p.muted), ("_hover", p.accent)):
            f = folder / f"{name}{tag}_{col.strip('#')}.svg"
            if not f.exists():
                f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="{d}" fill="none" '
                             f'stroke="{col}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
                             encoding="utf-8")
            out[name + tag] = f.as_posix()
    f = folder / f"check_{p.accent_text.strip('#')}.svg"
    if not f.exists():
        f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-5" '
                     f'fill="none" stroke="{p.accent_text}" stroke-width="1.8" stroke-linecap="round" '
                     f'stroke-linejoin="round"/></svg>', encoding="utf-8")
    out["check"] = f.as_posix()
    return out


def stylesheet(p: Palette, scale: float = 1.0, arrows: dict | None = None) -> str:
    fs = round(13 * scale)
    arrows = arrows or {}
    down, up = arrows.get("down", ""), arrows.get("up", "")
    down_h, up_h = arrows.get("down_hover", down), arrows.get("up_hover", up)
    check = arrows.get("check", "")
    return f"""
* {{ font-family: {FONT_STACK}; font-size: {fs}px; color: {p.text}; outline: 0; }}
QMainWindow, QDialog, #Workspace {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface3}; color: {p.text}; border: 1px solid {p.border_strong};
            padding: 6px 8px; border-radius: 6px; }}

/* ---------- sidebar ---------- */
#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
#BrandName {{ font-size: {fs + 3}px; font-weight: 650; letter-spacing: 0.2px; }}
#BrandSub {{ color: {p.faint}; font-size: {fs - 2}px; letter-spacing: 1.4px; }}
#NavSection {{ color: {p.faint}; font-size: {fs - 3}px; font-weight: 600; letter-spacing: 1.3px;
               padding: 14px 14px 4px 14px; }}
QPushButton#NavButton {{ text-align: left; padding: 8px 12px; border: none; border-radius: 8px;
    background: transparent; color: {p.muted}; font-weight: 500; }}
QPushButton#NavButton:hover {{ background: {p.surface2}; color: {p.text}; }}
QPushButton#NavButton:checked {{ background: {p.accent_soft}; color: {p.accent}; font-weight: 600; }}
QPushButton#NewChat {{ background: {p.accent}; color: {p.accent_text}; border: none; border-radius: 9px;
    padding: 9px 12px; font-weight: 650; text-align: left; }}
QPushButton#NewChat:hover {{ background: {p.accent_hover}; }}

/* ---------- status pills ---------- */
QLabel#Pill {{ border-radius: 10px; padding: 3px 9px; font-size: {fs - 2}px; font-weight: 600;
    background: {p.surface3}; color: {p.muted}; }}
QLabel#Pill[state="ok"] {{ background: rgba(76,201,141,0.14); color: {p.ok}; }}
QLabel#Pill[state="warn"] {{ background: rgba(240,180,76,0.14); color: {p.warn}; }}
QLabel#Pill[state="error"] {{ background: rgba(242,119,122,0.14); color: {p.danger}; }}
QLabel#Pill[state="accent"] {{ background: {p.accent_soft}; color: {p.accent}; }}

/* ---------- typography ---------- */
QLabel#PageTitle {{ font-size: {fs + 9}px; font-weight: 650; letter-spacing: -0.2px; }}
QLabel#PageSubtitle {{ color: {p.muted}; font-size: {fs}px; }}
QLabel#H2 {{ font-size: {fs + 2}px; font-weight: 650; }}
QLabel#Muted {{ color: {p.muted}; }}
QLabel#Faint {{ color: {p.faint}; font-size: {fs - 1}px; }}
QLabel#Eyebrow {{ color: {p.accent}; font-size: {fs - 3}px; font-weight: 700; letter-spacing: 1.4px; }}
QLabel#Hero {{ font-size: {fs + 17}px; font-weight: 650; letter-spacing: -0.6px; }}
QLabel#Warning {{ color: {p.warn}; }}
QLabel#Error {{ color: {p.danger}; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#CardFlat {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#Suggestion {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#Suggestion:hover {{ border-color: {p.accent}; background: {p.surface2}; }}
QFrame#Banner {{ background: rgba(240,180,76,0.10); border: 1px solid rgba(240,180,76,0.35); border-radius: 10px; }}
QFrame#BannerInfo {{ background: {p.accent_soft}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}
#ContextPanel {{ background: {p.surface}; border-left: 1px solid {p.border}; }}

/* ---------- chat ---------- */
QFrame#UserBubble {{ background: {p.user_bubble}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#AssistantBubble {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#ErrorBubble {{ background: rgba(242,119,122,0.08); border: 1px solid rgba(242,119,122,0.4); border-radius: 12px; }}
QFrame#Composer {{ background: {p.surface}; border: 1px solid {p.border_strong}; border-radius: 16px; }}
QFrame#Composer[focus="true"] {{ border-color: {p.accent}; }}
QTextBrowser, QTextBrowser#Markdown {{ background: transparent; border: none; selection-background-color: {p.selection}; }}
QPlainTextEdit#ComposerInput {{ background: transparent; border: none; font-size: {fs + 1}px; }}
QFrame#SourceCard {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px; }}
QFrame#SourceCard:hover {{ border-color: {p.accent}; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px 9px;
    selection-background-color: {p.selection}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {p.accent}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {p.faint}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; margin-right: 8px; }}
QComboBox::down-arrow:hover {{ image: url("{down_h}"); }}
QAbstractSpinBox {{ padding-right: 20px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 18px; border: none;
    background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url("{up}"); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url("{down}"); width: 9px; height: 9px; }}
QAbstractSpinBox::up-arrow:hover {{ image: url("{up_h}"); }}
QAbstractSpinBox::down-arrow:hover {{ image: url("{down_h}"); }}
QComboBox QAbstractItemView {{ background: {p.surface2}; border: 1px solid {p.border_strong};
    selection-background-color: {p.accent_soft}; selection-color: {p.text}; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p.border_strong};
    background: {p.surface2}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}
QListView::indicator, QTableView::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {p.border_strong}; background: {p.surface2}; }}
QListView::indicator:checked, QTableView::indicator:checked {{ background: {p.accent}; border-color: {p.accent};
    image: url("{check}"); }}

/* ---------- buttons ---------- */
QPushButton {{ background: {p.surface3}; border: 1px solid {p.border}; border-radius: 8px; padding: 7px 13px;
    font-weight: 550; }}
QPushButton:hover {{ border-color: {p.border_strong}; background: {p.surface2}; }}
QPushButton:pressed {{ background: {p.surface}; }}
QPushButton:disabled {{ color: {p.faint}; background: {p.surface2}; }}
QPushButton#Primary {{ background: {p.accent}; color: {p.accent_text}; border: none; font-weight: 650; }}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#Primary:disabled {{ background: {p.surface3}; color: {p.faint}; }}
QPushButton#Danger {{ background: transparent; color: {p.danger}; border: 1px solid rgba(242,119,122,0.45); }}
QPushButton#Danger:hover {{ background: rgba(242,119,122,0.10); }}
QPushButton#Ghost, QToolButton#Ghost {{ background: transparent; border: none; color: {p.muted}; padding: 5px 8px;
    border-radius: 7px; }}
QPushButton#Ghost:hover, QToolButton#Ghost:hover {{ background: {p.surface3}; color: {p.text}; }}
QPushButton#Send {{ background: {p.accent}; border: none; border-radius: 10px; min-width: 36px; min-height: 36px; }}
QPushButton#Send:hover {{ background: {p.accent_hover}; }}
QPushButton#Send:disabled {{ background: {p.surface3}; }}
QPushButton#Stop {{ background: {p.surface3}; border: 1px solid {p.border_strong}; border-radius: 10px;
    min-width: 36px; min-height: 36px; }}
QPushButton#Chip {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 13px; padding: 4px 11px;
    color: {p.muted}; font-weight: 500; }}
QPushButton#Chip:hover {{ border-color: {p.accent}; color: {p.text}; }}
QPushButton#Chip:checked {{ background: {p.accent_soft}; border-color: {p.accent}; color: {p.accent}; }}
QPushButton#Link {{ background: transparent; border: none; color: {p.accent}; padding: 2px 4px; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}

/* ---------- tables / lists ---------- */
QTableView, QTableWidget, QTreeView, QListView, QListWidget {{ background: {p.surface}; border: 1px solid {p.border};
    border-radius: 10px; gridline-color: {p.border}; alternate-background-color: {p.surface2};
    selection-background-color: {p.accent_soft}; selection-color: {p.text}; }}
QListWidget::item, QListView::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {p.surface2}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QHeaderView::section {{ background: {p.surface2}; color: {p.muted}; border: none; border-bottom: 1px solid {p.border};
    border-right: 1px solid {p.border}; padding: 6px 8px; font-weight: 600; font-size: {fs - 1}px; }}
QTableCornerButton::section {{ background: {p.surface2}; border: none; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 10px; top: -1px; background: {p.surface}; }}
QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 550; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom-color: {p.accent}; }}
QTabBar::tab:hover {{ color: {p.text}; }}

/* ---------- scrollbars ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: {p.surface3}; border: none; border-radius: 3px; height: 6px; text-align: center;
    color: transparent; max-height: 6px; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {p.sidebar}; border-top: 1px solid {p.border}; color: {p.muted}; }}
QStatusBar QLabel {{ color: {p.muted}; font-size: {fs - 1}px; }}
QMenu {{ background: {p.surface2}; border: 1px solid {p.border_strong}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QGroupBox {{ border: 1px solid {p.border}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px;
    background: {p.surface}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p.muted}; }}
#Toast {{ background: {p.surface3}; border: 1px solid {p.border_strong}; border-radius: 10px; }}
"""


def markdown_css(p: Palette) -> str:
    return f"""
body {{ color: {p.text}; line-height: 150%; }}
p {{ margin: 0 0 8px 0; }}
h1 {{ font-size: 18px; margin: 10px 0 6px 0; }} h2 {{ font-size: 16px; margin: 10px 0 6px 0; }}
h3 {{ font-size: 14px; margin: 8px 0 4px 0; }}
a {{ color: {p.accent}; text-decoration: none; }}
a.cite {{ color: {p.accent}; font-weight: 600; }}
code {{ font-family: {MONO_STACK}; background-color: {p.code_bg}; color: {p.text}; }}
pre {{ font-family: {MONO_STACK}; background-color: {p.code_bg}; padding: 10px; margin: 2px 0 10px 0;
       border: 1px solid {p.border}; }}
blockquote {{ color: {p.warn}; margin: 6px 0 8px 0; padding-left: 10px; border-left: 3px solid {p.warn}; }}
table {{ border-collapse: collapse; margin: 6px 0 10px 0; }}
th {{ background-color: {p.surface3}; padding: 5px 8px; border: 1px solid {p.border}; }}
td {{ padding: 5px 8px; border: 1px solid {p.border}; }}
span.invalid {{ color: {p.danger}; font-weight: 600; }}
a.copy {{ color: {p.faint}; font-size: 11px; }}
li {{ margin-bottom: 3px; }}
"""


def qpalette(p: Palette):
    """Matching QPalette so widgets without explicit QSS (scroll-area viewports, dialogs) follow the theme."""
    from PySide6.QtGui import QColor, QPalette

    qp = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.bg, QPalette.ColorRole.WindowText: p.text, QPalette.ColorRole.Base: p.surface,
        QPalette.ColorRole.AlternateBase: p.surface2, QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.Button: p.surface3, QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.ToolTipBase: p.surface3, QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.Highlight: p.selection, QPalette.ColorRole.HighlightedText: p.text,
        QPalette.ColorRole.PlaceholderText: p.faint, QPalette.ColorRole.Link: p.accent,
        QPalette.ColorRole.BrightText: p.accent, QPalette.ColorRole.Mid: p.border, QPalette.ColorRole.Dark: p.sidebar,
    }
    for role, col in roles.items():
        qp.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        qp.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.faint))
    return qp

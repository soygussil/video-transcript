"""Temas claro y oscuro con tokens de color fijos (contraste AA en texto principal)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

PALETTES: dict[str, dict[str, str]] = {
    "claro": {
        "bg": "#F5F6F8",
        "surface": "#FFFFFF",
        "surface_alt": "#EEF1F5",
        "text": "#1B1F24",
        "muted": "#4B5563",
        "border": "#C9CED6",
        "accent": "#0F5CC0",
        "accent_text": "#FFFFFF",
        "focus": "#E07A00",
        "danger": "#B42318",
        "danger_bg": "#FDECEA",
        "warning": "#8A5300",
        "warning_bg": "#FFF4E0",
        "success": "#1E7B34",
        "selection": "#D6E4FA",
        "nav": "#E9EDF3",
    },
    "oscuro": {
        "bg": "#16181D",
        "surface": "#1F232A",
        "surface_alt": "#272C35",
        "text": "#ECEFF4",
        "muted": "#B4BCC8",
        "border": "#3A414D",
        "accent": "#5B9BFF",
        "accent_text": "#0B1220",
        "focus": "#FFB347",
        "danger": "#FF8A80",
        "danger_bg": "#3A1E1E",
        "warning": "#FFCC80",
        "warning_bg": "#3A2E1A",
        "success": "#7CD992",
        "selection": "#2D3E5C",
        "nav": "#1A1D23",
    },
}

QSS = """
QWidget {{ background: {bg}; color: {text}; font-size: 10.5pt; }}
QFrame#Card, QFrame#DropZone, QGroupBox {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; }}
QFrame#DropZone {{ border: 2px dashed {border}; min-height: 150px; }}
QFrame#DropZone[active="true"] {{ border-color: {accent}; background: {selection}; }}
QFrame#DropZone:focus {{ border: 2px solid {focus}; }}
QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 17pt; font-weight: 600; }}
QLabel#Subtitle, QLabel#Muted {{ color: {muted}; }}
QLabel#Section {{ font-size: 12pt; font-weight: 600; }}
QListWidget#Nav {{ background: {nav}; border: none; padding: 8px; font-size: 11pt; }}
QListWidget#Nav::item {{ padding: 10px 12px; border-radius: 6px; margin: 2px 0; }}
QListWidget#Nav::item:selected {{ background: {selection}; color: {text}; font-weight: 600; }}
QListWidget#Nav::item:hover {{ background: {surface_alt}; }}
QListWidget#Nav:focus {{ border: 2px solid {focus}; }}
QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: {surface_alt}; }}
QPushButton:focus {{ border: 2px solid {focus}; }}
QPushButton:disabled {{ color: {muted}; background: {surface_alt}; border-style: dashed; }}
QPushButton#Primary {{ background: {accent}; color: {accent_text}; border: 1px solid {accent}; font-weight: 600;
    padding: 9px 20px; }}
QPushButton#Primary:hover {{ border: 2px solid {text}; }}
QPushButton#Primary:focus {{ border: 2px solid {focus}; }}
QPushButton#Primary:disabled {{ background: {surface_alt}; color: {muted}; border: 1px dashed {border}; }}
QPushButton#Danger {{ color: {danger}; border-color: {danger}; }}
QPushButton#Link {{ border: none; color: {accent}; text-decoration: underline; padding: 2px 4px; }}
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {{ background: {surface}; border: 1px solid {border};
    border-radius: 6px; padding: 5px; selection-background-color: {selection}; selection-color: {text}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTableWidget:focus, QListWidget:focus {{
    border: 2px solid {focus}; }}
QHeaderView::section {{ background: {surface_alt}; color: {text}; border: none; border-bottom: 1px solid {border};
    padding: 6px; font-weight: 600; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {selection}; color: {text}; }}
QProgressBar {{ background: {surface_alt}; border: 1px solid {border}; border-radius: 5px; text-align: center;
    min-height: 18px; color: {text}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
QRadioButton:focus, QCheckBox:focus {{ color: {accent}; text-decoration: underline; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid {muted};
    background: {surface}; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator:checked {{ background: {accent}; border: 4px solid {surface}; border-radius: 10px; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QRadioButton::indicator:focus, QCheckBox::indicator:focus {{ border-color: {focus}; }}
QFrame#ErrorBanner {{ background: {danger_bg}; border: 1px solid {danger}; border-radius: 8px; }}
QFrame#WarningBanner {{ background: {warning_bg}; border: 1px solid {warning}; border-radius: 8px; }}
QLabel#ErrorTitle {{ color: {danger}; font-weight: 600; }}
QLabel#WarningText {{ color: {warning}; }}
QLabel#Ok {{ color: {success}; }}
QStatusBar {{ background: {nav}; }}
"""


def apply_theme(app: QApplication, name: str) -> None:
    tokens = PALETTES.get(name, PALETTES["claro"])
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface",
        QPalette.ColorRole.AlternateBase: "surface_alt",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "surface",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.Highlight: "selection",
        QPalette.ColorRole.HighlightedText: "text",
        QPalette.ColorRole.PlaceholderText: "muted",
        QPalette.ColorRole.ToolTipBase: "surface",
        QPalette.ColorRole.ToolTipText: "text",
    }
    for role, token in roles.items():
        palette.setColor(role, QColor(tokens[token]))
    app.setPalette(palette)
    font = QFont("Segoe UI")
    font.setPointSizeF(10.5)
    app.setFont(font)
    app.setStyleSheet(QSS.format(**tokens))
    app.setProperty("theme", name)

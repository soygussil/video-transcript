"""Widgets reutilizables: zona de arrastre y aviso en línea con detalles técnicos plegables."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from analizador_video.domain.errors import UserMessage
from analizador_video.ui import strings as T


def label(text: str, object_name: str | None = None, wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if object_name:
        widget.setObjectName(object_name)
    return widget


class DropZone(QFrame):
    """Zona de arrastrar y soltar accesible con teclado (Entrar/Espacio abre el selector)."""

    fileDropped = Signal(Path)
    browseRequested = Signal()

    def __init__(self, extensions: frozenset[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.extensions = extensions
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(T.DROP_ACCESSIBLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.addStretch(1)
        self.title = label(T.DROP_TITLE, "Section")
        self.hint = label(T.DROP_HINT, "Muted")
        self.selected = label("")
        for widget in (self.title, self.hint, self.selected):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(widget)
        layout.addStretch(1)

    def set_selected(self, path: Path | None) -> None:
        self.selected.setText(f"Seleccionado: {path.name}" if path else "")
        self.selected.setToolTip(str(path) if path else "")

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _accepted(self, event: QDragEnterEvent | QDropEvent) -> Path | None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        return path if path.suffix.lower() in self.extensions else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepted(event):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        path = self._accepted(event)
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.browseRequested.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.browseRequested.emit()
        else:
            super().keyPressEvent(event)


class MessageBanner(QFrame):
    """Mensaje en línea (sin diálogo modal) con detalles técnicos plegables."""

    def __init__(self, kind: str = "error", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ErrorBanner" if kind == "error" else "WarningBanner")
        layout = QVBoxLayout(self)
        self.title = label("", "ErrorTitle" if kind == "error" else "WarningText")
        self.body = label("")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        self.details.setAccessibleName(T.DETAILS_SHOW)
        self.details.hide()
        row = QHBoxLayout()
        self.toggle = QPushButton(T.DETAILS_SHOW)
        self.toggle.setObjectName("Link")
        self.toggle.clicked.connect(self._toggle)
        row.addWidget(self.toggle)
        row.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addLayout(row)
        layout.addWidget(self.details)
        self.hide()

    def show_message(self, message: UserMessage) -> None:
        self.title.setText(message.what.rstrip(".") + ".")
        parts = [message.affected.rstrip(".") + "."] if message.affected else []
        if message.saved:
            parts.append(T.SAVED_YES)
        if message.action:
            parts.append(message.action.rstrip(".") + ".")
        self.body.setText(" ".join(parts))
        self.details.setPlainText(message.details or "")
        self.toggle.setVisible(bool(message.details))
        self.details.hide()
        self.toggle.setText(T.DETAILS_SHOW)
        self.setAccessibleName(message.text())
        self.show()

    def show_text(self, title: str, body: str = "") -> None:
        self.show_message(UserMessage("aviso", title, "", None, ""))
        self.body.setText(body)

    def _toggle(self) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.toggle.setText(T.DETAILS_HIDE if visible else T.DETAILS_SHOW)

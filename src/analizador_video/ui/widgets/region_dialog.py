"""Diálogo para elegir el área de captura sobre una vista previa del video (arrastrar, mover y redimensionar)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QSlider, QVBoxLayout, QWidget

from analizador_video.infrastructure.video.region import MIN_SIDE, Region, read_preview
from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import label

HANDLE = 9  # radio (px) de las asas de las esquinas y los bordes


def _to_pixmap(frame: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    height, width = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy())


class RegionSelector(QWidget):
    """Muestra el fotograma y un rectángulo editable; la región se expresa en fracciones 0–1 del fotograma."""

    regionChanged = Signal(object)

    def __init__(self, region: Region, parent: QWidget | None = None):
        super().__init__(parent)
        self.pixmap: QPixmap | None = None
        self.region = region.clamped()
        self._drag: tuple[str, QPointF, Region] | None = None
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setAccessibleName(T.REGION_ACCESSIBLE)

    def set_frame(self, frame: np.ndarray) -> None:
        self.pixmap = _to_pixmap(frame)
        self.update()

    def set_region(self, region: Region) -> None:
        self.region = region.clamped()
        self.update()
        self.regionChanged.emit(self.region)

    def _image_rect(self) -> QRectF:
        if self.pixmap is None:
            return QRectF(self.rect())
        scale = min(self.width() / self.pixmap.width(), self.height() / self.pixmap.height())
        w, h = self.pixmap.width() * scale, self.pixmap.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _region_rect(self) -> QRectF:
        image, r = self._image_rect(), self.region
        return QRectF(
            image.x() + r.x * image.width(), image.y() + r.y * image.height(), r.w * image.width(), r.h * image.height()
        )

    def _hit(self, pos: QPointF) -> str:
        rect = self._region_rect()
        near_left, near_right = abs(pos.x() - rect.left()) <= HANDLE, abs(pos.x() - rect.right()) <= HANDLE
        near_top, near_bottom = abs(pos.y() - rect.top()) <= HANDLE, abs(pos.y() - rect.bottom()) <= HANDLE
        inside_x = rect.left() - HANDLE <= pos.x() <= rect.right() + HANDLE
        inside_y = rect.top() - HANDLE <= pos.y() <= rect.bottom() + HANDLE
        edges = ("t" if near_top and inside_x else "b" if near_bottom and inside_x else "") + (
            "l" if near_left and inside_y else "r" if near_right and inside_y else ""
        )
        if edges:
            return edges
        return "move" if rect.contains(pos) else "new"

    _CURSORS: ClassVar[dict[str, Qt.CursorShape]] = {
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
        "move": Qt.CursorShape.SizeAllCursor,
        "new": Qt.CursorShape.CrossCursor,
    }

    def _norm(self, pos: QPointF) -> tuple[float, float]:
        image = self._image_rect()
        return (
            min(max((pos.x() - image.x()) / image.width(), 0.0), 1.0),
            min(max((pos.y() - image.y()) / image.height(), 0.0), 1.0),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.pixmap is None:
            return
        pos = event.position()
        mode = self._hit(pos)
        if mode == "new":
            x, y = self._norm(pos)
            self.region = Region(x, y, MIN_SIDE, MIN_SIDE)
            mode = "br"
        self._drag = (mode, pos, self.region)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._drag is None:
            self.setCursor(self._CURSORS[self._hit(pos)])
            return
        mode, start, origin = self._drag
        image = self._image_rect()
        dx, dy = (pos.x() - start.x()) / image.width(), (pos.y() - start.y()) / image.height()
        left, top, right, bottom = origin.x, origin.y, origin.x + origin.w, origin.y + origin.h
        if mode == "move":
            left = min(max(0.0, left + dx), 1.0 - origin.w)
            top = min(max(0.0, top + dy), 1.0 - origin.h)
            right, bottom = left + origin.w, top + origin.h
        else:
            if "l" in mode:
                left = min(max(0.0, left + dx), right - MIN_SIDE)
            if "r" in mode:
                right = max(min(1.0, right + dx), left + MIN_SIDE)
            if "t" in mode:
                top = min(max(0.0, top + dy), bottom - MIN_SIDE)
            if "b" in mode:
                bottom = max(min(1.0, bottom + dy), top + MIN_SIDE)
        self.region = Region(left, top, right - left, bottom - top)
        self.update()
        self.regionChanged.emit(self.region)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag = None

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image = self._image_rect()
        if self.pixmap is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, T.REGION_NO_PREVIEW)
            return
        painter.drawPixmap(image.toRect(), self.pixmap)
        rect = self._region_rect()
        shade = QColor(0, 0, 0, 140)
        painter.fillRect(QRectF(image.left(), image.top(), image.width(), rect.top() - image.top()), shade)
        painter.fillRect(QRectF(image.left(), rect.bottom(), image.width(), image.bottom() - rect.bottom()), shade)
        painter.fillRect(QRectF(image.left(), rect.top(), rect.left() - image.left(), rect.height()), shade)
        painter.fillRect(QRectF(rect.right(), rect.top(), image.right() - rect.right(), rect.height()), shade)
        painter.setPen(QPen(QColor("#2f9bff"), 2))
        painter.drawRect(rect)
        painter.setBrush(QColor("#2f9bff"))
        for cx in (rect.left(), rect.center().x(), rect.right()):
            for cy in (rect.top(), rect.center().y(), rect.bottom()):
                if (cx, cy) != (rect.center().x(), rect.center().y()):
                    painter.drawRect(QRectF(cx - 4, cy - 4, 8, 8))


class RegionDialog(QDialog):
    def __init__(self, video: Path, region: Region, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(T.REGION_TITLE)
        self.video = video
        self.selector = RegionSelector(region)
        self.selector.regionChanged.connect(self._update_info)
        layout = QVBoxLayout(self)
        layout.addWidget(label(T.REGION_HELP, "Muted"))
        layout.addWidget(self.selector, 1)
        self.info = label("", "Muted")
        layout.addWidget(self.info)

        scrub = QHBoxLayout()
        scrub.addWidget(label(T.REGION_MOMENT, wrap=False))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(10)
        self.slider.setAccessibleName(T.REGION_MOMENT)
        self.slider.sliderReleased.connect(self._load_preview)
        self.slider.valueChanged.connect(lambda _v: None if self.slider.isSliderDown() else self._load_preview())
        scrub.addWidget(self.slider, 1)
        layout.addLayout(scrub)

        full = QPushButton(T.REGION_FULL)
        full.clicked.connect(lambda: self.selector.set_region(Region()))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(T.REGION_USE)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(T.REGION_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(full)
        row.addStretch(1)
        row.addWidget(buttons)
        layout.addLayout(row)
        self.resize(820, 560)
        self._load_preview()
        self._update_info(self.selector.region)

    def _load_preview(self) -> None:
        frame = read_preview(self.video, self.slider.value() / 100)
        if frame is not None:
            self.selector.set_frame(frame)

    def _update_info(self, region: Region) -> None:
        self.info.setText(T.REGION_INFO_FULL if region.is_full else T.REGION_INFO.format(w=region.w, h=region.h))

    def region(self) -> Region:
        return self.selector.region

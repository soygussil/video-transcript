"""Área de captura: recorte rectangular (coordenadas relativas 0–1) aplicado antes de detectar y guardar capturas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from analizador_video.infrastructure.fileio import atomic_write_bytes
from analizador_video.infrastructure.video.probe import open_capture

REGION_FILE = "region.json"
MIN_SIDE = 0.05  # fracción mínima por lado para que el recorte siga siendo útil


@dataclass(frozen=True)
class Region:
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    @property
    def is_full(self) -> bool:
        return self.x <= 0.001 and self.y <= 0.001 and self.w >= 0.999 and self.h >= 0.999

    def clamped(self) -> Region:
        w, h = min(1.0, max(MIN_SIDE, self.w)), min(1.0, max(MIN_SIDE, self.h))
        return Region(min(max(0.0, self.x), 1.0 - w), min(max(0.0, self.y), 1.0 - h), w, h)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        if self.is_full:
            return frame
        height, width = frame.shape[:2]
        x0, y0 = round(self.x * width), round(self.y * height)
        x1, y1 = round((self.x + self.w) * width), round((self.y + self.h) * height)
        x1, y1 = max(x1, x0 + 16), max(y1, y0 + 16)
        return frame[y0:y1, x0:x1]


def save_region(root: Path, region: Region) -> None:
    path = root / REGION_FILE
    if region.is_full:
        path.unlink(missing_ok=True)
        return
    data = json.dumps({"x": region.x, "y": region.y, "w": region.w, "h": region.h})
    atomic_write_bytes(path, data.encode("utf-8"))


def load_region(root: Path) -> Region:
    try:
        raw = json.loads((root / REGION_FILE).read_text(encoding="utf-8"))
        return Region(float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"])).clamped()
    except (OSError, ValueError, KeyError, TypeError):
        return Region()


def read_preview(video: Path, fraction: float) -> np.ndarray | None:
    """Fotograma del video en `fraction` (0–1) de su duración, para la vista previa; None si no se puede leer."""
    try:
        capture = open_capture(video)
    except Exception:
        return None
    try:
        total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if total and total > 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(total * min(max(fraction, 0.0), 0.99)))
        ok, frame = capture.read()
        return frame if ok else None
    finally:
        capture.release()

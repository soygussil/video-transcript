"""OCR desacoplado. EasyOCR se usa en CPU: su aceleración depende de PyTorch CUDA, no de Intel."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import BackendUnavailableError, ModelNotAvailableError
from analizador_video.domain.models import OcrBlock


class LoadedOcr(Protocol):
    backend: str
    device: DeviceKind

    def recognize(self, image: np.ndarray) -> list[OcrBlock]: ...


class OcrBackend(Protocol):
    name: str

    def is_installed(self) -> bool: ...

    def supported_devices(self) -> tuple[DeviceKind, ...]: ...

    def models_available(self, languages: Sequence[str]) -> bool: ...

    def load(self, languages: Sequence[str], device: DeviceKind, allow_download: bool) -> LoadedOcr: ...


def read_image(path: Path) -> np.ndarray:
    """Lee imágenes con rutas Unicode (cv2.imread falla con ellas en Windows)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        raise ValueError("La imagen no se pudo decodificar.")
    return image


def preprocess(image: np.ndarray, steps: Sequence[str]) -> np.ndarray:
    """Aplica sólo los filtros configurados, en orden fijo."""
    result = image
    if "escalado" in steps:
        result = cv2.resize(result, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    if {"escala_grises", "contraste", "umbral"} & set(steps) and result.ndim == 3:
        result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    if "contraste" in steps:
        result = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(result)
    if "nitidez" in steps:
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        result = cv2.filter2D(result, -1, kernel)
    if "umbral" in steps:
        result = cv2.adaptiveThreshold(result, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
    return result


def sort_reading_order(blocks: list[OcrBlock], line_height: float = 15.0) -> list[OcrBlock]:
    """Orden de lectura del original: por renglón aproximado y luego de izquierda a derecha."""

    def key(block: OcrBlock) -> tuple[int, float]:
        ys = [p[1] for p in block.box] or [0.0]
        xs = [p[0] for p in block.box] or [0.0]
        return (round(min(ys) / line_height), min(xs))

    return sorted(blocks, key=key)


class _EasyOcrReader:
    backend = "easyocr"

    def __init__(self, reader: Any):
        self._reader = reader
        self.device = DeviceKind.CPU

    def recognize(self, image: np.ndarray) -> list[OcrBlock]:
        return [
            OcrBlock(str(text), round(float(conf), 4), tuple((float(p[0]), float(p[1])) for p in box))
            for box, text, conf in self._reader.readtext(image)
        ]


class EasyOcrBackend:
    name = "easyocr"

    def __init__(self, models_root: Path):
        self.models_root = models_root / "easyocr"

    def is_installed(self) -> bool:
        return importlib.util.find_spec("easyocr") is not None

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return (DeviceKind.CPU,)

    def models_available(self, languages: Sequence[str]) -> bool:
        if not self.models_root.exists():
            return False
        names = {p.name for p in self.models_root.glob("*.pth")}
        return "craft_mlt_25k.pth" in names and len(names) >= 2

    def load(self, languages: Sequence[str], device: DeviceKind, allow_download: bool) -> LoadedOcr:
        if not self.is_installed():
            raise BackendUnavailableError(
                "El motor OCR (EasyOCR) no está instalado",
                "Las capturas no tendrán texto visible reconocido",
                "Instala el componente opcional de OCR desde la guía de Diagnóstico",
                saved=True,
            )
        if not allow_download and not self.models_available(languages):
            raise ModelNotAvailableError(
                "Los modelos de OCR no están descargados",
                "Las capturas no tendrán texto visible reconocido",
                "Descárgalos con 'analizador-video modelos descargar --ocr'",
                saved=True,
            )
        import easyocr

        self.models_root.mkdir(parents=True, exist_ok=True)
        try:
            reader = easyocr.Reader(
                list(languages),
                gpu=False,
                model_storage_directory=str(self.models_root),
                download_enabled=allow_download,
                verbose=False,
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise ModelNotAvailableError(
                "No se pudieron cargar los modelos de OCR",
                "Las capturas no tendrán texto visible reconocido",
                "Verifica los modelos en Diagnóstico",
                saved=True,
                details=type(error).__name__,
            ) from error
        return _EasyOcrReader(reader)

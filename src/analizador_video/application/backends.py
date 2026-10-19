"""Registro de backends. Permite inyectar dobles de prueba sin modelos reales."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from analizador_video.infrastructure.hardware.compatibility import CompatibilityStore
from analizador_video.infrastructure.ocr.backends import EasyOcrBackend, OcrBackend
from analizador_video.infrastructure.ocr.openvino_backend import RapidOcrOpenVinoBackend
from analizador_video.infrastructure.paths import app_home, models_dir
from analizador_video.infrastructure.transcription.backends import (
    FasterWhisperBackend,
    OpenVinoWhisperBackend,
    TranscriptionBackend,
)

COMPAT_FILE = "compatibilidad.json"


@dataclass
class BackendRegistry:
    transcription: dict[str, TranscriptionBackend] = field(default_factory=dict)
    ocr: dict[str, OcrBackend] = field(default_factory=dict)
    compatibility: CompatibilityStore | None = None
    runtime_version: str | None = None

    @classmethod
    def default(cls, models_root: Path | None = None) -> BackendRegistry:
        root = models_root or models_dir()
        try:
            runtime: str | None = version("openvino")
        except PackageNotFoundError:
            runtime = None
        return cls(
            transcription={"openvino": OpenVinoWhisperBackend(root), "faster_whisper": FasterWhisperBackend(root)},
            ocr={"rapidocr_openvino": RapidOcrOpenVinoBackend(root), "easyocr": EasyOcrBackend(root)},
            compatibility=CompatibilityStore(app_home() / COMPAT_FILE),
            runtime_version=runtime,
        )

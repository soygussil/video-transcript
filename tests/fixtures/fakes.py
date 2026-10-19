"""Dobles de prueba de backends (sin modelos reales)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import BackendUnavailableError, OperationCancelled
from analizador_video.domain.models import OcrBlock
from analizador_video.infrastructure.transcription.backends import LoadedTranscriber, RawSegment


@dataclass
class FakeOcrReader:
    backend: str = "fake_ocr"
    device: DeviceKind = DeviceKind.CPU
    calls: int = 0
    fail_on: set[int] = field(default_factory=set)

    def recognize(self, image: np.ndarray) -> list[OcrBlock]:
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("fallo simulado")
        box = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        return [OcrBlock("Botón Guardar", 0.95, box), OcrBlock("ruido", 0.1, box)]


@dataclass
class FakeOcrBackend:
    name: str = "fake_ocr"
    installed: bool = True
    models: bool = True
    reader: FakeOcrReader = field(default_factory=FakeOcrReader)

    def is_installed(self) -> bool:
        return self.installed

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return (DeviceKind.CPU,)

    def models_available(self, languages: Sequence[str]) -> bool:
        return self.models

    def load(self, languages: Sequence[str], device: DeviceKind, allow_download: bool) -> FakeOcrReader:
        if not self.installed:
            raise BackendUnavailableError("OCR simulado no instalado", "Sin OCR", "Instálalo", saved=True)
        return self.reader


@dataclass
class FakeTranscriber:
    backend: str
    device: DeviceKind
    precision: str = "int8"
    fail: bool = False

    def transcribe(
        self, audio: np.ndarray, language: str, offset_seconds: float, is_cancelled: Callable[[], bool]
    ) -> list[RawSegment]:
        if is_cancelled():
            raise OperationCancelled()
        if self.fail:
            raise RuntimeError("fallo del dispositivo simulado")
        return [RawSegment(offset_seconds + 0.5, offset_seconds + 1.5, f"texto {self.device.value}", 0.9)]


@dataclass
class FakeTranscriptionBackend:
    name: str
    devices: tuple[DeviceKind, ...]
    installed: bool = True
    model: bool = True
    failing_devices: set[DeviceKind] = field(default_factory=set)
    load_failures: set[DeviceKind] = field(default_factory=set)

    def is_installed(self) -> bool:
        return self.installed

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return self.devices

    def model_available(self, model: str) -> bool:
        return self.model

    def load(self, model: str, device: DeviceKind, allow_download: bool) -> LoadedTranscriber:
        if device in self.load_failures:
            raise BackendUnavailableError(
                f"No compila en {device.value}", "Ese dispositivo no se usará", "Se usará el siguiente"
            )
        return FakeTranscriber(self.name, device, fail=device in self.failing_devices)


class CountingToken:
    """Cancela después de `after` consultas (cancelación determinista)."""

    def __init__(self, after: int | None = None):
        self.after = after
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.after is not None and self.checks > self.after

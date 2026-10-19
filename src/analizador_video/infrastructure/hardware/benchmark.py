"""BenchmarkService: prueba real de cada combinación (cargar, compilar, inferir, validar, medir).

Se ejecuta en el proceso worker y sólo por solicitud explícita. Entradas sintéticas (tono e imagen
con texto generado): no usa contenido de proyectos ni guarda contenido sensible en métricas.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import NPU_MODEL_INCOMPATIBLE, NPU_OCR_INCOMPATIBLE, AppError, OperationCancelled
from analizador_video.infrastructure.hardware.compatibility import (
    COMPATIBLE,
    NOT_COMPATIBLE,
    NOT_VERIFIED,
    CompatibilityRecord,
)
from analizador_video.infrastructure.ocr.backends import OcrBackend
from analizador_video.infrastructure.transcription.backends import RawSegment, TranscriptionBackend


def _npu_reason(case: BenchmarkCase) -> str | None:
    if case.device is not DeviceKind.NPU:
        return None
    return NPU_OCR_INCOMPATIBLE if case.task == "ocr" else NPU_MODEL_INCOMPATIBLE


def _rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return round(psutil.Process().memory_info().rss / 2**20, 1)


def synthetic_audio(seconds: float = 3.0, rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    return (0.05 * np.sin(2 * math.pi * 220 * t)).astype(np.float32)


def synthetic_text_image() -> np.ndarray:
    image = np.full((120, 480, 3), 255, np.uint8)
    cv2.putText(image, "PRUEBA OCR 123", (12, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
    return image


def _valid_segments(segments: object) -> bool:
    return isinstance(segments, list) and all(
        isinstance(s, RawSegment) and math.isfinite(s.start) and math.isfinite(s.end) and s.end >= s.start
        for s in segments
    )


@dataclass(frozen=True)
class BenchmarkCase:
    task: str
    backend: str
    model: str
    device: DeviceKind


class BenchmarkService:
    def __init__(
        self,
        transcription_backends: dict[str, TranscriptionBackend],
        ocr_backends: dict[str, OcrBackend],
        runtime_version: str | None,
    ):
        self.transcription = transcription_backends
        self.ocr = ocr_backends
        self.runtime_version = runtime_version

    def candidate_cases(self, models: Sequence[str], ocr_languages: Sequence[str]) -> list[BenchmarkCase]:
        cases = [
            BenchmarkCase("transcripcion", name, model, device)
            for name, backend in self.transcription.items()
            for model in models
            for device in backend.supported_devices()
        ]
        cases += [
            BenchmarkCase("ocr", name, "+".join(ocr_languages), device)
            for name, backend in self.ocr.items()
            for device in backend.supported_devices()
        ]
        return cases

    def run(
        self,
        cases: Sequence[BenchmarkCase],
        is_cancelled: Callable[[], bool],
        on_result: Callable[[CompatibilityRecord], None] = lambda _r: None,
    ) -> list[CompatibilityRecord]:
        results: list[CompatibilityRecord] = []
        for case in cases:
            if is_cancelled():
                raise OperationCancelled()
            record = self._run_case(case, is_cancelled)
            results.append(record)
            on_result(record)
        return results

    def _record(
        self,
        case: BenchmarkCase,
        status: str,
        reason: str,
        load_ms: float | None = None,
        latency_ms: float | None = None,
        peak: float | None = None,
    ) -> CompatibilityRecord:
        return CompatibilityRecord(
            case.task,
            case.backend,
            case.model,
            case.device.value,
            status,
            reason,
            latency_ms,
            load_ms,
            peak,
            self.runtime_version if case.backend in ("openvino", "rapidocr_openvino") else None,
            datetime.now().isoformat(timespec="seconds"),
        )

    def _run_case(self, case: BenchmarkCase, is_cancelled: Callable[[], bool]) -> CompatibilityRecord:
        before = _rss_mb()
        started = time.perf_counter()
        try:
            if case.task == "transcripcion":
                backend = self.transcription[case.backend]
                if not backend.is_installed():
                    return self._record(case, NOT_VERIFIED, "Motor no instalado")
                if not backend.model_available(case.model):
                    return self._record(case, NOT_VERIFIED, "Modelo no disponible localmente")
                loaded = backend.load(case.model, case.device, allow_download=False)
                load_ms = (time.perf_counter() - started) * 1000
                infer = time.perf_counter()
                output: object = loaded.transcribe(synthetic_audio(), "es", 0.0, is_cancelled)
                latency = (time.perf_counter() - infer) * 1000
                if not _valid_segments(output):
                    return self._record(
                        case, NOT_COMPATIBLE, "La salida del modelo no tiene el formato esperado", load_ms, latency
                    )
            else:
                ocr = self.ocr[case.backend]
                languages = case.model.split("+")
                if not ocr.is_installed():
                    return self._record(case, NOT_VERIFIED, "Motor no instalado")
                if not ocr.models_available(languages):
                    return self._record(case, NOT_VERIFIED, "Modelos no disponibles localmente")
                reader = ocr.load(languages, case.device, allow_download=False)
                load_ms = (time.perf_counter() - started) * 1000
                infer = time.perf_counter()
                blocks: object = reader.recognize(synthetic_text_image())
                latency = (time.perf_counter() - infer) * 1000
                if not isinstance(blocks, list):
                    return self._record(
                        case, NOT_COMPATIBLE, "La salida del OCR no tiene el formato esperado", load_ms, latency
                    )
        except OperationCancelled:
            raise
        except AppError as error:
            return self._record(case, NOT_COMPATIBLE, _npu_reason(case) or error.message.what)
        except (RuntimeError, ValueError, OSError, TypeError, MemoryError) as error:
            return self._record(case, NOT_COMPATIBLE, _npu_reason(case) or type(error).__name__)
        after = _rss_mb()
        peak = round(after - before, 1) if before is not None and after is not None else None
        return self._record(
            case,
            COMPATIBLE,
            "Carga, compilación e inferencia mínima correctas",
            round(load_ms, 1),
            round(latency, 1),
            peak,
        )

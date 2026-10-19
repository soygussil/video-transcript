"""Backends de transcripción automática desacoplados detrás de una interfaz común.

- FasterWhisperBackend: CTranslate2, sólo CPU (int8). CTranslate2 no acelera GPU/NPU Intel.
- OpenVinoWhisperBackend: openvino-genai WhisperPipeline con un modelo exportado a OpenVINO IR.
  En modo Automático sólo se usa en GPU/NPU si una prueba real (BenchmarkService) lo verificó.
Ninguno descarga modelos sin autorización explícita (`allow_download`).
"""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import BackendUnavailableError, ModelNotAvailableError, OperationCancelled


@dataclass(frozen=True)
class RawSegment:
    start: float
    end: float
    text: str
    confidence: float | None = None


class LoadedTranscriber(Protocol):
    backend: str
    device: DeviceKind
    precision: str

    def transcribe(
        self, audio: np.ndarray, language: str, offset_seconds: float, is_cancelled: Callable[[], bool]
    ) -> list[RawSegment]: ...


class TranscriptionBackend(Protocol):
    name: str

    def is_installed(self) -> bool: ...

    def supported_devices(self) -> tuple[DeviceKind, ...]: ...

    def model_available(self, model: str) -> bool: ...

    def load(self, model: str, device: DeviceKind, allow_download: bool) -> LoadedTranscriber: ...


class _FasterWhisperTranscriber:
    backend = "faster_whisper"
    precision = "int8"

    def __init__(self, model: Any):
        self._model = model
        self.device = DeviceKind.CPU

    def transcribe(
        self, audio: np.ndarray, language: str, offset_seconds: float, is_cancelled: Callable[[], bool]
    ) -> list[RawSegment]:
        segments, _info = self._model.transcribe(audio, language=language, vad_filter=True)
        result: list[RawSegment] = []
        for segment in segments:  # generador: la cancelación se revisa entre segmentos
            if is_cancelled():
                raise OperationCancelled()
            logprob = getattr(segment, "avg_logprob", None)
            confidence = round(min(1.0, math.exp(logprob)), 4) if logprob is not None else None
            text = str(segment.text).strip()
            if text:
                start = offset_seconds + float(segment.start)
                result.append(RawSegment(start, max(start, offset_seconds + float(segment.end)), text, confidence))
        return result


class FasterWhisperBackend:
    name = "faster_whisper"

    def __init__(self, models_root: Path):
        self.models_root = models_root / "faster-whisper"

    def is_installed(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return (DeviceKind.CPU,)

    def model_available(self, model: str) -> bool:
        if not self.models_root.exists():
            return False
        suffix = f"faster-whisper-{model}"
        return any(
            p.name.endswith(suffix) and (p / "snapshots").exists() for p in self.models_root.iterdir() if p.is_dir()
        )

    def load(self, model: str, device: DeviceKind, allow_download: bool) -> LoadedTranscriber:
        if device is not DeviceKind.CPU:
            raise BackendUnavailableError(
                "faster-whisper sólo se usa en CPU en esta aplicación",
                "No se puede usar el dispositivo solicitado con este motor",
                "Selecciona CPU o el motor OpenVINO",
            )
        if not self.is_installed():
            raise BackendUnavailableError(
                "El motor de transcripción faster-whisper no está instalado",
                "La transcripción automática no está disponible",
                "Instala el componente opcional o importa una transcripción VTT o SRT",
                saved=True,
            )
        if not allow_download and not self.model_available(model):
            raise ModelNotAvailableError(
                f"El modelo de transcripción «{model}» no está descargado",
                "La transcripción automática no está disponible",
                "Descárgalo con 'analizador-video modelos descargar' o importa una transcripción VTT o SRT",
                saved=True,
            )
        from faster_whisper import WhisperModel

        self.models_root.mkdir(parents=True, exist_ok=True)
        try:
            loaded = WhisperModel(
                model,
                device="cpu",
                compute_type="int8",
                download_root=str(self.models_root),
                local_files_only=not allow_download,
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise ModelNotAvailableError(
                f"No se pudo cargar el modelo de transcripción «{model}»",
                "La transcripción automática no está disponible",
                "Verifica la descarga del modelo en Diagnóstico o importa una transcripción VTT o SRT",
                saved=True,
                details=type(error).__name__,
            ) from error
        return _FasterWhisperTranscriber(loaded)


_OV_DEVICE = {DeviceKind.CPU: "CPU", DeviceKind.GPU: "GPU", DeviceKind.NPU: "NPU"}


class _OpenVinoTranscriber:
    backend = "openvino"

    def __init__(self, pipeline: Any, device: DeviceKind, precision: str):
        self._pipeline = pipeline
        self.device = device
        self.precision = precision

    def transcribe(
        self, audio: np.ndarray, language: str, offset_seconds: float, is_cancelled: Callable[[], bool]
    ) -> list[RawSegment]:
        if is_cancelled():
            raise OperationCancelled()
        result = self._pipeline.generate(
            audio.astype(np.float32).tolist(), language=f"<|{language}|>", task="transcribe", return_timestamps=True
        )
        segments: list[RawSegment] = []
        for chunk in getattr(result, "chunks", None) or []:
            text = str(chunk.text).strip()
            if text:
                start = offset_seconds + float(chunk.start_ts)
                end_raw = chunk.end_ts if chunk.end_ts is not None and chunk.end_ts >= 0 else chunk.start_ts
                segments.append(RawSegment(start, max(start, offset_seconds + float(end_raw)), text))
        if not segments:
            joined = " ".join(str(t).strip() for t in (getattr(result, "texts", None) or [])).strip()
            if joined:
                segments.append(RawSegment(offset_seconds, offset_seconds + len(audio) / 16000.0, joined))
        return segments


class OpenVinoWhisperBackend:
    """Requiere un modelo Whisper exportado a OpenVINO IR en <modelos>/openvino/whisper-<modelo>/."""

    name = "openvino"

    def __init__(self, models_root: Path):
        self.models_root = models_root / "openvino"

    def model_dir(self, model: str) -> Path:
        """Carpeta exportada a mano (`whisper-<modelo>`) o descargada con precisión (`whisper-<modelo>-int8`)."""
        for suffix in ("", "-int8", "-int4", "-fp16"):
            candidate = self.models_root / f"whisper-{model}{suffix}"
            if (candidate / "openvino_encoder_model.xml").exists():
                return candidate
        return self.models_root / f"whisper-{model}"

    def download(self, model: str, precision: str = "int8") -> Path:
        """Descarga el modelo ya convertido (repositorio público OpenVINO/whisper-<modelo>-<precisión>-ov)."""
        from huggingface_hub import snapshot_download

        target = self.models_root / f"whisper-{model}-{precision}"
        try:
            snapshot_download(f"OpenVINO/whisper-{model}-{precision}-ov", local_dir=str(target))
        except Exception as error:  # huggingface_hub lanza tipos propios (red, repositorio inexistente)
            raise ModelNotAvailableError(
                f"No se pudo descargar el modelo OpenVINO «{model}» ({precision})",
                "La transcripción con OpenVINO no está disponible",
                "Revisa el nombre del modelo (tiny, base, small, medium, large-v3), la precisión y tu conexión",
                details=type(error).__name__,
            ) from error
        return target

    def is_installed(self) -> bool:
        return importlib.util.find_spec("openvino_genai") is not None

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return (DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU)

    def model_available(self, model: str) -> bool:
        return (self.model_dir(model) / "openvino_encoder_model.xml").exists()

    def load(self, model: str, device: DeviceKind, allow_download: bool) -> LoadedTranscriber:
        if not self.is_installed():
            raise BackendUnavailableError(
                "OpenVINO GenAI no está instalado",
                "La aceleración con GPU o NPU Intel no está disponible",
                "Se usará CPU; instala el componente opcional 'openvino' para habilitarla",
            )
        if not self.model_available(model):
            raise ModelNotAvailableError(
                f"No hay un modelo OpenVINO para «{model}»",
                "La transcripción con OpenVINO no está disponible",
                "Exporta el modelo a OpenVINO IR siguiendo la guía de README o usa CPU",
            )
        if device is DeviceKind.AUTO:
            raise ValueError("El dispositivo debe resolverse antes de cargar el modelo.")
        import openvino_genai

        cache = self.models_root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        try:
            pipeline = openvino_genai.WhisperPipeline(
                str(self.model_dir(model)), _OV_DEVICE[device], CACHE_DIR=str(cache)
            )
        except (RuntimeError, ValueError, OSError) as error:
            raise BackendUnavailableError(
                f"OpenVINO no pudo compilar el modelo «{model}» para {device.value.upper()}",
                "Ese dispositivo no se usará para transcribir",
                "Se usará el siguiente dispositivo permitido",
                details=str(error)[:500],
            ) from error
        name = self.model_dir(model).name.lower()
        precision = next((tag for tag in ("int4", "int8", "fp16") if tag in name), "según exportación")
        return _OpenVinoTranscriber(pipeline, device, precision)

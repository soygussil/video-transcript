"""Detección de pantallas clave (algoritmo original conservado) con progreso, cancelación y reanudación.

Se conserva la lógica original (diferencia de píxeles sobre miniatura desenfocada, espera de
estabilidad, separación mínima y captura periódica). Cambios: lectura secuencial con grab()
(mismos timestamps t = índice / fps), estado serializable para reanudar y persistencia delegada.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from analizador_video.config.settings import VideoSettings
from analizador_video.domain.models import VideoMetadata
from analizador_video.infrastructure.video.probe import open_capture
from analizador_video.infrastructure.video.region import Region

Thumb = np.ndarray


def make_thumb(frame: np.ndarray, width: int, height: int) -> Thumb:
    small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(small, (5, 5), 0).astype(np.float32) / 255.0


def change_ratio(a: Thumb, b: Thumb, pixel_threshold: float) -> float:
    return float(np.mean(np.max(np.abs(a - b), axis=2) > pixel_threshold))


@dataclass
class _Pending:
    time: float
    frame: np.ndarray
    thumb: Thumb
    change: float
    reason: str


@dataclass(frozen=True)
class DetectedCapture:
    seq: int
    time_seconds: float
    change_score: float
    reason: str
    jpeg_bytes: bytes


class KeyframeDetector:
    """Máquina de estados pura: recibe muestras y decide qué capturas conservar."""

    def __init__(self, cfg: VideoSettings, last_saved_thumb: Thumb | None = None, last_time: float | None = None):
        self.cfg = cfg
        self.last_saved = last_saved_thumb
        self.last_t = last_time if last_time is not None else -1e9
        self.prev: Thumb | None = None
        self.pending: _Pending | None = None

    def feed(self, t: float, frame: np.ndarray) -> _Pending | None:
        cfg = self.cfg
        th = make_thumb(frame, cfg.ancho_miniatura, cfg.alto_miniatura)
        vs_saved = 1.0 if self.last_saved is None else change_ratio(th, self.last_saved, cfg.umbral_pixel)
        vs_prev = 0.0 if self.prev is None else change_ratio(th, self.prev, cfg.umbral_pixel)
        periodic = cfg.captura_periodica_seg > 0 and t - self.last_t >= cfg.captura_periodica_seg
        if self.last_saved is None or periodic:
            reason = "inicial" if self.last_saved is None else "periodica"
            self.pending = _Pending(t, frame.copy(), th, vs_saved, reason)
        elif vs_saved >= cfg.umbral_cambio and t - self.last_t >= cfg.separacion_minima_seg:
            if self.pending is None:
                self.pending = _Pending(t, frame.copy(), th, vs_saved, "cambio")
            if vs_prev < cfg.umbral_estable or t - self.pending.time >= cfg.espera_max_estable_seg:
                reason = "cambio_estable" if vs_prev < cfg.umbral_estable else "espera_maxima"
                self.pending = _Pending(t, frame.copy(), th, vs_saved, reason)
        elif self.pending is not None and vs_saved < cfg.umbral_cambio:
            self.pending = None
        accepted: _Pending | None = None
        if self.pending and (
            self.last_saved is None
            or periodic
            or vs_prev < cfg.umbral_estable
            or t - self.pending.time >= cfg.espera_max_estable_seg
        ):
            accepted = self.pending
            self.last_saved = accepted.thumb
            self.last_t = accepted.time
            self.pending = None
        self.prev = th
        return accepted


def encode_capture(frame: np.ndarray, cfg: VideoSettings) -> bytes:
    width = cfg.ancho_salida
    height = max(1, round(frame.shape[0] * width / frame.shape[1]))
    resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, cfg.calidad_jpg])
    if not ok:
        raise RuntimeError("No se pudo codificar la captura en JPG.")
    return bytes(buffer.tobytes())


def thumb_from_jpeg(path: Path, cfg: VideoSettings) -> Thumb | None:
    if not path.exists():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    return None if image is None else make_thumb(image, cfg.ancho_miniatura, cfg.alto_miniatura)


def sample_step(fps: float, cfg: VideoSettings) -> int:
    return max(1, round(fps * cfg.muestreo_seg))


def total_samples(meta: VideoMetadata, cfg: VideoSettings) -> int:
    return max(0, math.ceil(meta.frame_count / sample_step(meta.fps, cfg)))


@dataclass
class FrameCheckpoint:
    next_index: int = 0
    captures: int = 0
    last_capture_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"next_index": self.next_index, "captures": self.captures, "last_capture_time": self.last_capture_time}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrameCheckpoint:
        last = data.get("last_capture_time")
        return cls(
            int(data.get("next_index", 0)), int(data.get("captures", 0)), float(last) if last is not None else None
        )


def extract_keyframes(
    video: Path,
    meta: VideoMetadata,
    cfg: VideoSettings,
    checkpoint: FrameCheckpoint,
    last_saved_thumb: Thumb | None,
    on_capture: Callable[[DetectedCapture, FrameCheckpoint], None],
    on_progress: Callable[[int, int, FrameCheckpoint], None],
    is_cancelled: Callable[[], bool],
    region: Region | None = None,
) -> FrameCheckpoint:
    """Recorre el video desde `checkpoint.next_index`; se detiene si `is_cancelled()`."""
    step = sample_step(meta.fps, cfg)
    total = total_samples(meta, cfg)
    detector = KeyframeDetector(cfg, last_saved_thumb, checkpoint.last_capture_time)
    capture = open_capture(video)
    try:
        index = checkpoint.next_index
        if index > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        position = index
        while meta.frame_count <= 0 or index < meta.frame_count:
            if is_cancelled():
                break
            ended = False
            while position < index:
                if not capture.grab():
                    ended = True
                    break
                position += 1
            ok, frame = (False, None) if ended else capture.read()
            position += 1
            if not ok or frame is None:
                # El contenedor reportó más cuadros de los legibles: fin del video.
                checkpoint.next_index = max(checkpoint.next_index, index)
                on_progress(total, total, checkpoint)
                break
            if region is not None:
                frame = region.crop(frame)
            accepted = detector.feed(index / meta.fps, frame)
            checkpoint.next_index = index + step
            if accepted is not None:
                checkpoint.captures += 1
                checkpoint.last_capture_time = accepted.time
                on_capture(
                    DetectedCapture(
                        checkpoint.captures,
                        accepted.time,
                        round(accepted.change, 5),
                        accepted.reason,
                        encode_capture(accepted.frame, cfg),
                    ),
                    checkpoint,
                )
            on_progress(min(total, checkpoint.next_index // step), total, checkpoint)
            index += step
    finally:
        capture.release()
    return checkpoint

"""Lectura de metadatos y apertura robusta de videos con OpenCV."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import cv2

from analizador_video.domain.errors import VideoUnreadableError
from analizador_video.domain.models import VideoMetadata

FINGERPRINT_CHUNK = 4 * 1024 * 1024


def _windows_short_path(path: Path) -> str | None:
    """OpenCV puede fallar con rutas no ASCII en Windows; la ruta corta 8.3 es ASCII."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    get_short = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    if get_short(str(path), buffer, len(buffer)) == 0:
        return None
    return buffer.value or None


def open_capture(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if capture.isOpened():
        return capture
    capture.release()
    if not str(path).isascii():
        short = _windows_short_path(path)
        if short:
            capture = cv2.VideoCapture(short)
            if capture.isOpened():
                return capture
            capture.release()
    raise VideoUnreadableError(
        f"No se pudo abrir el video «{path.name}»",
        "No es posible extraer capturas de este archivo",
        "Verifica que el archivo no esté dañado ni abierto en otro programa, o conviértelo a MP4 (H.264)",
        saved=True,
    )


def _fourcc(capture: cv2.VideoCapture) -> str | None:
    code = int(capture.get(cv2.CAP_PROP_FOURCC))
    if code <= 0:
        return None
    text = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00 ")
    return text if text.isprintable() and text else None


def probe_video(path: Path) -> VideoMetadata:
    capture = open_capture(path)
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        prop = getattr(cv2, "CAP_PROP_ORIENTATION_META", None)
        rotation = int(capture.get(prop) or 0) if prop is not None else 0
        ok, _ = capture.read()
        codec = _fourcc(capture)
    finally:
        capture.release()
    if not ok:
        raise VideoUnreadableError(
            f"El video «{path.name}» no contiene imágenes legibles",
            "No es posible extraer capturas",
            "Verifica el archivo o conviértelo a MP4 (H.264)",
            saved=True,
        )
    if fps <= 0 or fps > 1000:
        fps = 25.0
    duration = frame_count / fps if frame_count > 0 else 0.0
    return VideoMetadata(duration, fps, max(frame_count, 0), width, height, codec, rotation)


def fingerprint(path: Path) -> str:
    """Huella parcial (tamaño + primeros y últimos 4 MB). Detecta reemplazos; no garantiza integridad bit a bit."""
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(FINGERPRINT_CHUNK))
        if size > FINGERPRINT_CHUNK:
            handle.seek(max(0, size - FINGERPRINT_CHUNK))
            digest.update(handle.read(FINGERPRINT_CHUNK))
    return f"sha256p:{digest.hexdigest()}"

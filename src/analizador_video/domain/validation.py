"""Validaciones puras (sin abrir el video): rápidas y seguras para el hilo de la interfaz."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv"})
SUBTITLE_EXTENSIONS = frozenset({".vtt", ".srt"})
MAX_SUBTITLE_BYTES = 50 * 1024 * 1024
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    blocking: bool = True


def validate_video_file(path: Path | None) -> list[ValidationIssue]:
    if path is None or not str(path).strip():
        return [ValidationIssue("video", "Selecciona o arrastra un archivo de video.")]
    if not path.exists():
        return [ValidationIssue("video", f"No se encontró el archivo «{path.name}». Verifica que no se haya movido.")]
    if not path.is_file():
        return [ValidationIssue("video", "La ruta seleccionada es una carpeta, no un archivo de video.")]
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        fmt = path.suffix or "sin extensión"
        return [ValidationIssue("video", f"El formato «{fmt}» no es compatible. Usa: {allowed}.")]
    if path.stat().st_size == 0:
        return [ValidationIssue("video", f"El archivo «{path.name}» está vacío.")]
    return []


def validate_subtitle_file(path: Path | None) -> list[ValidationIssue]:
    if path is None:
        return []
    if not path.is_file():
        return [ValidationIssue("transcripcion", f"No se encontró la transcripción «{path.name}».")]
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        return [ValidationIssue("transcripcion", "La transcripción debe ser un archivo .vtt o .srt.")]
    size = path.stat().st_size
    if size == 0:
        return [ValidationIssue("transcripcion", f"La transcripción «{path.name}» está vacía.")]
    if size > MAX_SUBTITLE_BYTES:
        return [ValidationIssue("transcripcion", "La transcripción supera 50 MB; verifica que sea de subtítulos.")]
    return []


def safe_filename(name: str, max_length: int = 80, fallback: str = "proyecto") -> str:
    """Nombre seguro para Windows: sin separadores, reservados ni caracteres de control."""
    normalized = unicodedata.normalize("NFKC", name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned.replace("..", "_")
    if not cleaned or cleaned.upper().split(".")[0] in _RESERVED:
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    return cleaned[:max_length].rstrip(" .") or fallback


def resolve_within(base: Path, relative: str) -> Path:
    """Resuelve `relative` dentro de `base` y rechaza cualquier path traversal."""
    candidate = (base / relative).resolve()
    root = base.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("La ruta solicitada sale de la carpeta del proyecto.")
    return candidate

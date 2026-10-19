"""Formato temporal. Siempre se convierte primero a milisegundos enteros (nunca '.1000')."""

from __future__ import annotations

import math
import re

_TIMESTAMP_RE = re.compile(r"^(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})$")


def to_milliseconds(seconds: float) -> int:
    if math.isnan(seconds) or math.isinf(seconds):
        raise ValueError("El tiempo debe ser un número finito.")
    return round(max(0.0, float(seconds)) * 1000)


def format_hms(seconds: float, decimal_separator: str = ".") -> str:
    """HH:MM:SS.mmm (o HH:MM:SS,mmm para SRT)."""
    total_seconds, ms = divmod(to_milliseconds(seconds), 1000)
    hours, rest = divmod(total_seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_separator}{ms:03d}"


def format_srt(seconds: float) -> str:
    return format_hms(seconds, ",")


def format_compact(seconds: float) -> str:
    """Formato para nombres de archivo: HH-MM-SS."""
    return format_hms(seconds).split(".")[0].replace(":", "-")


def parse_timestamp(text: str) -> float:
    """Acepta HH:MM:SS.mmm, MM:SS.mmm y la coma de SRT."""
    match = _TIMESTAMP_RE.match(text.strip())
    if not match:
        raise ValueError(f"Marca de tiempo inválida: {text!r}")
    hours, minutes, secs, frac = match.groups()
    if int(minutes) > 59 or int(secs) > 59:
        raise ValueError(f"Marca de tiempo fuera de rango: {text!r}")
    ms = int(frac.ljust(3, "0"))
    total_ms = ((int(hours or 0) * 60 + int(minutes)) * 60 + int(secs)) * 1000 + ms
    return total_ms / 1000.0

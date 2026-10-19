"""Importación de transcripciones VTT/SRT.

Codificaciones: UTF-8 (con o sin BOM), UTF-16 (BOM o detectado por bytes nulos) y, como último
recurso controlado, Windows-1252 con advertencia. Bloques inválidos se omiten y se cuentan.
Se conserva la regla original de unir intervenciones consecutivas del mismo hablante.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from analizador_video.domain.enums import TranscriptSource
from analizador_video.domain.errors import InputValidationError
from analizador_video.domain.models import UNKNOWN_SPEAKER, TranscriptSegment
from analizador_video.domain.timefmt import parse_timestamp

_TS = r"(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3}"
_TIMING_RE = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_VOICE_RE = re.compile(r"<v(?:\.[^\s>]+)*\s+([^>]+)>(.*?)(?:</v>|$)", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PREFIX_SPEAKER_RE = re.compile(r"^([^:\n]{2,80}):\s+(.+)$", re.DOTALL)
Item = tuple[float, float, str, str]


@dataclass
class SubtitleParseResult:
    segments: list[TranscriptSegment]
    encoding: str
    warnings: list[str] = field(default_factory=list)
    skipped_blocks: int = 0


def decode_subtitle_bytes(raw: bytes) -> tuple[str, str, list[str]]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig", []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16", []
    if raw[:200].count(b"\x00") > 20:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc), enc, []
            except UnicodeDecodeError:
                continue
    try:
        return raw.decode("utf-8"), "utf-8", []
    except UnicodeDecodeError:
        pass
    try:
        return (
            raw.decode("cp1252"),
            "cp1252",
            ["La transcripción no estaba en UTF-8; se interpretó como Windows-1252. Revisa acentos y eñes."],
        )
    except UnicodeDecodeError:
        return (
            raw.decode("latin-1"),
            "latin-1",
            ["La codificación de la transcripción no se reconoció; algunos caracteres podrían verse mal."],
        )


def _split_speaker(raw: str) -> tuple[str, str]:
    voice = _VOICE_RE.search(raw)
    if voice:
        return html.unescape(voice.group(1).strip()), html.unescape(_TAG_RE.sub("", voice.group(2))).strip()
    plain = html.unescape(_TAG_RE.sub("", raw)).strip()
    prefixed = _PREFIX_SPEAKER_RE.match(plain)
    if prefixed and not prefixed.group(1).strip().isdigit():
        return prefixed.group(1).strip(), prefixed.group(2).strip()
    return UNKNOWN_SPEAKER, plain


def parse_subtitle_text(text: str) -> tuple[list[Item], int, list[str]]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    items: list[Item] = []
    skipped = 0
    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        match = _TIMING_RE.match(lines[timing_index]) if timing_index is not None else None
        if timing_index is None or match is None:
            skipped += 1
            continue
        try:
            start, end = parse_timestamp(match.group(1)), parse_timestamp(match.group(2))
        except ValueError:
            skipped += 1
            continue
        if end < start:
            skipped += 1
            continue
        speaker, content = _split_speaker(" ".join(line.strip() for line in lines[timing_index + 1 :]))
        content = re.sub(r"\s+", " ", content).strip()
        if content:
            items.append((start, end, speaker, content))
    warnings = [f"Se omitieron {skipped} bloques de la transcripción con formato inválido."] if skipped else []
    return items, skipped, warnings


def merge_same_speaker(items: list[Item], max_gap_seconds: float) -> list[Item]:
    ordered = [item for _, item in sorted(enumerate(items), key=lambda pair: (pair[1][0], pair[0]))]
    merged: list[Item] = []
    for start, end, speaker, text in ordered:
        if merged and merged[-1][2] == speaker and start - merged[-1][1] <= max_gap_seconds:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), speaker, f"{prev[3]} {text}")
        else:
            merged.append((start, end, speaker, text))
    return merged


def import_subtitles(path: Path, merge_gap_seconds: float) -> SubtitleParseResult:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise InputValidationError(
            f"No se pudo leer la transcripción «{path.name}»",
            "La transcripción no se importó",
            "Cierra el archivo si está abierto en otro programa y vuelve a intentarlo",
            saved=True,
        ) from error
    text, encoding, warnings = decode_subtitle_bytes(raw)
    items, skipped, parse_warnings = parse_subtitle_text(text)
    if not items:
        raise InputValidationError(
            f"La transcripción «{path.name}» no contiene segmentos válidos",
            "La transcripción no se importó",
            "Verifica que sea un archivo VTT o SRT con marcas 00:00:00.000 --> 00:00:00.000",
            saved=True,
        )
    segments = [
        TranscriptSegment(i, s, e, sp, t, TranscriptSource.IMPORTED)
        for i, (s, e, sp, t) in enumerate(merge_same_speaker(items, merge_gap_seconds), start=1)
    ]
    return SubtitleParseResult(segments, encoding, warnings + parse_warnings, skipped)

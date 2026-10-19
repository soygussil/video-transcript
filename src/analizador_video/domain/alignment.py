"""Servicio de dominio de alineación "visto vs. dicho".

Contrato (probado en tests/unit/test_domain.py):
1. Intervalo de captura: [inicio, fin), fin = tiempo de la siguiente captura. Para la última,
   fin = duración del video; si no se conoce, fin del último segmento; nunca infinito.
2. Un segmento [s, e] pertenece a la captura si e >= inicio y s < fin. Un segmento que cruza un
   cambio de pantalla aparece en ambas.
3. Segmentos superpuestos se conservan todos, en orden estable (inicio, seq).
4. Sin OCR: ocr_text vacío. Sin transcripción: segments vacío. Ninguno es un error.
5. Capturas en orden estable (tiempo, seq).
6. Formato público de `dicho`: "[HH:MM:SS.mmm - HH:MM:SS.mmm] Hablante: texto". Los reportes
   formatean desde los campos estructurados y nunca vuelven a analizar este texto.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from analizador_video.domain.models import AlignedEvidence, ScreenCapture, TranscriptSegment


def format_spoken_line(segment: TranscriptSegment) -> str:
    return f"[{segment.start_display} - {segment.end_display}] {segment.speaker_or_unknown}: {segment.text}"


def format_spoken(segments: Iterable[TranscriptSegment]) -> str:
    return "\n".join(format_spoken_line(s) for s in segments)


def align(
    captures: Sequence[ScreenCapture],
    segments: Sequence[TranscriptSegment],
    ocr_text_by_capture: Mapping[str, str],
    duration_seconds: float | None,
) -> list[AlignedEvidence]:
    ordered_captures = sorted(captures, key=lambda c: (c.time_seconds, c.seq))
    ordered_segments = sorted(segments, key=lambda s: (s.start_seconds, s.seq))
    last_spoken = max((s.end_seconds for s in ordered_segments), default=0.0)
    result: list[AlignedEvidence] = []
    for index, capture in enumerate(ordered_captures):
        start = capture.time_seconds
        if index + 1 < len(ordered_captures):
            end = ordered_captures[index + 1].time_seconds
        elif duration_seconds is not None:
            end = max(start, float(duration_seconds))
        else:
            end = max(start, last_spoken)
        matched = tuple(s for s in ordered_segments if s.end_seconds >= start and s.start_seconds < end)
        result.append(AlignedEvidence(capture, start, end, ocr_text_by_capture.get(capture.id, ""), matched))
    return result

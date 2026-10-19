import math

import pytest

from analizador_video.domain.alignment import align, format_spoken_line
from analizador_video.domain.enums import TranscriptSource
from analizador_video.domain.errors import InputValidationError, UserMessage
from analizador_video.domain.models import ScreenCapture, TranscriptSegment
from analizador_video.domain.timefmt import format_compact, format_hms, format_srt, parse_timestamp
from analizador_video.domain.validation import (
    resolve_within,
    safe_filename,
    validate_subtitle_file,
    validate_video_file,
)


def seg(seq, start, end, speaker="A", text="Hola"):
    return TranscriptSegment(seq, start, end, speaker, text, TranscriptSource.IMPORTED)


def cap(seq, time):
    return ScreenCapture(f"P{seq:04d}", seq, f"frames/P{seq:04d}.jpg", time, 1.0, "cambio")


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "00:00:00.000"),
        (0.9996, "00:00:01.000"),
        (59.9999, "00:01:00.000"),
        (3599.9995, "01:00:00.000"),
        (3723.5, "01:02:03.500"),
        (-2, "00:00:00.000"),
        (360000, "100:00:00.000"),
    ],
)
def test_format_hms_rounds_before_split(value, expected):  # problema I
    assert format_hms(value) == expected


def test_srt_and_compact_formats():
    assert format_srt(1.25) == "00:00:01,250"
    assert format_compact(3723.9) == "01-02-03"


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_format_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        format_hms(bad)


@pytest.mark.parametrize("text,expected", [("01:02:03.500", 3723.5), ("02:03,5", 123.5), ("1:00:00.1", 3600.1)])
def test_parse_timestamp(text, expected):
    assert parse_timestamp(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["00:61:00.000", "abc", "00:00:00", "00:00:60.000"])
def test_parse_timestamp_invalid(bad):
    with pytest.raises(ValueError):
        parse_timestamp(bad)


def test_spoken_line_contract():  # problema A
    assert format_spoken_line(seg(1, 1, 2, "A", "Hola")) == "[00:00:01.000 - 00:00:02.000] A: Hola"
    assert format_spoken_line(seg(1, 1, 2, "  ", "x")).endswith("Desconocido: x")


def test_alignment_intervals_and_overlap_rules():
    captures = [cap(1, 0.0), cap(2, 5.0), cap(3, 9.0)]
    segments = [seg(1, 1, 2), seg(2, 4.5, 6.0), seg(3, 5.0, 5.5), seg(4, 9.0, 12.0), seg(5, 3.0, 4.0)]
    rows = align(captures, segments, {"P0002": "Guardar"}, 12.0)
    assert [(r.start_seconds, r.end_seconds) for r in rows] == [(0, 5), (5, 9), (9, 12)]
    assert [s.seq for s in rows[0].segments] == [1, 5, 2]
    assert [s.seq for s in rows[1].segments] == [2, 3]
    assert [s.seq for s in rows[2].segments] == [4]
    assert rows[1].ocr_text == "Guardar" and rows[0].ocr_text == ""


def test_alignment_boundary_and_missing_data():
    assert [s.seq for s in align([cap(1, 0.0), cap(2, 5.0)], [seg(1, 3.0, 5.0)], {}, 10.0)[1].segments] == [1]
    assert align([cap(1, 2.0)], [seg(1, 3, 8)], {}, None)[0].end_seconds == 8.0
    empty = align([cap(1, 2.0)], [], {}, None)[0]
    assert empty.end_seconds == 2.0 and empty.segments == ()
    assert [r.capture.id for r in align([cap(2, 5.0), cap(1, 0.0)], [], {}, 6.0)] == ["P0001", "P0002"]


def test_segment_rejects_inverted_interval():
    with pytest.raises(ValueError):
        seg(1, 5, 4)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Demo: Portal/Claims?", "Demo_ Portal_Claims_"),
        ("CON", "proyecto_CON"),
        ("  ..  ", "proyecto"),
        ("ñandú 2026", "ñandú 2026"),
        ("../../etc", "___etc"),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


def test_resolve_within_blocks_traversal(tmp_path):
    assert resolve_within(tmp_path, "frames/a.jpg") == (tmp_path / "frames/a.jpg").resolve()
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "../fuera.txt")


def test_video_and_subtitle_validation(tmp_path):
    assert validate_video_file(None)[0].field == "video"
    assert "No se encontró" in validate_video_file(tmp_path / "x.mp4")[0].message
    (tmp_path / "a.txt").write_text("x")
    assert "no es compatible" in validate_video_file(tmp_path / "a.txt")[0].message
    (tmp_path / "v.mp4").write_bytes(b"")
    assert "vacío" in validate_video_file(tmp_path / "v.mp4")[0].message
    assert validate_subtitle_file(None) == []
    assert validate_subtitle_file(tmp_path / "a.txt")


def test_user_message_has_all_parts_and_roundtrip():
    error = InputValidationError(
        "No se encontró FFmpeg",
        "La transcripción automática necesita este componente",
        "Instálalo desde Diagnóstico",
        saved=True,
        details="WinError 2",
    )
    text = str(error)
    assert "FFmpeg" in text and "avance quedó guardado" in text and "Diagnóstico" in text
    assert "WinError" not in text
    assert UserMessage.from_dict(error.message.to_dict()) == error.message

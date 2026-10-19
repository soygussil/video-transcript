import pytest

from analizador_video.domain.errors import InputValidationError
from analizador_video.infrastructure.transcription.subtitles import (
    decode_subtitle_bytes,
    import_subtitles,
    merge_same_speaker,
    parse_subtitle_text,
)

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Ana>Hola</v>\n\n00:00:02.500 --> 00:00:03.000\n<v Ana>mundo</v>\n"
SRT = "1\n00:00:01,000 --> 00:00:02,000\nLuis: Línea uno\nlínea dos\n\n2\n00:00:05,000 --> 00:00:06,000\nSin hablante\n"


@pytest.mark.parametrize(
    "encoding,expected", [("utf-8", "utf-8"), ("utf-8-sig", "utf-8-sig"), ("utf-16", "utf-16"), ("cp1252", "cp1252")]
)
def test_encodings(tmp_path, encoding, expected):
    path = tmp_path / "t.srt"
    path.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nAcción: añadir línea\n".encode(encoding))
    result = import_subtitles(path, 0)
    assert result.encoding == expected
    assert result.segments[0].speaker == "Acción" and result.segments[0].text == "añadir línea"
    assert bool(result.warnings) == (encoding == "cp1252")


def test_utf16_without_bom_detected():
    text, encoding, _ = decode_subtitle_bytes("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhola\n".encode("utf-16-le"))
    assert encoding == "utf-16-le" and "hola" in text


def test_vtt_voice_tags_and_merge(tmp_path):
    path = tmp_path / "a.vtt"
    path.write_text(VTT, encoding="utf-8")
    merged = import_subtitles(path, 1.5).segments
    assert len(merged) == 1 and merged[0].text == "Hola mundo" and merged[0].end_seconds == 3.0
    assert [s.text for s in import_subtitles(path, 0.1).segments] == ["Hola", "mundo"]


def test_srt_multiline_and_missing_speaker(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text(SRT, encoding="utf-8")
    segments = import_subtitles(path, 0).segments
    assert segments[0].speaker == "Luis" and segments[0].text == "Línea uno línea dos"
    assert segments[1].speaker == "Desconocido"


def test_voice_with_class_and_entities():
    items, skipped, _ = parse_subtitle_text(
        "WEBVTT\n\n00:01.000 --> 00:02.000\n<v.loud Dra. Pérez &amp; Co>Sí &lt;ok&gt;</v>\n"
    )
    assert items == [(1.0, 2.0, "Dra. Pérez & Co", "Sí <ok>")] and skipped == 0


def test_partially_invalid_and_inverted_blocks():
    text = (
        "WEBVTT\n\nNOTE comentario\n\n00:00:01.000 --> 00:00:02.000\nbien\n\nbasura sin tiempo\n\n"
        "00:00:05.000 --> 00:00:04.000\ninvertido\n\n00:00:99.000 --> 00:01:00.000\nfuera de rango\n"
    )
    items, skipped, warnings = parse_subtitle_text(text)
    assert [i[3] for i in items] == ["bien"] and skipped == 3 and warnings


def test_overlapping_segments_are_kept_in_order():
    merged = merge_same_speaker([(5.0, 7.0, "B", "dos"), (1.0, 6.0, "A", "uno"), (5.5, 6.5, "C", "tres")], 0)
    assert [m[3] for m in merged] == ["uno", "dos", "tres"]


def test_boundary_timestamps():
    items, _, _ = parse_subtitle_text("00:00:00.000 --> 00:00:00.000\ncero\n\n99:59:59.999 --> 99:59:59.999\nfin\n")
    assert items[0][:2] == (0.0, 0.0) and items[1][0] == pytest.approx(359999.999)


def test_empty_file_raises(tmp_path):
    path = tmp_path / "vacio.vtt"
    path.write_text("WEBVTT\n\n", encoding="utf-8")
    with pytest.raises(InputValidationError):
        import_subtitles(path, 1)

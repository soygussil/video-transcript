"""ReportService: genera los formatos seleccionados de forma repetible, sin reprocesar el video."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from analizador_video.domain.enums import ReportKind
from analizador_video.domain.models import ReportArtifact
from analizador_video.infrastructure.reports.excel import create_excel
from analizador_video.infrastructure.reports.model import ReportData
from analizador_video.infrastructure.reports.text_exports import export_json, export_srt, export_txt
from analizador_video.infrastructure.reports.word import create_word

_WRITERS: dict[ReportKind, Callable[[ReportData, Path], Path]] = {
    ReportKind.WORD: create_word,
    ReportKind.EXCEL: create_excel,
    ReportKind.JSON: export_json,
    ReportKind.TXT: export_txt,
    ReportKind.SRT: export_srt,
}


class ReportService:
    def generate(
        self,
        data: ReportData,
        kinds: Iterable[ReportKind],
        destination: Path,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> list[ReportArtifact]:
        destination.mkdir(parents=True, exist_ok=True)
        selected = set(kinds)
        artifacts: list[ReportArtifact] = []
        for kind in ReportKind:  # orden estable
            if kind in selected and not is_cancelled():
                path = _WRITERS[kind](data, destination)
                artifacts.append(ReportArtifact(kind, path, datetime.now().isoformat(timespec="seconds")))
        return artifacts

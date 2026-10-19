"""Preferencias de la interfaz guardadas sin que la persona edite archivos."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from analizador_video.infrastructure.fileio import atomic_write_json, read_json_object

THEMES = ("claro", "oscuro")
DEVICES = ("auto", "gpu", "npu", "cpu")


@dataclass
class Preferences:
    theme: str = "claro"
    projects_root: str = ""
    profile: str = "balanceado"
    copy_video: bool = False
    device: str = "auto"  # auto | gpu | npu | cpu (transcripción y OCR)

    @classmethod
    def load(cls, path: Path) -> Preferences:
        try:
            data = read_json_object(path) or {}
        except ValueError:
            data = {}
        prefs = cls()
        for key in asdict(prefs):
            if key in data and isinstance(data[key], type(getattr(prefs, key))):
                setattr(prefs, key, data[key])
        if prefs.theme not in THEMES:
            prefs.theme = "claro"
        if prefs.device not in DEVICES:
            prefs.device = "auto"
        return prefs

    def save(self, path: Path) -> None:
        atomic_write_json(path, asdict(self))

"""Ubicaciones de la aplicación. Funcionan en desarrollo y dentro del ejecutable de PyInstaller."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from analizador_video import APP_ID

HOME_ENV = "ANALIZADOR_VIDEO_HOME"


def app_home() -> Path:
    """Datos de la aplicación (logs, preferencias, modelos). Siempre escribible."""
    override = os.environ.get(HOME_ENV)
    if override:
        base = Path(override)
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / APP_ID
    else:
        base = Path.home() / ".local" / "share" / "analizador_video"
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    path = app_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = app_home() / "modelos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_projects_root() -> Path:
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override) / "Proyectos"
    documents = Path.home() / "Documents"
    return (documents if documents.exists() else Path.home()) / "Analizador de video" / "Proyectos"


def bundled_resource(relative: str) -> Path:
    """Ruta a un recurso empaquetado (PyInstaller define sys._MEIPASS)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "analizador_video" / relative
    return Path(__file__).resolve().parents[1] / relative


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

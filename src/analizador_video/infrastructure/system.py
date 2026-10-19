"""Integración con el sistema operativo (abrir carpetas, espacio libre, FFmpeg)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# En Windows evita que se abra una consola al invocar procesos auxiliares desde la GUI.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def open_folder(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(path.name)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def find_ffmpeg() -> Path | None:
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def ffmpeg_version(binary: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(binary), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (completed.stdout or "").splitlines()[:1]
    return first[0].strip() if first else None

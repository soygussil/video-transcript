# -*- mode: python ; coding: utf-8 -*-
# Build reproducible: ejecutar desde la raíz con scripts/build_windows.ps1.
# Ventana sin consola; los modelos NO se incluyen (viven en %LOCALAPPDATA%\AnalizadorVideo\modelos).
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"

a = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "launcher.py")],
    pathex=[str(SRC)],
    datas=[
        (str(SRC / "analizador_video" / "config" / "default_config.yaml"), "analizador_video/config"),
        (str(SRC / "analizador_video" / "ui" / "resources"), "analizador_video/ui/resources"),
    ],
    hiddenimports=["analizador_video.application.workers", "analizador_video.application.diagnostics"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AnalizadorVideo",
    console=False,
    icon=str(SRC / "analizador_video" / "ui" / "resources" / "app.ico"),
    version=str(ROOT / "packaging" / "windows" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="AnalizadorVideo")

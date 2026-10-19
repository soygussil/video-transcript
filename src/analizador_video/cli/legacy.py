"""Compatibilidad con la CLI original (`python main.py --video ...`) durante la transición.

Traduce las opciones antiguas al comando `analizar`. El proyecto se crea en <salida>/<nombre del video>
como antes, aunque la estructura interna cambió (ver CHANGELOG).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from analizador_video.cli import commands


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="(Compatibilidad) Analiza un video. Usa 'analizador-video analizar'.")
    p.add_argument("--video", required=True)
    p.add_argument("--transcript")
    p.add_argument("--config")
    p.add_argument("--salida", default="salida")
    p.add_argument("--pasos", default=",".join(commands.PUBLIC_STAGES))
    p.add_argument("--forzar", default="")
    p.add_argument("--sin-ocr", action="store_true")
    p.add_argument("--sin-transcripcion-automatica", action="store_true")
    p.add_argument("--sin-ia", action="store_true", help="OBSOLETO: equivale a --sin-transcripcion-automatica.")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def to_modern_argv(argv: Sequence[str] | None = None) -> list[str]:
    a = build_parser().parse_args(argv)
    if a.sin_ia:
        print("Aviso: --sin-ia está obsoleto; usa --sin-transcripcion-automatica.", file=sys.stderr)
    modern = ["--log-level", a.log_level, "analizar", a.video, "--salida", a.salida, "--pasos", a.pasos]
    if a.transcript:
        modern += ["--transcript", a.transcript]
    config = a.config or ("config.yaml" if Path("config.yaml").is_file() else None)
    if config:
        modern += ["--config", config]
    if a.forzar:
        modern += ["--forzar", a.forzar]
    if a.sin_ocr:
        modern.append("--sin-ocr")
    if a.sin_transcripcion_automatica or a.sin_ia:
        modern.append("--sin-transcripcion-automatica")
    return modern


def main(argv: Sequence[str] | None = None) -> int:
    return commands.main(to_modern_argv(argv))

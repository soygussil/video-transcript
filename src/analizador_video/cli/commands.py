"""CLI `analizador-video`. Usa los mismos casos de uso que la interfaz gráfica.

Códigos de salida (documentados y probados):
  0   éxito (también si terminó con advertencias)
  1   fallo de procesamiento (mensaje accionable en stderr)
  2   entrada o configuración inválida
  130 cancelado por la persona usuaria (Ctrl+C); el avance queda guardado
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analizador_video import __version__
from analizador_video.domain.enums import DeviceKind, JobStatus, ProfileName, ReportKind, SourceMode, StageName
from analizador_video.domain.errors import AppError, InputValidationError

EXIT_OK, EXIT_FAILURE, EXIT_USAGE, EXIT_CANCELLED = 0, 1, 2, 130
PUBLIC_STAGES = [s.value for s in StageName.ordered() if s is not StageName.PREPARE]
PROFILE_ALIASES = {
    "rapido": ProfileName.FAST,
    "balanceado": ProfileName.BALANCED,
    "maxima": ProfileName.MAX_ACCURACY,
    "maxima_precision": ProfileName.MAX_ACCURACY,
}


def _stage_set(raw: str, option: str, allow_all: bool = False) -> set[StageName]:
    values = {v.strip() for v in raw.split(",") if v.strip()}
    if allow_all and "todo" in values:
        return set(StageName.ordered())
    unknown = values - set(PUBLIC_STAGES)
    if unknown:
        raise InputValidationError(
            f"{option}: etapas no reconocidas {sorted(unknown)}",
            "No se inició el análisis",
            f"Usa una lista separada por comas de: {', '.join(PUBLIC_STAGES)}",
        )
    return {StageName(v) for v in values}


def _common_processing(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pasos", default=",".join(PUBLIC_STAGES), help=f"Etapas: {', '.join(PUBLIC_STAGES)}.")
    parser.add_argument("--forzar", default="", help="Etapas a recalcular (o 'todo').")
    parser.add_argument("--dispositivo", choices=[d.value for d in DeviceKind], default=DeviceKind.AUTO.value)
    parser.add_argument("--sin-ocr", action="store_true", help="No ejecuta OCR.")
    parser.add_argument(
        "--sin-transcripcion-automatica",
        action="store_true",
        help="No usa transcripción automática (útil si se importa VTT/SRT).",
    )


def build_parser() -> argparse.ArgumentParser:
    from analizador_video.infrastructure.paths import default_projects_root

    parser = argparse.ArgumentParser(prog="analizador-video", description="Análisis local de videos.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analizar", help="Crea (o reanuda) un proyecto y analiza un video.")
    analyze.add_argument("video", type=Path)
    analyze.add_argument("--transcript", type=Path, help="Transcripción VTT o SRT.")
    analyze.add_argument("--perfil", choices=sorted(PROFILE_ALIASES), default="balanceado")
    analyze.add_argument("--salida", type=Path, default=default_projects_root(), help="Carpeta de proyectos.")
    analyze.add_argument("--nombre", help="Identificador del proyecto (por defecto, el nombre del video).")
    analyze.add_argument("--copiar-video", action="store_true", help="Copia el video dentro del proyecto.")
    analyze.add_argument("--config", type=Path, help="Archivo de configuración YAML (v1 o v2).")
    _common_processing(analyze)

    resume = sub.add_parser("continuar", help="Reanuda un proyecto existente.")
    resume.add_argument("proyecto", type=Path)
    resume.add_argument("--salida", type=Path, default=default_projects_root())
    _common_processing(resume)

    export = sub.add_parser("exportar", help="Genera reportes sin reprocesar el video.")
    export.add_argument("proyecto", type=Path)
    export.add_argument("--salida", type=Path, default=default_projects_root())
    export.add_argument("--formatos", default=",".join(k.value for k in ReportKind))
    export.add_argument("--destino", type=Path)
    export.add_argument(
        "--sin-datos-sensibles", action="store_true", help="Omite rutas locales y nombres de hablantes."
    )

    diagnose = sub.add_parser("diagnostico", help="Muestra hardware, componentes y compatibilidad.")
    diagnose.add_argument("--json", type=Path, help="Guarda el diagnóstico completo en este archivo.")
    diagnose.add_argument("--probar", action="store_true", help="Ejecuta pruebas reales de compatibilidad.")
    diagnose.add_argument("--modelos", default="", help="Modelos de transcripción a probar (coma).")

    models = sub.add_parser("modelos", help="Lista o descarga modelos locales (requiere confirmación).")
    models.add_argument("accion", choices=["listar", "descargar"])
    models.add_argument("--ocr", action="store_true", help="Modelos de EasyOCR (sólo CPU).")
    models.add_argument("--ocr-openvino", action="store_true", help="Modelos OCR para OpenVINO (GPU/NPU/CPU Intel).")
    models.add_argument("--whisper", help="Modelo faster-whisper a descargar (tiny, base, small, medium…).")
    models.add_argument(
        "--whisper-openvino", help="Modelo Whisper ya convertido a OpenVINO para GPU/NPU (tiny, base, small, medium…)."
    )
    models.add_argument("--precision", default="int8", choices=["int8", "int4", "fp16"])
    models.add_argument("--si", action="store_true", help="Confirma la descarga sin preguntar.")

    legacy = sub.add_parser("importar-legado", help="Importa una carpeta de resultados de la versión anterior.")
    legacy.add_argument("carpeta", type=Path)
    legacy.add_argument("--video", type=Path, required=True)
    legacy.add_argument("--salida", type=Path, default=default_projects_root())

    sub.add_parser("gui", help="Abre la aplicación de escritorio.")
    return parser


class _Printer:
    def __init__(self) -> None:
        self.last = 0.0

    def __call__(self, event: Any) -> None:
        from analizador_video.application import events as ev
        from analizador_video.domain.errors import UserMessage

        if isinstance(event, ev.StageStarted):
            device = "/".join(x for x in (event.backend, event.device) if x)
            print(f"▶ {event.stage}" + (f" [{device}]" if device else ""), file=sys.stderr)
        elif isinstance(event, ev.StageProgress):
            now = time.monotonic()
            if now - self.last >= 1.0 or (event.total and event.done >= event.total):
                self.last = now
                total = f"/{event.total}" if event.total else ""
                print(f"  {event.stage}: {event.done}{total} {event.detail}", file=sys.stderr)
        elif isinstance(event, ev.StageFinished):
            print(f"✓ {event.stage}: {event.status} {event.detail}".rstrip(), file=sys.stderr)
        elif isinstance(event, ev.WarningRaised):
            print(f"⚠ {event.message}", file=sys.stderr)
        elif isinstance(event, ev.LogLine):
            print(f"  {event.text}", file=sys.stderr)
        elif isinstance(event, ev.JobFailed):
            print(f"✗ {UserMessage.from_dict(event.message).text()}", file=sys.stderr)


def _run_engine(root: Path, args: argparse.Namespace) -> int:
    from analizador_video.application.analyze_video import AnalyzeVideo
    from analizador_video.application.backends import BackendRegistry
    from analizador_video.application.cancellation import EventToken
    from analizador_video.application.job_manager import new_run_id
    from analizador_video.domain.models import StagePlan

    run = _stage_set(args.pasos, "--pasos") | {StageName.PREPARE}
    force = _stage_set(args.forzar, "--forzar", allow_all=True) if args.forzar else set()
    if args.sin_ocr:
        run.discard(StageName.OCR)
    plan = StagePlan(
        frozenset(run),
        frozenset(force),
        not args.sin_transcripcion_automatica,
        not args.sin_ocr,
        DeviceKind(args.dispositivo),
    )
    token = EventToken()
    previous = signal.signal(signal.SIGINT, lambda *_: token.cancel())
    try:
        status = AnalyzeVideo(BackendRegistry.default()).run(root, plan, _Printer(), token, new_run_id())
    finally:
        signal.signal(signal.SIGINT, previous)
    if status is JobStatus.CANCELLED:
        print("Análisis cancelado. El avance quedó guardado; usa 'continuar' para reanudar.", file=sys.stderr)
        return EXIT_CANCELLED
    if status is JobStatus.FAILED:
        return EXIT_FAILURE
    print(f"Proyecto: {root}")
    return EXIT_OK


def _cmd_analyze(args: argparse.Namespace) -> int:
    from analizador_video.application.project_service import CreateProjectRequest, ProjectService
    from analizador_video.domain.validation import safe_filename
    from analizador_video.infrastructure.persistence.repository import DB_NAME

    _stage_set(args.pasos, "--pasos")  # valida antes de crear nada
    service = ProjectService(args.salida)
    project_id = safe_filename(args.nombre or args.video.stem, 90)
    root = args.salida / project_id
    if (root / DB_NAME).exists():
        print(f"Se reanudará el proyecto existente «{project_id}».", file=sys.stderr)
    else:
        args.salida.mkdir(parents=True, exist_ok=True)
        service.create(
            CreateProjectRequest(
                video=args.video,
                transcript=args.transcript,
                profile=PROFILE_ALIASES[args.perfil],
                source_mode=SourceMode.COPY if args.copiar_video else SourceMode.REFERENCE,
                project_id=project_id,
                config_path=args.config,
            )
        )
    return _run_engine(root, args)


def _cmd_resume(args: argparse.Namespace) -> int:
    from analizador_video.application.project_service import ProjectService

    return _run_engine(ProjectService(args.salida).resolve(args.proyecto), args)


def _cmd_export(args: argparse.Namespace) -> int:
    from analizador_video.application.export_reports import ExportReports
    from analizador_video.application.project_service import ProjectService

    root = ProjectService(args.salida).resolve(args.proyecto)
    try:
        kinds = [ReportKind(k.strip()) for k in args.formatos.split(",") if k.strip()]
    except ValueError as error:
        raise InputValidationError(
            "Formato de reporte no reconocido",
            "No se generaron reportes",
            f"Usa: {', '.join(k.value for k in ReportKind)}",
        ) from error
    for artifact in ExportReports().run(root, kinds, args.destino, not args.sin_datos_sensibles):
        print(artifact.path)
    return EXIT_OK


def _cmd_diagnose(args: argparse.Namespace) -> int:
    from analizador_video.application.backends import BackendRegistry
    from analizador_video.application.cancellation import EventToken
    from analizador_video.application.diagnostics import collect_diagnostics, run_benchmark
    from analizador_video.config.settings import load_settings

    registry = BackendRegistry.default()
    models = [m.strip() for m in args.modelos.split(",") if m.strip()] or [load_settings().transcript.modelo_whisper]
    if args.probar:
        token = EventToken()
        previous = signal.signal(signal.SIGINT, lambda *_: token.cancel())
        try:
            run_benchmark(
                registry,
                models,
                token,
                lambda r: print(
                    f"  {r.task}/{r.backend}/{r.model}/{r.device}: {r.status} – {r.reason}", file=sys.stderr
                ),
            )
        finally:
            signal.signal(signal.SIGINT, previous)
    data = collect_diagnostics(registry, models)
    for cap in data["capabilities"]:
        version = f" ({cap['version']})" if cap.get("version") else ""
        print(f"{cap['component']:<34} {cap['status']:<24} {cap['detail']}{version}")
    print("\nBackend | Modelo | CPU | GPU | NPU | Estado | Motivo")
    for row in data["matriz"]:
        print(" | ".join(row[k] for k in ("backend", "modelo", "cpu", "gpu", "npu", "estado", "motivo")))
    if args.json:
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nDiagnóstico guardado en {args.json}")
    return EXIT_OK


def _cmd_models(args: argparse.Namespace) -> int:
    from analizador_video.application.backends import BackendRegistry
    from analizador_video.config.settings import load_settings
    from analizador_video.infrastructure.paths import models_dir

    registry = BackendRegistry.default()
    settings = load_settings()
    if args.accion == "listar":
        print(f"Carpeta de modelos: {models_dir()}")
        model = settings.transcript.modelo_whisper
        for name, backend in registry.transcription.items():
            print(
                f"{name}: instalado={backend.is_installed()} "
                f"modelo «{model}» disponible={backend.model_available(model)}"
            )
        for name, ocr in registry.ocr.items():
            print(f"{name}: instalado={ocr.is_installed()} modelos={ocr.models_available(settings.ocr.idiomas)}")
        return EXIT_OK
    targets = (
        (["OCR (EasyOCR)"] if args.ocr else [])
        + (["OCR OpenVINO (RapidOCR)"] if args.ocr_openvino else [])
        + ([f"Whisper «{args.whisper}»"] if args.whisper else [])
        + ([f"Whisper OpenVINO «{args.whisper_openvino}» ({args.precision})"] if args.whisper_openvino else [])
    )
    if not targets:
        raise InputValidationError(
            "No se indicó qué descargar",
            "No se descargó nada",
            "Usa --ocr-openvino y/o --whisper-openvino MODELO (o --ocr / --whisper para CPU)",
        )
    print(f"Se descargarán de Internet: {', '.join(targets)} en {models_dir()}.", file=sys.stderr)
    if not args.si and input("¿Continuar? [s/N]: ").strip().lower() not in ("s", "si", "sí"):
        print("Descarga cancelada.", file=sys.stderr)
        return EXIT_CANCELLED
    if args.ocr:
        registry.ocr["easyocr"].load(settings.ocr.idiomas, DeviceKind.CPU, allow_download=True)
    if args.ocr_openvino:
        registry.ocr["rapidocr_openvino"].load(settings.ocr.idiomas, DeviceKind.CPU, allow_download=True)
    if args.whisper:
        registry.transcription["faster_whisper"].load(args.whisper, DeviceKind.CPU, allow_download=True)
    if args.whisper_openvino:
        registry.transcription["openvino"].download(args.whisper_openvino, args.precision)  # type: ignore[attr-defined]
    print("Modelos descargados.", file=sys.stderr)
    return EXIT_OK


def _cmd_legacy(args: argparse.Namespace) -> int:
    from analizador_video.application.legacy_import import import_legacy_output
    from analizador_video.application.project_service import ProjectService

    args.salida.mkdir(parents=True, exist_ok=True)
    print(f"Proyecto importado: {import_legacy_output(args.carpeta, args.video, ProjectService(args.salida))}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "gui":
        from analizador_video.ui.app import main as gui_main

        return gui_main()
    from analizador_video.infrastructure.logging_setup import configure_logging
    from analizador_video.infrastructure.paths import logs_dir

    configure_logging(logs_dir(), args.log_level)
    handlers = {
        "analizar": _cmd_analyze,
        "continuar": _cmd_resume,
        "exportar": _cmd_export,
        "diagnostico": _cmd_diagnose,
        "modelos": _cmd_models,
        "importar-legado": _cmd_legacy,
    }
    try:
        return handlers[args.command](args)
    except (InputValidationError, ValueError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return EXIT_USAGE
    except AppError as error:
        print(f"✗ {error}", file=sys.stderr)
        if error.message.code == "configuracion_invalida":
            print(error.message.details, file=sys.stderr)
            return EXIT_USAGE
        return EXIT_FAILURE

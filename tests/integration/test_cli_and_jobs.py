import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from analizador_video.application.events import JobFailed, JobFinished, PartialResult, StageProgress
from analizador_video.application.job_manager import JobHandle, JobManager
from analizador_video.application.project_service import CreateProjectRequest, ProjectService
from analizador_video.cli import commands, legacy
from analizador_video.domain.enums import ProfileName, StageName
from analizador_video.infrastructure.persistence.repository import ProjectRepository

ROOT = Path(__file__).resolve().parents[2]


def test_cli_analyze_export_and_exit_codes(tmp_path, sample_video, sample_vtt, capsys):
    out = tmp_path / "proyectos"
    args = [
        "analizar",
        str(sample_video),
        "--transcript",
        str(sample_vtt),
        "--salida",
        str(out),
        "--sin-ocr",
        "--sin-transcripcion-automatica",
    ]
    assert commands.main(args) == 0
    assert (out / "demo" / "reports" / "reporte_analisis.docx").exists()
    assert commands.main(args) == 0
    assert "reutilizada" in capsys.readouterr().err
    assert (
        commands.main(
            [
                "exportar",
                "demo",
                "--salida",
                str(out),
                "--formatos",
                "srt,txt",
                "--destino",
                str(tmp_path / "exp"),
                "--sin-datos-sensibles",
            ]
        )
        == 0
    )
    assert "Ana" not in (tmp_path / "exp" / "transcripcion.srt").read_text(encoding="utf-8")
    assert commands.main(["exportar", "demo", "--salida", str(out), "--formatos", "pdf"]) == 2
    assert commands.main(["continuar", "no-existe", "--salida", str(out)]) == 1
    assert commands.main(["analizar", str(tmp_path / "nada.mp4"), "--salida", str(out)]) == 2
    assert commands.main(["analizar", str(sample_video), "--salida", str(out), "--pasos", "magia"]) == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("ocr: {guardar_cada: 0}\n", encoding="utf-8")
    assert (
        commands.main(["analizar", str(sample_video), "--salida", str(out), "--nombre", "otro", "--config", str(bad)])
        == 2
    )
    with pytest.raises(SystemExit) as info:
        commands.main(["--version"])
    assert info.value.code == 0


def test_cli_stage_dependency_exit_code(tmp_path, sample_video):
    assert commands.main(["analizar", str(sample_video), "--salida", str(tmp_path / "p"), "--pasos", "reporte"]) == 1


def test_legacy_flags_translation(tmp_path, monkeypatch, capsys):  # problema B
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("video: {}\n", encoding="utf-8")
    argv = legacy.to_modern_argv(["--video", "v.mp4", "--transcript", "t.vtt", "--sin-ia", "--forzar", "ocr"])
    assert "obsoleto" in capsys.readouterr().err
    assert argv[:4] == ["--log-level", "INFO", "analizar", "v.mp4"]
    assert "--sin-transcripcion-automatica" in argv
    assert argv[argv.index("--config") + 1] == "config.yaml"


def test_legacy_main_py_end_to_end(tmp_path, sample_video, sample_vtt):
    env = {**os.environ, "ANALIZADOR_VIDEO_HOME": str(tmp_path / "home")}
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "main.py"),
            "--video",
            str(sample_video),
            "--transcript",
            str(sample_vtt),
            "--salida",
            str(tmp_path / "salida"),
            "--sin-ia",
            "--sin-ocr",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "salida" / "demo" / "reports" / "reporte_analisis.xlsx").exists()


def _legacy_folder(tmp_path):
    folder = tmp_path / "salida" / "demo"
    (folder / "pantallas").mkdir(parents=True)
    (folder / "pantallas" / "P0001_00-00-00.jpg").write_bytes(b"jpg")
    frames = [
        {"id": "P0001", "archivo": "pantallas/P0001_00-00-00.jpg", "tiempo": 0.0, "cambio": 1.0, "motivo": "inicial"}
    ]
    (folder / "frames.json").write_text(json.dumps({"completo": True, "items": frames}), encoding="utf-8")
    (folder / "transcript.json").write_text(
        json.dumps({"items": [{"inicio": 1, "fin": 2, "hablante": "A", "texto": "Hola"}]}), encoding="utf-8"
    )
    ocr = [
        {
            "id": "P0001",
            "texto": "Guardar",
            "elementos": [{"texto": "Guardar", "confianza": 0.9, "caja": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        }
    ]
    (folder / "ocr.json").write_text(json.dumps({"items": ocr}), encoding="utf-8")
    return folder, frames


def test_import_legacy_output(tmp_path, sample_video):
    folder, frames = _legacy_folder(tmp_path)
    traversal = [*frames, {"id": "P0002", "archivo": "../../fuera.jpg", "tiempo": 4.0}]
    (folder / "frames.json").write_text(json.dumps({"items": traversal}), encoding="utf-8")
    assert (
        commands.main(["importar-legado", str(folder), "--video", str(sample_video), "--salida", str(tmp_path / "p")])
        == 2
    )  # path traversal rechazado
    (folder / "frames.json").write_text(json.dumps({"items": frames}), encoding="utf-8")
    assert (
        commands.main(["importar-legado", str(folder), "--video", str(sample_video), "--salida", str(tmp_path / "p2")])
        == 0
    )
    repo = ProjectRepository.open(next((tmp_path / "p2").iterdir()))
    assert len(repo.captures()) == 1 and repo.ocr_results()["P0001"].text == "Guardar"
    assert repo.segments()[0].text == "Hola"
    repo.close()


def _drain(handle: JobHandle, timeout: float = 90) -> list[object]:
    events: list[object] = []
    end = time.time() + timeout
    while time.time() < end and not handle.finished:
        events.extend(handle.poll())
        time.sleep(0.05)
    return events


def test_job_manager_runs_analysis_in_separate_process(tmp_path, isolated_home, sample_video):
    project = ProjectService(tmp_path / "p").create(CreateProjectRequest(sample_video, None, ProfileName.FAST))
    manager = JobManager(isolated_home)
    handle = manager.start(
        "analyze", {"project_root": str(project.root), "run_id": "r1", "stages": ["preparar", "pantallas"]}
    )
    assert handle.process.pid != os.getpid()
    events = _drain(handle)
    assert any(isinstance(e, StageProgress) for e in events) and any(isinstance(e, PartialResult) for e in events)
    assert isinstance(events[-1], JobFinished) and events[-1].status == "completed"
    assert manager.shutdown(5)


def test_job_manager_cancellation_saves_checkpoint(tmp_path, isolated_home, video_factory):
    video = video_factory("largo.mp4", scenes=4, seconds_per_scene=30, fps=25, size=(640, 480))
    project = ProjectService(tmp_path / "p").create(CreateProjectRequest(video, None, ProfileName.MAX_ACCURACY))
    handle = JobManager(isolated_home).start(
        "analyze", {"project_root": str(project.root), "run_id": "r1", "stages": ["preparar", "pantallas"]}
    )
    events: list[object] = []
    end = time.time() + 60
    while time.time() < end and not any(isinstance(e, StageProgress) and e.stage == "pantallas" for e in events):
        events.extend(handle.poll())
        time.sleep(0.02)
    handle.cancel()
    events.extend(_drain(handle))
    assert isinstance(events[-1], JobFinished) and events[-1].status == "cancelled"
    state = ProjectRepository.open(project.root).get_stage(StageName.FRAMES)
    assert state.status.value == "cancelled" and state.checkpoint.get("next_index", 0) > 0
    assert not (project.root / ".en_proceso.lock").exists()


def test_worker_unexpected_error_is_reported_without_traceback(isolated_home):
    events = _drain(JobManager(isolated_home).start("desconocido", {}), 30)
    failure = next(e for e in events if isinstance(e, JobFailed))
    assert failure.message["code"] == "error_inesperado"
    assert "Traceback" not in failure.message["what"] + failure.message["action"]
    assert isinstance(events[-1], JobFinished) and events[-1].status == "failed"


def test_handle_detects_killed_worker(isolated_home, tmp_path, sample_video):
    project = ProjectService(tmp_path / "p").create(CreateProjectRequest(sample_video, None, ProfileName.FAST))
    handle = JobManager(isolated_home).start("analyze", {"project_root": str(project.root), "run_id": "r1"})
    handle.process.kill()
    handle.process.join(5)
    events = _drain(handle, 10)
    assert isinstance(events[-1], JobFinished) and events[-1].status == "failed"

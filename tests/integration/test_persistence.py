import sqlite3

import pytest

from analizador_video.application.project_service import CreateProjectRequest, ProjectService
from analizador_video.domain.enums import ProfileName, StageName, StageStatus
from analizador_video.domain.errors import DatabaseError
from analizador_video.domain.models import ScreenCapture
from analizador_video.infrastructure.persistence.database import LATEST_VERSION, Database, restore_backup
from analizador_video.infrastructure.persistence.repository import ProjectRepository


def test_migrations_up_down_with_backup_and_rollback(tmp_path):
    path = tmp_path / "project.db"
    db = Database(path)
    db.migrate()
    assert db.version == LATEST_VERSION == 2
    with db.transaction() as conn:
        conn.execute("INSERT INTO run(id, status, started_at, app_version) VALUES ('r1','ok','t','0')")
        conn.execute("INSERT INTO stage(name, status, updated_at) VALUES ('pantallas','completed','t')")
    backup = db.migrate(1)  # rollback de la migración 2
    assert backup is not None and backup.exists() and db.version == 1
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "run" not in tables and "stage" in tables
    assert db.conn.execute("SELECT status FROM stage").fetchone()[0] == "completed"
    db.close()
    restore_backup(path, backup)
    with Database(path) as restored:
        assert restored.version == 2 and restored.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 1


def test_newer_schema_is_refused(tmp_path):
    db = Database(tmp_path / "project.db")
    db.migrate()
    with db.transaction() as conn:
        conn.execute("INSERT INTO schema_info VALUES (99, 'x', 't')")
    with pytest.raises(DatabaseError):
        db.migrate()


def test_constraints_and_foreign_keys(sample_video, projects_root):
    project = ProjectService(projects_root).create(CreateProjectRequest(sample_video, None, ProfileName.BALANCED))
    repo = ProjectRepository.open(project.root)
    state = repo.get_stage(StageName.FRAMES)
    repo.add_capture(ScreenCapture("P0001", 1, "frames/a.jpg", 0.0, 1.0, "inicial"), state)
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_capture(ScreenCapture("P0002", 1, "frames/b.jpg", 1.0, 1.0, "x"), state)
    with pytest.raises(sqlite3.IntegrityError), repo.db.transaction() as conn:
        conn.execute("INSERT INTO ocr_result VALUES ('NOEXISTE','t','[]','b','cpu',NULL)")
    with pytest.raises(sqlite3.IntegrityError), repo.db.transaction() as conn:
        conn.execute("INSERT INTO transcript_segment VALUES (1, 5, 4, 'a', 't', 'importada', NULL)")
    assert [c.id for c in repo.captures()] == ["P0001"]
    repo.close()


def test_invalidate_cascades(sample_video, projects_root):
    project = ProjectService(projects_root).create(CreateProjectRequest(sample_video, None, ProfileName.BALANCED))
    repo = ProjectRepository.open(project.root)
    for name in StageName.ordered():
        state = repo.get_stage(name)
        state.status = StageStatus.COMPLETED
        repo.save_stage(state)
    assert repo.invalidate(StageName.FRAMES) == [StageName.FRAMES, StageName.OCR, StageName.ALIGN, StageName.REPORT]
    assert repo.get_stage(StageName.TRANSCRIPT).status is StageStatus.COMPLETED
    repo.close()


def test_interrupted_recovery(sample_video, projects_root):
    project = ProjectService(projects_root).create(CreateProjectRequest(sample_video, None, ProfileName.BALANCED))
    repo = ProjectRepository.open(project.root)
    state = repo.get_stage(StageName.FRAMES)
    state.status = StageStatus.RUNNING
    repo.save_stage(state)
    repo.close()
    assert ProjectService(projects_root).summary(project.root).status == "interrumpido"
    repo = ProjectRepository.open(project.root)
    assert repo.mark_interrupted() == [StageName.FRAMES]
    repo.close()

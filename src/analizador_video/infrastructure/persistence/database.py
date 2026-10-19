"""SQLite por proyecto: transacciones, claves foráneas, migraciones con respaldo y rollback.

Nunca se guardan binarios grandes: imágenes, audio y documentos viven en la carpeta del proyecto.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from analizador_video import __version__
from analizador_video.domain.errors import DatabaseError


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    up: str
    down: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "Esquema inicial de proyecto",
        """
        CREATE TABLE project (
            id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK (length(name) > 0), source_path TEXT NOT NULL,
            source_mode TEXT NOT NULL CHECK (source_mode IN ('referencia', 'copia')), source_stored_rel TEXT,
            source_size INTEGER NOT NULL CHECK (source_size >= 0), source_fingerprint TEXT NOT NULL,
            video_meta_json TEXT, transcript_path TEXT, profile TEXT NOT NULL, config_json TEXT NOT NULL,
            app_version TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE stage (
            name TEXT PRIMARY KEY, status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0 CHECK (done >= 0),
            total INTEGER CHECK (total IS NULL OR total >= 0), checkpoint_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT, error_message TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE capture (
            id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE CHECK (seq > 0), file_rel TEXT NOT NULL UNIQUE,
            time_seconds REAL NOT NULL CHECK (time_seconds >= 0), change_score REAL NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX idx_capture_time ON capture(time_seconds);
        CREATE TABLE transcript_segment (
            seq INTEGER PRIMARY KEY CHECK (seq > 0), start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
            end_seconds REAL NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
            confidence REAL, CHECK (end_seconds >= start_seconds));
        CREATE INDEX idx_segment_start ON transcript_segment(start_seconds);
        CREATE TABLE ocr_result (
            capture_id TEXT PRIMARY KEY REFERENCES capture(id) ON DELETE CASCADE, text TEXT NOT NULL,
            blocks_json TEXT NOT NULL, backend TEXT NOT NULL, device TEXT NOT NULL, error_code TEXT);
        CREATE TABLE alignment (
            capture_id TEXT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
            segment_seq INTEGER NOT NULL REFERENCES transcript_segment(seq) ON DELETE CASCADE,
            PRIMARY KEY (capture_id, segment_seq));
        CREATE TABLE correction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('ocr', 'segmento', 'captura')),
            entity_id TEXT NOT NULL, field_name TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE INDEX idx_correction_entity ON correction(entity_type, entity_id);
        CREATE TABLE report (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, path TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT, code TEXT NOT NULL, message TEXT NOT NULL,
            recoverable INTEGER NOT NULL CHECK (recoverable IN (0, 1)), created_at TEXT NOT NULL);
        """,
        """
        DROP TABLE IF EXISTS error_log; DROP TABLE IF EXISTS report; DROP TABLE IF EXISTS correction;
        DROP TABLE IF EXISTS alignment; DROP TABLE IF EXISTS ocr_result; DROP TABLE IF EXISTS transcript_segment;
        DROP TABLE IF EXISTS capture; DROP TABLE IF EXISTS stage; DROP TABLE IF EXISTS project;
        """,
    ),
    Migration(
        2,
        "Ejecuciones y métricas por etapa (backend, dispositivo, duración)",
        """
        CREATE TABLE run (id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
            app_version TEXT NOT NULL);
        CREATE TABLE stage_metric (
            run_id TEXT NOT NULL REFERENCES run(id) ON DELETE CASCADE, stage TEXT NOT NULL, backend TEXT,
            device TEXT, precision TEXT, duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
            items INTEGER, peak_rss_mb REAL, result TEXT NOT NULL, PRIMARY KEY (run_id, stage));
        """,
        "DROP TABLE IF EXISTS stage_metric; DROP TABLE IF EXISTS run;",
    ),
)
LATEST_VERSION = MIGRATIONS[-1].version


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as error:
            raise DatabaseError(
                "No se pudo abrir la base de datos del proyecto",
                "El proyecto no se puede cargar",
                "Verifica que la carpeta del proyecto exista y tengas permisos de escritura",
            ) from error
        self.conn.row_factory = sqlite3.Row
        for pragma in ("foreign_keys = ON", "journal_mode = WAL", "synchronous = NORMAL", "busy_timeout = 10000"):
            self.conn.execute(f"PRAGMA {pragma}")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL, "
            "app_version TEXT NOT NULL, migrated_at TEXT NOT NULL)"
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    @property
    def version(self) -> int:
        row = self.conn.execute("SELECT MAX(version) AS v FROM schema_info").fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0

    def backup(self, label: str) -> Path:
        """Copia consistente mediante la API de respaldo de SQLite (válida aun con WAL)."""
        target = self.path.with_name(f"{self.path.stem}.backup-{label}.db")
        dest = sqlite3.connect(str(target))
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        return target

    def migrate(self, target: int = LATEST_VERSION) -> Path | None:
        current = self.version
        if current > LATEST_VERSION:
            raise DatabaseError(
                "El proyecto fue creado con una versión más reciente de la aplicación",
                "No se puede abrir con esta versión",
                "Actualiza la aplicación para abrir este proyecto",
            )
        if current == target:
            return None
        backup = self.backup(f"v{current}") if current > 0 else None
        try:
            if target > current:
                for migration in MIGRATIONS:
                    if current < migration.version <= target:
                        self._apply(migration.up, migration.version)
            else:
                for migration in reversed(MIGRATIONS):
                    if target < migration.version <= current:
                        self._apply(migration.down, migration.version - 1, down=True)
        except sqlite3.Error as error:
            raise DatabaseError(
                "La actualización de la base de datos del proyecto falló",
                "El proyecto no se modificó",
                "Se conservó un respaldo junto a project.db; comparte el diagnóstico con soporte",
                saved=True,
                details=str(error),
            ) from error
        return backup

    def _apply(self, script: str, new_version: int, down: bool = False) -> None:
        statements = [s.strip() for s in script.split(";") if s.strip()]
        with self.transaction() as conn:
            for statement in statements:
                conn.execute(statement)
            if down:
                conn.execute("DELETE FROM schema_info WHERE version > ?", (new_version,))
            else:
                conn.execute(
                    "INSERT INTO schema_info(version, app_version, migrated_at) VALUES (?, ?, ?)",
                    (new_version, __version__, utc_now()),
                )


def restore_backup(db_path: Path, backup_path: Path) -> None:
    """Rollback manual: reemplaza project.db por un respaldo (la aplicación debe estar cerrada)."""
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, db_path)

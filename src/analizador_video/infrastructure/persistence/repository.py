"""Repositorio del proyecto. Única puerta de acceso a SQLite (los reportes no la usan)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from analizador_video import __version__
from analizador_video.domain.enums import (
    STAGE_DEPENDENTS,
    ProfileName,
    ReportKind,
    SourceMode,
    StageName,
    StageStatus,
    TranscriptSource,
)
from analizador_video.domain.models import (
    OcrBlock,
    OcrResult,
    ProcessingError,
    Project,
    ReportArtifact,
    ScreenCapture,
    SourceVideo,
    StageState,
    TranscriptSegment,
    UserCorrection,
    VideoMetadata,
)
from analizador_video.infrastructure.persistence.database import Database, utc_now

DB_NAME = "project.db"
_DATA_TABLE = {
    StageName.FRAMES: "capture",
    StageName.TRANSCRIPT: "transcript_segment",
    StageName.OCR: "ocr_result",
    StageName.ALIGN: "alignment",
}


def _meta_from_json(raw: str | None) -> VideoMetadata | None:
    return VideoMetadata(**json.loads(raw)) if raw else None


class ProjectRepository:
    def __init__(self, root: Path, db: Database):
        self.root = root
        self.db = db

    @classmethod
    def open(cls, root: Path) -> ProjectRepository:
        db = Database(root / DB_NAME)
        db.migrate()
        return cls(root, db)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ proyecto
    def create_project(self, project: Project, config: dict[str, Any]) -> None:
        src = project.source
        stored_rel = src.stored_path.relative_to(self.root).as_posix() if src.stored_path else None
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO project(id, name, source_path, source_mode, source_stored_rel, source_size, "
                "source_fingerprint, video_meta_json, transcript_path, profile, config_json, app_version, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    project.id,
                    project.name,
                    str(src.original_path),
                    src.mode.value,
                    stored_rel,
                    src.size_bytes,
                    src.fingerprint,
                    json.dumps(src.metadata.__dict__) if src.metadata else None,
                    str(project.transcript_path) if project.transcript_path else None,
                    project.profile.value,
                    json.dumps(config, ensure_ascii=False),
                    project.app_version,
                    project.created_at,
                    project.updated_at,
                ),
            )
            for name in StageName.ordered():
                conn.execute(
                    "INSERT INTO stage(name, status, updated_at) VALUES (?, ?, ?)",
                    (name.value, StageStatus.PENDING.value, utc_now()),
                )

    def get_project(self) -> Project:
        row = self.db.conn.execute("SELECT * FROM project").fetchone()
        if row is None:
            raise LookupError("El proyecto no tiene datos.")
        stored = self.root / row["source_stored_rel"] if row["source_stored_rel"] else None
        source = SourceVideo(
            Path(row["source_path"]),
            SourceMode(row["source_mode"]),
            int(row["source_size"]),
            row["source_fingerprint"],
            _meta_from_json(row["video_meta_json"]),
            stored,
        )
        return Project(
            row["id"],
            row["name"],
            self.root,
            source,
            ProfileName(row["profile"]),
            Path(row["transcript_path"]) if row["transcript_path"] else None,
            row["created_at"],
            row["updated_at"],
            row["app_version"],
        )

    def get_config(self) -> dict[str, Any]:
        row = self.db.conn.execute("SELECT config_json FROM project").fetchone()
        data = json.loads(row["config_json"]) if row else {}
        assert isinstance(data, dict)
        return data

    def set_config(self, config: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE project SET config_json = ?, updated_at = ?",
                (json.dumps(config, ensure_ascii=False), utc_now()),
            )

    def update_source(self, metadata: VideoMetadata, stored_path: Path | None, fingerprint: str) -> None:
        stored_rel = stored_path.relative_to(self.root).as_posix() if stored_path else None
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE project SET video_meta_json = ?, source_stored_rel = COALESCE(?, source_stored_rel), "
                "source_fingerprint = ?, updated_at = ?",
                (json.dumps(metadata.__dict__), stored_rel, fingerprint, utc_now()),
            )

    def touch(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE project SET updated_at = ?, app_version = ?", (utc_now(), __version__))

    # ------------------------------------------------------------------ etapas
    def get_stage(self, name: StageName) -> StageState:
        row = self.db.conn.execute("SELECT * FROM stage WHERE name = ?", (name.value,)).fetchone()
        if row is None:
            return StageState(name=name)
        return StageState(
            name,
            StageStatus(row["status"]),
            int(row["done"]),
            row["total"],
            json.loads(row["checkpoint_json"] or "{}"),
            row["error_code"],
            row["error_message"],
            row["updated_at"],
        )

    def stages(self) -> dict[StageName, StageState]:
        return {name: self.get_stage(name) for name in StageName.ordered()}

    def save_stage(self, state: StageState, conn: Any | None = None) -> None:
        sql = (
            "UPDATE stage SET status=?, done=?, total=?, checkpoint_json=?, error_code=?, error_message=?, "
            "updated_at=? WHERE name=?"
        )
        params = (
            state.status.value,
            state.done,
            state.total,
            json.dumps(state.checkpoint),
            state.error_code,
            state.error_message,
            utc_now(),
            state.name.value,
        )
        if conn is not None:
            conn.execute(sql, params)
        else:
            with self.db.transaction() as tx:
                tx.execute(sql, params)

    def mark_interrupted(self) -> list[StageName]:
        """Tras un cierre inesperado, las etapas que quedaron 'running' pasan a 'interrupted'."""
        rows = self.db.conn.execute("SELECT name FROM stage WHERE status = ?", (StageStatus.RUNNING.value,)).fetchall()
        names = [StageName(r["name"]) for r in rows]
        if names:
            with self.db.transaction() as conn:
                conn.execute(
                    "UPDATE stage SET status = ?, updated_at = ? WHERE status = ?",
                    (StageStatus.INTERRUPTED.value, utc_now(), StageStatus.RUNNING.value),
                )
        return names

    def invalidate(self, name: StageName) -> list[StageName]:
        """Borra los datos de una etapa y de sus dependientes. Devuelve las etapas invalidadas."""
        pending, affected = [name], []
        while pending:
            current = pending.pop(0)
            if current not in affected:
                affected.append(current)
                pending.extend(STAGE_DEPENDENTS[current])
        with self.db.transaction() as conn:
            for stage in affected:
                if stage in _DATA_TABLE:
                    conn.execute(f"DELETE FROM {_DATA_TABLE[stage]}")
                conn.execute(
                    "UPDATE stage SET status=?, done=0, total=NULL, checkpoint_json='{}', error_code=NULL, "
                    "error_message=NULL, updated_at=? WHERE name=?",
                    (StageStatus.PENDING.value, utc_now(), stage.value),
                )
        return affected

    # ------------------------------------------------------------------ capturas
    def add_capture(self, capture: ScreenCapture, frames_state: StageState) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO capture(id, seq, file_rel, time_seconds, change_score, reason, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    capture.id,
                    capture.seq,
                    capture.file_rel,
                    capture.time_seconds,
                    capture.change_score,
                    capture.reason,
                    utc_now(),
                ),
            )
            self.save_stage(frames_state, conn)

    def captures(self) -> list[ScreenCapture]:
        rows = self.db.conn.execute("SELECT * FROM capture ORDER BY time_seconds, seq").fetchall()
        return [
            ScreenCapture(
                r["id"], int(r["seq"]), r["file_rel"], float(r["time_seconds"]), float(r["change_score"]), r["reason"]
            )
            for r in rows
        ]

    def capture_files(self) -> set[str]:
        return {r["file_rel"] for r in self.db.conn.execute("SELECT file_rel FROM capture").fetchall()}

    # ------------------------------------------------------------------ transcripción
    def replace_segments(self, segments: Iterable[TranscriptSegment], state: StageState) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transcript_segment")
            self._insert_segments(conn, segments)
            self.save_stage(state, conn)

    def append_segments(self, segments: Iterable[TranscriptSegment], state: StageState) -> None:
        with self.db.transaction() as conn:
            self._insert_segments(conn, segments)
            self.save_stage(state, conn)

    @staticmethod
    def _insert_segments(conn: Any, segments: Iterable[TranscriptSegment]) -> None:
        conn.executemany(
            "INSERT INTO transcript_segment(seq, start_seconds, end_seconds, speaker, text, source, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (s.seq, s.start_seconds, s.end_seconds, s.speaker, s.text, s.source.value, s.confidence)
                for s in segments
            ],
        )

    def segments(self) -> list[TranscriptSegment]:
        rows = self.db.conn.execute("SELECT * FROM transcript_segment ORDER BY start_seconds, seq").fetchall()
        return [
            TranscriptSegment(
                int(r["seq"]),
                float(r["start_seconds"]),
                float(r["end_seconds"]),
                r["speaker"],
                r["text"],
                TranscriptSource(r["source"]),
                r["confidence"],
            )
            for r in rows
        ]

    def max_segment_seq(self) -> int:
        row = self.db.conn.execute("SELECT MAX(seq) AS m FROM transcript_segment").fetchone()
        return int(row["m"]) if row and row["m"] is not None else 0

    # ------------------------------------------------------------------ OCR
    def save_ocr(self, results: Iterable[OcrResult], state: StageState) -> None:
        rows = [
            (
                r.capture_id,
                r.text,
                json.dumps(
                    [{"texto": b.text, "confianza": b.confidence, "caja": [list(p) for p in b.box]} for b in r.blocks],
                    ensure_ascii=False,
                ),
                r.backend,
                r.device,
                r.error_code,
            )
            for r in results
        ]
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO ocr_result(capture_id, text, blocks_json, backend, device, "
                "error_code) VALUES (?,?,?,?,?,?)",
                rows,
            )
            self.save_stage(state, conn)

    def ocr_results(self) -> dict[str, OcrResult]:
        result: dict[str, OcrResult] = {}
        for r in self.db.conn.execute("SELECT * FROM ocr_result").fetchall():
            blocks = tuple(
                OcrBlock(b["texto"], float(b["confianza"]), tuple((float(p[0]), float(p[1])) for p in b["caja"]))
                for b in json.loads(r["blocks_json"])
            )
            result[r["capture_id"]] = OcrResult(
                r["capture_id"], r["text"], blocks, r["backend"], r["device"], r["error_code"]
            )
        return result

    # ------------------------------------------------------------------ alineación, correcciones, reportes
    def save_alignment(self, pairs: Iterable[tuple[str, int]], state: StageState) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM alignment")
            conn.executemany("INSERT INTO alignment(capture_id, segment_seq) VALUES (?, ?)", list(pairs))
            self.save_stage(state, conn)

    def corrections(self) -> list[UserCorrection]:
        rows = self.db.conn.execute("SELECT * FROM correction ORDER BY id").fetchall()
        return [
            UserCorrection(
                r["entity_type"], r["entity_id"], r["field_name"], r["old_value"], r["new_value"], r["created_at"]
            )
            for r in rows
        ]

    def add_correction(self, c: UserCorrection) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO correction(entity_type, entity_id, field_name, old_value, new_value, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (c.entity_type, c.entity_id, c.field_name, c.old_value, c.new_value, c.created_at or utc_now()),
            )

    def add_reports(self, artifacts: Iterable[ReportArtifact]) -> None:
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT INTO report(kind, path, created_at) VALUES (?,?,?)",
                [(a.kind.value, str(a.path), a.created_at) for a in artifacts],
            )

    def reports(self) -> list[ReportArtifact]:
        rows = self.db.conn.execute("SELECT * FROM report ORDER BY id").fetchall()
        return [ReportArtifact(ReportKind(r["kind"]), Path(r["path"]), r["created_at"]) for r in rows]

    def add_error(self, error: ProcessingError) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO error_log(stage, code, message, recoverable, created_at) VALUES (?,?,?,?,?)",
                (
                    error.stage.value if error.stage else None,
                    error.code,
                    error.message[:2000],
                    int(error.recoverable),
                    utc_now(),
                ),
            )

    def errors(self, limit: int = 50) -> list[ProcessingError]:
        rows = self.db.conn.execute("SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            ProcessingError(
                r["code"],
                StageName(r["stage"]) if r["stage"] else None,
                r["message"],
                bool(r["recoverable"]),
                r["created_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ ejecuciones y métricas
    def start_run(self, run_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO run(id, status, started_at, app_version) VALUES (?,?,?,?)",
                (run_id, "running", utc_now(), __version__),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE run SET status=?, finished_at=? WHERE id=?", (status, utc_now(), run_id))

    def add_metric(
        self,
        run_id: str,
        stage: StageName,
        meta: dict[str, str | None],
        duration_ms: int,
        items: int | None,
        peak_rss_mb: float | None,
        result: str,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stage_metric(run_id, stage, backend, device, precision, duration_ms, "
                "items, peak_rss_mb, result) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    stage.value,
                    meta.get("backend"),
                    meta.get("device"),
                    meta.get("precision"),
                    duration_ms,
                    items,
                    peak_rss_mb,
                    result,
                ),
            )

    def metrics(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.conn.execute("SELECT * FROM stage_metric WHERE run_id = ?", (run_id,)).fetchall()
        return [dict(r) for r in rows]

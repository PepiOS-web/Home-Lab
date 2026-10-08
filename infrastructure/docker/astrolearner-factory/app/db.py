from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import ContentPackage, JobView

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    topic TEXT NOT NULL,
    source_urls_json TEXT NOT NULL,
    target_seconds INTEGER NOT NULL,
    status TEXT NOT NULL,
    pending_action TEXT,
    progress TEXT NOT NULL DEFAULT '',
    error TEXT,
    package_json TEXT,
    approved_script_at TEXT,
    approved_render_at TEXT,
    output_dir TEXT,
    render_hash TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_queue
ON jobs(status, pending_action, created_at);

CREATE INDEX IF NOT EXISTS idx_events_job
ON events(job_id, id);
"""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def recover_interrupted_jobs(self) -> int:
        timestamp = now_iso()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = 'processing'"
            ).fetchall()
            for row in rows:
                message = (
                    "El servicio se reinició durante el procesamiento; "
                    "revisa el estado y vuelve a intentar la etapa"
                )
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', pending_action = NULL, progress = ?,
                        error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "Trabajo interrumpido por un reinicio",
                        message,
                        timestamp,
                        row["id"],
                    ),
                )
                self._add_event(connection, row["id"], "error", message)
        return len(rows)

    def create_job(
        self, topic: str, source_urls: list[str], target_seconds: int
    ) -> str:
        job_id = str(uuid.uuid4())
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, created_at, updated_at, topic, source_urls_json,
                    target_seconds, status, pending_action, progress
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'generate', ?)
                """,
                (
                    job_id,
                    timestamp,
                    timestamp,
                    topic,
                    json.dumps(source_urls, ensure_ascii=False),
                    target_seconds,
                    "Esperando turno para investigar y generar el guion",
                ),
            )
            self._add_event(connection, job_id, "info", "Trabajo creado")
        return job_id

    def list_jobs(self, limit: int = 50) -> list[JobView]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get_job(self, job_id: str) -> JobView | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, level, message
                FROM events WHERE job_id = ? ORDER BY id DESC LIMIT 100
                """,
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_next_job(self) -> tuple[JobView, str] | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued' AND pending_action IS NOT NULL
                ORDER BY created_at ASC LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            action = row["pending_action"]
            timestamp = now_iso()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'processing', pending_action = NULL,
                    updated_at = ?, progress = ?, error = NULL
                WHERE id = ?
                """,
                (timestamp, f"Ejecutando etapa: {action}", row["id"]),
            )
            self._add_event(connection, row["id"], "info", f"Etapa iniciada: {action}")
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        return self._row_to_job(updated), action

    def queue_action(self, job_id: str, action: str, message: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', pending_action = ?, progress = ?,
                    error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (action, message, timestamp, job_id),
            )
            self._add_event(connection, job_id, "info", message)

    def set_progress(self, job_id: str, progress: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (progress, now_iso(), job_id),
            )

    def complete_generation(
        self, job_id: str, package: ContentPackage, output_dir: str
    ) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'script_ready', progress = ?, package_json = ?,
                    output_dir = ?, updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (
                    "Guion listo para revisión humana",
                    package.model_dump_json(),
                    output_dir,
                    timestamp,
                    job_id,
                ),
            )
            self._add_event(connection, job_id, "info", "Guion generado")

    def update_package(self, job_id: str, package: ContentPackage) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "script_ready":
                raise ValueError(
                    "Solo se puede editar un guion pendiente de aprobación"
                )
            connection.execute(
                """
                UPDATE jobs
                SET package_json = ?, approved_script_at = NULL,
                    progress = ?, updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (
                    package.model_dump_json(),
                    "Cambios guardados; pendiente de revisión humana",
                    timestamp,
                    job_id,
                ),
            )
            self._add_event(connection, job_id, "info", "Guion editado manualmente")

    def reject_script(self, job_id: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "script_ready":
                raise ValueError("El guion no está pendiente de revisión")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'rejected', pending_action = NULL,
                    progress = ?, updated_at = ?
                WHERE id = ?
                """,
                ("Guion rechazado; no se renderizará", timestamp, job_id),
            )
            self._add_event(connection, job_id, "info", "Guion rechazado")

    def approve_script_and_queue_render(self, job_id: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "script_ready":
                raise ValueError("El guion no está pendiente de aprobación")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', pending_action = 'render',
                    approved_script_at = ?, approved_render_at = NULL,
                    progress = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    timestamp,
                    "Guion aprobado; esperando turno de render",
                    timestamp,
                    job_id,
                ),
            )
            self._add_event(connection, job_id, "info", "Guion aprobado")

    def complete_render(self, job_id: str, render_hash: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'review_required', progress = ?, render_hash = ?,
                    approved_render_at = NULL, updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (
                    "Render listo para revisión humana",
                    render_hash,
                    timestamp,
                    job_id,
                ),
            )
            self._add_event(connection, job_id, "info", "Render completado")

    def approve_render(self, job_id: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] != "review_required":
                raise ValueError("El vídeo no está pendiente de aprobación")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'approved', progress = ?, approved_render_at = ?,
                    updated_at = ? WHERE id = ?
                """,
                (
                    "Vídeo aprobado; la publicación aún está desactivada",
                    timestamp,
                    timestamp,
                    job_id,
                ),
            )
            self._add_event(connection, job_id, "info", "Render aprobado")

    def queue_rerender(self, job_id: str) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status, package_json, approved_script_at
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] not in {"review_required", "approved"}
                or not row["package_json"]
                or not row["approved_script_at"]
            ):
                raise ValueError("Este trabajo no se puede volver a renderizar")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', pending_action = 'render',
                    approved_render_at = NULL, progress = ?, error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                ("Nuevo render solicitado", timestamp, job_id),
            )
            self._add_event(connection, job_id, "info", "Nuevo render solicitado")

    def fail_job(self, job_id: str, error: str) -> None:
        timestamp = now_iso()
        safe_error = error[:4000]
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', progress = 'La etapa ha fallado',
                    error = ?, updated_at = ? WHERE id = ?
                """,
                (safe_error, timestamp, job_id),
            )
            self._add_event(connection, job_id, "error", safe_error)

    @staticmethod
    def _add_event(
        connection: sqlite3.Connection,
        job_id: str,
        level: str,
        message: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(job_id, created_at, level, message)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, now_iso(), level, message[:4000]),
        )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobView:
        package = (
            ContentPackage.model_validate_json(row["package_json"])
            if row["package_json"]
            else None
        )
        return JobView(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            topic=row["topic"],
            source_urls=json.loads(row["source_urls_json"]),
            target_seconds=row["target_seconds"],
            status=row["status"],
            pending_action=row["pending_action"],
            progress=row["progress"],
            error=row["error"],
            package=package,
            approved_script_at=row["approved_script_at"],
            approved_render_at=row["approved_render_at"],
            output_dir=row["output_dir"],
        )

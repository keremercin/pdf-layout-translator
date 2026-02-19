import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pdf_translator.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              source_lang TEXT NOT NULL,
              target_lang TEXT NOT NULL,
              input_path TEXT NOT NULL,
              output_path TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_job(job_id: str, source_lang: str, target_lang: str, input_path: str) -> None:
    ts = _now()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, status, source_lang, target_lang, input_path, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?, ?, ?)
            """,
            (job_id, source_lang, target_lang, input_path, ts, ts),
        )
        conn.commit()


def update_job_status(job_id: str, status: str, output_path: str | None = None, error: str | None = None) -> None:
    ts = _now()
    with _conn() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, output_path = COALESCE(?, output_path), error = COALESCE(?, error), updated_at = ?
            WHERE job_id = ?
            """,
            (status, output_path, error, ts, job_id),
        )
        conn.commit()


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None

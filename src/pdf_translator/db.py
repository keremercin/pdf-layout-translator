import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pdf_translator.config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=settings.retention_hours)).isoformat()


def _conn() -> sqlite3.Connection:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              telegram_user_id INTEGER PRIMARY KEY,
              available_credits INTEGER NOT NULL DEFAULT 0,
              reserved_credits INTEGER NOT NULL DEFAULT 0,
              is_blocked INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_ledger (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              telegram_user_id INTEGER NOT NULL,
              type TEXT NOT NULL,
              pages INTEGER NOT NULL,
              job_id TEXT,
              external_ref TEXT,
              note TEXT,
              created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              job_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              source_lang TEXT NOT NULL,
              target_lang TEXT NOT NULL,
              owner_telegram_user_id INTEGER NOT NULL DEFAULT 0,
              input_path TEXT NOT NULL,
              output_path TEXT,
              error TEXT,
              pages_total INTEGER NOT NULL DEFAULT 0,
              pages_processed INTEGER NOT NULL DEFAULT 0,
              credits_reserved INTEGER NOT NULL DEFAULT 0,
              credits_charged INTEGER NOT NULL DEFAULT 0,
              failure_reason_code TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              cleaned_at TEXT
            )
            """
        )

        if not _has_col(conn, "jobs", "owner_telegram_user_id"):
            conn.execute("ALTER TABLE jobs ADD COLUMN owner_telegram_user_id INTEGER NOT NULL DEFAULT 0")
        if not _has_col(conn, "jobs", "pages_total"):
            conn.execute("ALTER TABLE jobs ADD COLUMN pages_total INTEGER NOT NULL DEFAULT 0")
        if not _has_col(conn, "jobs", "pages_processed"):
            conn.execute("ALTER TABLE jobs ADD COLUMN pages_processed INTEGER NOT NULL DEFAULT 0")
        if not _has_col(conn, "jobs", "credits_reserved"):
            conn.execute("ALTER TABLE jobs ADD COLUMN credits_reserved INTEGER NOT NULL DEFAULT 0")
        if not _has_col(conn, "jobs", "credits_charged"):
            conn.execute("ALTER TABLE jobs ADD COLUMN credits_charged INTEGER NOT NULL DEFAULT 0")
        if not _has_col(conn, "jobs", "failure_reason_code"):
            conn.execute("ALTER TABLE jobs ADD COLUMN failure_reason_code TEXT")
        if not _has_col(conn, "jobs", "expires_at"):
            conn.execute("ALTER TABLE jobs ADD COLUMN expires_at TEXT")
        if not _has_col(conn, "jobs", "cleaned_at"):
            conn.execute("ALTER TABLE jobs ADD COLUMN cleaned_at TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_pages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              page_no INTEGER NOT NULL,
              mode TEXT NOT NULL,
              status TEXT NOT NULL,
              error TEXT,
              created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_cache (
              cache_key TEXT PRIMARY KEY,
              source_lang TEXT NOT NULL,
              target_lang TEXT NOT NULL,
              translated_text TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )

        conn.commit()


def ensure_user(telegram_user_id: int) -> None:
    ts = _now()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_user_id, created_at, last_seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at
            """,
            (telegram_user_id, ts, ts),
        )
        conn.commit()


def get_user(telegram_user_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_user_id=?", (telegram_user_id,)).fetchone()
    return dict(row) if row else None


def add_ledger(
    telegram_user_id: int,
    entry_type: str,
    pages: int,
    job_id: str | None = None,
    external_ref: str | None = None,
    note: str | None = None,
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO credit_ledger (telegram_user_id, type, pages, job_id, external_ref, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_user_id, entry_type, pages, job_id, external_ref, note, _now()),
        )
        conn.commit()


def list_ledger(telegram_user_id: int, limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_ledger WHERE telegram_user_id=? ORDER BY id DESC LIMIT ?",
            (telegram_user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def grant_credits(telegram_user_id: int, pages: int, note: str, external_ref: str | None = None) -> None:
    if pages <= 0:
        raise ValueError("pages must be > 0")
    ensure_user(telegram_user_id)
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET available_credits = available_credits + ?, last_seen_at=? WHERE telegram_user_id=?",
            (pages, _now(), telegram_user_id),
        )
        conn.execute(
            """
            INSERT INTO credit_ledger (telegram_user_id, type, pages, external_ref, note, created_at)
            VALUES (?, 'grant', ?, ?, ?, ?)
            """,
            (telegram_user_id, pages, external_ref, note, _now()),
        )
        conn.commit()


def reserve_credits(telegram_user_id: int, pages: int, job_id: str) -> bool:
    if pages <= 0:
        return True
    ensure_user(telegram_user_id)
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute("SELECT telegram_user_id,pages FROM credit_ledger WHERE job_id=? AND type='reserve'", (job_id,)).fetchone()
        if prior:
            if prior['telegram_user_id'] != telegram_user_id or prior['pages'] != pages:
                raise ValueError("Reservation identity or amount mismatch")
            return True
        user = conn.execute(
            "SELECT available_credits, reserved_credits FROM users WHERE telegram_user_id=?",
            (telegram_user_id,),
        ).fetchone()
        if not user or user["available_credits"] < pages:
            return False

        conn.execute(
            """
            UPDATE users
            SET available_credits = available_credits - ?, reserved_credits = reserved_credits + ?, last_seen_at=?
            WHERE telegram_user_id=?
            """,
            (pages, pages, _now(), telegram_user_id),
        )
        conn.execute(
            """
            INSERT INTO credit_ledger (telegram_user_id, type, pages, job_id, note, created_at)
            VALUES (?, 'reserve', ?, ?, 'job reserve', ?)
            """,
            (telegram_user_id, pages, job_id, _now()),
        )
        conn.commit()
    return True


def _settle_reserved(telegram_user_id: int, pages: int, job_id: str, kind: str, note: str, *, final_status: str | None = None, output_path: str | None = None, failure_code: str | None = None) -> None:
    if pages < 0:
        raise ValueError("Settlement amount cannot be negative")
    if pages == 0 and not final_status:
        return
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if final_status:
            job = conn.execute("SELECT owner_telegram_user_id,status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not job or job['owner_telegram_user_id'] != telegram_user_id:
                raise ValueError("Job owner mismatch")
            if job['status'] != 'running':
                if job['status'] == final_status:
                    return
                raise ValueError("Only running jobs may be finalized")
        reservation = conn.execute("SELECT telegram_user_id,pages FROM credit_ledger WHERE job_id=? AND type='reserve'", (job_id,)).fetchone()
        if pages > 0 and (not reservation or reservation['telegram_user_id'] != telegram_user_id or reservation['pages'] != pages):
            raise ValueError("Settlement must match a durable reservation")
        previous = conn.execute("SELECT type FROM credit_ledger WHERE job_id=? AND type IN ('capture','release')", (job_id,)).fetchone()
        if previous:
            if previous['type'] != kind:
                raise ValueError("Reservation already settled differently")
            return
        refund = pages if kind == 'release' else 0
        changed = conn.execute("UPDATE users SET reserved_credits=reserved_credits-?, available_credits=available_credits+?, last_seen_at=? WHERE telegram_user_id=? AND reserved_credits>=?", (pages, refund, _now(), telegram_user_id, pages)).rowcount
        if pages > 0 and changed != 1:
            raise ValueError("Reserved balance invariant violated")
        conn.execute("INSERT INTO credit_ledger (telegram_user_id,type,pages,job_id,note,created_at) VALUES (?,?,?,?,?,?)", (telegram_user_id, kind, pages, job_id, note, _now()))
        if final_status:
            conn.execute("UPDATE jobs SET status=?,output_path=?,error=?,failure_reason_code=?,credits_charged=?,pages_processed=CASE WHEN ?='completed' THEN ? ELSE pages_processed END,updated_at=? WHERE job_id=?", (final_status, output_path, note if kind == 'release' else None, failure_code, pages if kind == 'capture' else 0, final_status, pages, _now(), job_id))



def finish_job(job_id: str, *, output_path: str | None = None, error: str | None = None, failure_code: str | None = None) -> None:
    job = get_job(job_id)
    if not job:
        raise ValueError("Unknown job")
    success = error is None
    _settle_reserved(job['owner_telegram_user_id'], job['credits_reserved'], job_id,
                     'capture' if success else 'release', error or 'job completed',
                     final_status='completed' if success else 'failed', output_path=output_path,
                     failure_code=failure_code)


def capture_reserved(telegram_user_id: int, pages: int, job_id: str) -> None:
    _settle_reserved(telegram_user_id, pages, job_id, 'capture', 'job completed')


def release_reserved(telegram_user_id: int, pages: int, job_id: str, note: str = "job failed") -> None:
    _settle_reserved(telegram_user_id, pages, job_id, 'release', note)


def create_job(
    job_id: str,
    source_lang: str,
    target_lang: str,
    owner_telegram_user_id: int,
    input_path: str,
    pages_total: int,
    credits_reserved: int,
) -> None:
    ts = _now()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              job_id, status, source_lang, target_lang, owner_telegram_user_id,
              input_path, pages_total, credits_reserved, created_at, updated_at, expires_at
            )
            VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                source_lang,
                target_lang,
                owner_telegram_user_id,
                input_path,
                pages_total,
                credits_reserved,
                ts,
                ts,
                _expires_at(),
            ),
        )
        conn.commit()


def update_job_status(
    job_id: str,
    status: str,
    output_path: str | None = None,
    error: str | None = None,
    failure_reason_code: str | None = None,
    pages_processed: int | None = None,
    credits_charged: int | None = None,
) -> None:
    ts = _now()
    fields = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, ts]

    if output_path is not None:
        fields.append("output_path = ?")
        values.append(output_path)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if failure_reason_code is not None:
        fields.append("failure_reason_code = ?")
        values.append(failure_reason_code)
    if pages_processed is not None:
        fields.append("pages_processed = ?")
        values.append(pages_processed)
    if credits_charged is not None:
        fields.append("credits_charged = ?")
        values.append(credits_charged)

    values.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?"
    with _conn() as conn:
        conn.execute(sql, tuple(values))
        conn.commit()


def claim_job(job_id: str) -> bool:
    """Only one worker may transition a queued job to running."""
    with _conn() as conn:
        changed = conn.execute(
            "UPDATE jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'",
            (_now(), job_id),
        ).rowcount
    return changed == 1


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def add_job_page(job_id: str, page_no: int, mode: str, status: str, error: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO job_pages (job_id, page_no, mode, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, page_no, mode, status, error, _now()),
        )
        conn.commit()


def list_recent_jobs(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_daily_stats() -> dict:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        success = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status='completed'").fetchone()["c"]
        failed = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status='failed'").fetchone()["c"]
        avg_pages_row = conn.execute("SELECT AVG(pages_total) avg_pages FROM jobs").fetchone()
        avg_pages = float(avg_pages_row["avg_pages"] or 0)

    success_rate = (success / total) if total else 0.0
    est_token_cost = round(avg_pages * total * 0.00022, 4)
    return {
        "job_count": total,
        "success_count": success,
        "failed_count": failed,
        "success_rate": round(success_rate, 4),
        "avg_pages": round(avg_pages, 2),
        "estimated_token_cost_usd": est_token_cost,
    }


def mark_job_cleaned(job_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE jobs SET cleaned_at=?, status='cleaned', updated_at=? WHERE job_id=?", (_now(), _now(), job_id))
        conn.commit()


def list_expired_jobs() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE cleaned_at IS NULL AND expires_at IS NOT NULL AND expires_at < ?",
            (_now(),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_cached_translation(source_lang: str, target_lang: str, text: str) -> str | None:
    key = hashlib.sha256(f"{source_lang}|{target_lang}|{text}".encode("utf-8")).hexdigest()
    with _conn() as conn:
        row = conn.execute(
            "SELECT translated_text FROM translation_cache WHERE cache_key=?",
            (key,),
        ).fetchone()
    return str(row["translated_text"]) if row else None


def set_cached_translation(source_lang: str, target_lang: str, text: str, translated_text: str) -> None:
    key = hashlib.sha256(f"{source_lang}|{target_lang}|{text}".encode("utf-8")).hexdigest()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO translation_cache (cache_key, source_lang, target_lang, translated_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO NOTHING
            """,
            (key, source_lang, target_lang, translated_text, _now()),
        )
        conn.commit()


def recover_interrupted_jobs() -> list[str]:
    """Offline maintenance only: all workers MUST be stopped by the operator."""
    with _conn() as conn:
        rows = conn.execute("SELECT job_id FROM jobs WHERE status='running' ORDER BY created_at").fetchall()
    recovered = []
    for row in rows:
        finish_job(row['job_id'], error='Worker interrupted; reservation released during offline recovery', failure_code='WORKER_INTERRUPTED')
        recovered.append(row['job_id'])
    with _conn() as conn:
        orphans = conn.execute("SELECT r.job_id,r.telegram_user_id,r.pages FROM credit_ledger r LEFT JOIN jobs j ON j.job_id=r.job_id WHERE r.type='reserve' AND j.job_id IS NULL AND NOT EXISTS (SELECT 1 FROM credit_ledger s WHERE s.job_id=r.job_id AND s.type IN ('capture','release'))").fetchall()
    for row in orphans:
        release_reserved(row['telegram_user_id'], row['pages'], row['job_id'], note='Offline orphan reservation recovery')
        recovered.append(row['job_id'])
    return recovered

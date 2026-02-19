import time
from pathlib import Path

from pdf_translator.config import settings
from pdf_translator.db import (
    add_job_page,
    capture_reserved,
    get_cached_translation,
    get_job,
    release_reserved,
    set_cached_translation,
    update_job_status,
)
from pdf_translator.openrouter import OCRParseError, OCRTimeoutError, OpenRouterError, TranslateTimeoutError
from pdf_translator.pdf_pipeline import translate_pdf


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, OCRTimeoutError):
        return "OCR_TIMEOUT"
    if isinstance(exc, OCRParseError):
        return "OCR_PARSE_ERROR"
    if isinstance(exc, TranslateTimeoutError):
        return "TRANSLATE_TIMEOUT"
    if isinstance(exc, OpenRouterError):
        return "MODEL_ERROR"
    txt = str(exc).lower()
    if "pdf" in txt:
        return "PDF_ERROR"
    return "UNKNOWN_ERROR"


def process_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    started = time.time()

    def _on_page_done(page_no: int, mode: str) -> None:
        add_job_page(job_id, page_no=page_no, mode=mode, status="completed")
        update_job_status(job_id, status="running", pages_processed=page_no)

    try:
        update_job_status(job_id, "running")
        output_path = str(Path(settings.output_dir) / f"{job_id}.translated.pdf")

        metrics = translate_pdf(
            input_path=job["input_path"],
            output_path=output_path,
            source_lang=job["source_lang"],
            target_lang=job["target_lang"],
            on_page_done=_on_page_done,
            cache_get=get_cached_translation,
            cache_set=set_cached_translation,
        )

        elapsed = time.time() - started
        if elapsed > settings.job_timeout_sec:
            raise TimeoutError(f"job_timeout_{elapsed:.1f}s")

        charged = int(metrics["pages_total"])
        capture_reserved(job["owner_telegram_user_id"], charged, job_id)
        update_job_status(
            job_id,
            "completed",
            output_path=output_path,
            pages_processed=charged,
            credits_charged=charged,
        )
    except Exception as exc:
        code = _failure_code(exc)
        reserved = int(job.get("credits_reserved", 0))
        release_reserved(job["owner_telegram_user_id"], reserved, job_id, note=f"{code}: {exc}")
        update_job_status(job_id, "failed", error=str(exc), failure_reason_code=code)

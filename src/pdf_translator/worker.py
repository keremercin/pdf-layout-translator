import time
from pathlib import Path

from pdf_translator.config import settings
from pdf_translator.db import (
    add_job_page,
    claim_job,
    finish_job,
    get_cached_translation,
    get_job,
    set_cached_translation,
    update_job_status,
)
from pdf_translator.openrouter import (
    OCRParseError,
    OCRTimeoutError,
    OpenRouterError,
    TranslateTimeoutError,
)
from pdf_translator.pdf_pipeline import translate_pdf


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, OCRTimeoutError):
        return "OCR_TIMEOUT"
    if isinstance(exc, OCRParseError):
        return "OCR_PARSE_ERROR"
    if isinstance(exc, TranslateTimeoutError):
        return "TRANSLATE_TIMEOUT"
    if isinstance(exc, TimeoutError):
        return "JOB_TIMEOUT"
    if isinstance(exc, OpenRouterError):
        return "MODEL_ERROR"
    txt = str(exc).lower()
    if "pdf" in txt:
        return "PDF_ERROR"
    return "UNKNOWN_ERROR"


def process_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job or job["status"] in {"completed", "failed"}:
        return
    if not claim_job(job_id):
        return

    started = time.monotonic()

    def _check_deadline() -> None:
        elapsed = time.monotonic() - started
        if elapsed > settings.job_timeout_sec:
            raise TimeoutError(f"job_timeout_{elapsed:.1f}s")

    def _on_page_done(page_no: int, mode: str) -> None:
        _check_deadline()
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

        _check_deadline()

        charged = int(metrics["pages_total"])
        if charged != int(job['credits_reserved']):
            raise ValueError("Processed pages do not match reserved credits")
        finish_job(job_id, output_path=output_path)
    except Exception as exc:  # noqa: BLE001 - job boundary must refund on any processing failure
        code = _failure_code(exc)
        finish_job(job_id, error=str(exc), failure_code=code)

from pathlib import Path

from pdf_translator.config import settings
from pdf_translator.db import get_job, update_job_status
from pdf_translator.pdf_pipeline import translate_pdf


def process_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    try:
        update_job_status(job_id, "running")
        output_path = str(Path(settings.output_dir) / f"{job_id}.translated.pdf")
        translate_pdf(
            input_path=job["input_path"],
            output_path=output_path,
            source_lang=job["source_lang"],
            target_lang=job["target_lang"],
        )
        update_job_status(job_id, "completed", output_path=output_path)
    except Exception as exc:
        update_job_status(job_id, "failed", error=str(exc))

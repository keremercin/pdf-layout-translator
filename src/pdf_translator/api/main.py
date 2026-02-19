from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from pdf_translator.config import settings
from pdf_translator.db import create_job, get_job, init_db
from pdf_translator.schemas import JobResponse
from pdf_translator.worker import process_job

app = FastAPI(title="PDF Layout Translator", version=settings.app_version)
init_db()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.output_dir).mkdir(parents=True, exist_ok=True)


def envelope(data: dict, status: str = "ok", error: dict | None = None) -> dict:
    return {
        "status": status,
        "data": data,
        "meta": {"model_version": settings.app_version, "latency_ms": 0},
        "error": error,
    }


@app.get("/health")
def health() -> dict:
    return envelope({"service": "pdf-layout-translator"})


@app.get("/version")
def version() -> dict:
    return envelope({"service": "pdf-layout-translator", "version": settings.app_version})


@app.post("/v1/jobs")
async def create_translation_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...),
) -> dict:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    data = await file.read()
    if len(data) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    job_id = str(uuid4())
    input_path = str(Path(settings.upload_dir) / f"{job_id}.pdf")
    Path(input_path).write_bytes(data)

    create_job(job_id=job_id, source_lang=source_lang, target_lang=target_lang, input_path=input_path)
    background_tasks.add_task(process_job, job_id)

    job = get_job(job_id)
    return envelope(JobResponse(**job).model_dump())


@app.get("/v1/jobs/{job_id}")
def get_translation_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return envelope(JobResponse(**job).model_dump())


@app.get("/v1/jobs/{job_id}/download")
def download_translation(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed" or not job["output_path"]:
        raise HTTPException(status_code=409, detail="Job is not completed")
    path = Path(job["output_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Translated file not found")
    return FileResponse(path=str(path), filename=f"{job_id}.translated.pdf", media_type="application/pdf")

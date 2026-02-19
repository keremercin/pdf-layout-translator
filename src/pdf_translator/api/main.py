from pathlib import Path
from typing import Annotated
from uuid import uuid4

import fitz
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from pdf_translator.config import settings
from pdf_translator.db import (
    create_job,
    get_daily_stats,
    get_job,
    get_user,
    grant_credits,
    init_db,
    list_ledger,
    reserve_credits,
)
from pdf_translator.schemas import AdminGrantRequest, CreditBalanceResponse, JobResponse
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


def _require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if not settings.admin_api_token:
        raise HTTPException(status_code=500, detail="ADMIN_API_TOKEN is not configured")
    if x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _validate_lang_pair(source_lang: str, target_lang: str) -> None:
    src = source_lang.lower()
    tgt = target_lang.lower()
    if src not in {"tr", "en"} or tgt not in {"tr", "en"} or src == tgt:
        raise HTTPException(status_code=400, detail="Only TR<->EN language pairs are supported")


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
    telegram_user_id: int = Form(...),
) -> dict:
    _validate_lang_pair(source_lang, target_lang)

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    data = await file.read()
    if len(data) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        pages_total = len(doc)
        doc.close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PDF: {exc}") from exc

    if pages_total > settings.max_pages_per_job:
        raise HTTPException(status_code=400, detail=f"Max page limit is {settings.max_pages_per_job}")

    job_id = str(uuid4())
    if not reserve_credits(telegram_user_id, pages_total, job_id):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    input_path = str(Path(settings.upload_dir) / f"{job_id}.pdf")
    Path(input_path).write_bytes(data)

    create_job(
        job_id=job_id,
        source_lang=source_lang.lower(),
        target_lang=target_lang.lower(),
        owner_telegram_user_id=telegram_user_id,
        input_path=input_path,
        pages_total=pages_total,
        credits_reserved=pages_total,
    )
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
def download_translation(job_id: str, telegram_user_id: int = Query(...)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if int(job["owner_telegram_user_id"]) != telegram_user_id:
        raise HTTPException(status_code=403, detail="You do not own this job")
    if job["status"] != "completed" or not job["output_path"]:
        raise HTTPException(status_code=409, detail="Job is not completed")

    path = Path(job["output_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Translated file not found")

    return FileResponse(path=str(path), filename=f"{job_id}.translated.pdf", media_type="application/pdf")


@app.get("/v1/credits/{telegram_user_id}")
def get_credits(telegram_user_id: int) -> dict:
    user = get_user(telegram_user_id)
    if not user:
        user = {
            "telegram_user_id": telegram_user_id,
            "available_credits": 0,
            "reserved_credits": 0,
        }

    balance = CreditBalanceResponse(
        telegram_user_id=telegram_user_id,
        available_credits=int(user["available_credits"]),
        reserved_credits=int(user["reserved_credits"]),
    ).model_dump()
    return envelope({"balance": balance, "recent_ledger": list_ledger(telegram_user_id, limit=20)})


@app.post("/v1/admin/credits/grant")
def admin_grant_credits(payload: AdminGrantRequest, x_admin_token: Annotated[str | None, Header()] = None) -> dict:
    _require_admin(x_admin_token=x_admin_token)
    grant_credits(
        telegram_user_id=payload.telegram_user_id,
        pages=payload.pages,
        note=payload.note,
        external_ref=payload.external_ref,
    )
    user = get_user(payload.telegram_user_id)
    return envelope(
        {
            "telegram_user_id": payload.telegram_user_id,
            "available_credits": int(user["available_credits"] if user else 0),
            "reserved_credits": int(user["reserved_credits"] if user else 0),
        }
    )


@app.get("/v1/admin/jobs/stats")
def admin_job_stats(x_admin_token: Annotated[str | None, Header()] = None) -> dict:
    _require_admin(x_admin_token=x_admin_token)
    return envelope(get_daily_stats())

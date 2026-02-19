from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    status: str
    source_lang: str
    target_lang: str
    created_at: str
    updated_at: str
    error: str | None = None
    output_path: str | None = None


class Envelope(BaseModel):
    status: str = "ok"
    data: dict
    meta: dict
    error: dict | None = None

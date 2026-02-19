from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    status: str
    source_lang: str
    target_lang: str
    owner_telegram_user_id: int
    input_path: str
    output_path: str | None = None
    error: str | None = None
    pages_total: int = 0
    pages_processed: int = 0
    credits_reserved: int = 0
    credits_charged: int = 0
    failure_reason_code: str | None = None
    created_at: str
    updated_at: str
    expires_at: str
    cleaned_at: str | None = None


class CreditBalanceResponse(BaseModel):
    telegram_user_id: int
    available_credits: int
    reserved_credits: int


class AdminGrantRequest(BaseModel):
    telegram_user_id: int
    pages: int
    note: str = "manual grant"
    external_ref: str | None = None

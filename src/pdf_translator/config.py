from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_version: str = "0.2.0"
    database_path: str = "data/jobs.db"
    upload_dir: str = "uploads"
    output_dir: str = "outputs"

    model_provider: str = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_translate_model: str = "gpt-4.1-mini"
    openai_ocr_model: str = "gpt-4.1-mini"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_translate_model: str = "google/gemini-2.5-flash-lite"
    openrouter_ocr_model: str = "google/gemini-2.5-flash-lite"
    openrouter_fallback_model: str = "google/gemini-2.5-flash"

    max_file_mb: int = 80
    max_pages_per_job: int = 150
    allowed_langs: str = "tr,en"

    ocr_timeout_sec: int = 45
    translate_timeout_sec: int = 25
    job_timeout_sec: int = 1800

    block_chunk_chars: int = 1400
    retention_hours: int = 24

    admin_api_token: str = ""
    api_base_url: str = "http://localhost:8900"
    telegram_bot_token: str = ""


settings = Settings()

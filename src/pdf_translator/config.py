from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_version: str = "0.1.0"
    database_path: str = "data/jobs.db"
    upload_dir: str = "uploads"
    output_dir: str = "outputs"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_translate_model: str = "google/gemini-2.5-flash-lite"
    openrouter_ocr_model: str = "google/gemini-2.5-flash-lite"
    openrouter_fallback_model: str = "google/gemini-2.5-flash"

    max_file_mb: int = 80
    api_base_url: str = "http://localhost:8900"
    telegram_bot_token: str = ""


settings = Settings()

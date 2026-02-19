import pytest

from pdf_translator import config
from pdf_translator.db import init_db


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "outputs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config.settings, "database_path", str(db_path))
    monkeypatch.setattr(config.settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(config.settings, "output_dir", str(output_dir))
    monkeypatch.setattr(config.settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(config.settings, "max_pages_per_job", 150)

    init_db()
    yield

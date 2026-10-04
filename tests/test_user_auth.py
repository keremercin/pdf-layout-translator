import time

from fastapi.testclient import TestClient

from pdf_translator.api.main import app
from pdf_translator.auth import issue_user_token
from pdf_translator.config import settings


def test_auth_fails_closed_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "user_auth_secret", "")
    assert TestClient(app).get('/v1/credits/999').status_code == 503


def test_identity_cannot_be_claimed_or_tampered(monkeypatch):
    monkeypatch.setattr(settings, 'user_auth_secret', 'test-secret-' * 4)
    client = TestClient(app)
    assert client.get('/v1/credits/999').status_code == 401
    token = issue_user_token(999)
    headers = {'x-user-token': token}
    assert client.get('/v1/credits/999', headers=headers).status_code == 200
    assert client.get('/v1/credits/888', headers=headers).status_code == 403
    assert client.get('/v1/credits/888', headers={'x-user-token': token.replace('999:', '888:', 1)}).status_code == 401
    expired = issue_user_token(999, now=int(time.time()) - 4000)
    assert client.get('/v1/credits/999', headers={'x-user-token': expired}).status_code == 401


def test_foreign_job_metadata_and_file_are_protected(monkeypatch):
    from pdf_translator.db import create_job
    monkeypatch.setattr(settings, 'user_auth_secret', 'test-secret-' * 4)
    create_job(job_id='private-job', source_lang='tr', target_lang='en', owner_telegram_user_id=999, input_path='unused.pdf', pages_total=1, credits_reserved=0)
    client = TestClient(app)
    stranger = {'x-user-token': issue_user_token(888)}
    owner = {'x-user-token': issue_user_token(999)}
    assert client.get('/v1/jobs/private-job', headers=stranger).status_code == 404
    assert client.get('/v1/jobs/private-job', headers=owner).status_code == 200
    assert client.get('/v1/jobs/private-job/download?telegram_user_id=999', headers=stranger).status_code == 403
    assert client.get('/v1/jobs/private-job/download?telegram_user_id=888', headers=stranger).status_code == 403
    assert client.get('/v1/jobs/private-job/download?telegram_user_id=999', headers=owner).status_code == 409

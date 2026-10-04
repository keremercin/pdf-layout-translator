import fitz
from fastapi.testclient import TestClient

from pdf_translator.api.main import app
from pdf_translator.auth import issue_user_token


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Merhaba dunya")
    out = doc.tobytes()
    doc.close()
    return out


def test_job_create_and_status_with_reserved_credits() -> None:
    c = TestClient(app, headers={"x-user-token": issue_user_token(999)})

    # grant credits first
    g = c.post(
        '/v1/admin/credits/grant',
        json={"telegram_user_id": 999, "pages": 20, "note": "seed"},
        headers={"x-admin-token": "test-admin-token"},
    )
    assert g.status_code == 200

    r = c.post(
        '/v1/jobs',
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
        data={"source_lang": "tr", "target_lang": "en", "telegram_user_id": "999"},
    )
    assert r.status_code == 200

    data = r.json()["data"]
    assert data["owner_telegram_user_id"] == 999
    assert data["credits_reserved"] == 1

    rs = c.get(f"/v1/jobs/{data['job_id']}")
    assert rs.status_code == 200


def test_job_creation_failure_returns_reserved_credits(monkeypatch):
    from pdf_translator.api import main
    from pdf_translator.db import get_user, grant_credits, list_ledger
    grant_credits(999, 5, 'seed')
    def fail(**kwargs):
        raise OSError('injected database persistence failure')
    monkeypatch.setattr(main, 'create_job', fail)
    client = TestClient(app, headers={'x-user-token': issue_user_token(999)})
    response = client.post('/v1/jobs', files={'file': ('sample.pdf', _pdf_bytes(), 'application/pdf')}, data={'source_lang': 'tr', 'target_lang': 'en', 'telegram_user_id': '999'})
    assert response.status_code == 500
    assert get_user(999)['available_credits'] == 5
    assert get_user(999)['reserved_credits'] == 0
    assert [r['type'] for r in list_ledger(999)] == ['release', 'reserve', 'grant']

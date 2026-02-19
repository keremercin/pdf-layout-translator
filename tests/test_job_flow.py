import fitz
from fastapi.testclient import TestClient

from pdf_translator.api.main import app


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Merhaba dunya")
    out = doc.tobytes()
    doc.close()
    return out


def test_job_create_and_status_with_reserved_credits() -> None:
    c = TestClient(app)

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

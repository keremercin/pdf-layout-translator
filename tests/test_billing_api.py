from fastapi.testclient import TestClient

from pdf_translator.api.main import app


def test_admin_grant_and_balance() -> None:
    c = TestClient(app)

    payload = {
        "telegram_user_id": 12345,
        "pages": 100,
        "note": "manual stars",
        "external_ref": "STARS-12345-1",
    }
    r = c.post('/v1/admin/credits/grant', json=payload, headers={"x-admin-token": "test-admin-token"})
    assert r.status_code == 200

    rb = c.get('/v1/credits/12345')
    assert rb.status_code == 200
    bal = rb.json()['data']['balance']
    assert bal['available_credits'] == 100
    assert bal['reserved_credits'] == 0


def test_admin_auth_required() -> None:
    c = TestClient(app)
    r = c.post('/v1/admin/credits/grant', json={"telegram_user_id": 1, "pages": 10, "note": "x"})
    assert r.status_code == 401

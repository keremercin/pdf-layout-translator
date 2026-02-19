from fastapi.testclient import TestClient

from pdf_translator.api.main import app


def test_health() -> None:
    c = TestClient(app)
    r = c.get('/health')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert body['data']['service'] == 'pdf-layout-translator'

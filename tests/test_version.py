from fastapi.testclient import TestClient

from pdf_translator.api.main import app


def test_version() -> None:
    c = TestClient(app)
    r = c.get('/version')
    assert r.status_code == 200
    assert 'version' in r.json()['data']

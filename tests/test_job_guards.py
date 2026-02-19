import fitz
from fastapi.testclient import TestClient

from pdf_translator.api.main import app


def _pdf_bytes(page_count: int) -> bytes:
    doc = fitz.open()
    for i in range(page_count):
        p = doc.new_page()
        p.insert_text((72, 72), f"Page {i+1} sample text")
    out = doc.tobytes()
    doc.close()
    return out


def test_lang_pair_validation() -> None:
    c = TestClient(app)
    payload = _pdf_bytes(1)
    r = c.post(
        '/v1/jobs',
        files={"file": ("sample.pdf", payload, "application/pdf")},
        data={"source_lang": "tr", "target_lang": "de", "telegram_user_id": "1"},
    )
    assert r.status_code == 400


def test_page_limit_validation() -> None:
    c = TestClient(app)
    payload = _pdf_bytes(151)
    r = c.post(
        '/v1/jobs',
        files={"file": ("sample.pdf", payload, "application/pdf")},
        data={"source_lang": "tr", "target_lang": "en", "telegram_user_id": "1"},
    )
    assert r.status_code == 400


def test_insufficient_credits() -> None:
    c = TestClient(app)
    payload = _pdf_bytes(2)
    r = c.post(
        '/v1/jobs',
        files={"file": ("sample.pdf", payload, "application/pdf")},
        data={"source_lang": "tr", "target_lang": "en", "telegram_user_id": "1"},
    )
    assert r.status_code == 402

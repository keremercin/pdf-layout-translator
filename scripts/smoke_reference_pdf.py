import os
import time
from tempfile import TemporaryDirectory
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from pdf_translator.api.main import app
from pdf_translator.config import settings
from pdf_translator.db import grant_credits

REFERENCE_PDF = Path("data/fixtures/reference_english.pdf")


def _pdf_stats(path: Path) -> tuple[int, int]:
    doc = fitz.open(path)
    try:
        pages = len(doc)
        text_len = sum(len((p.get_text("text") or "").strip()) for p in doc)
        return pages, text_len
    finally:
        doc.close()


def main() -> int:
    if not REFERENCE_PDF.exists():
        print(f"[FAIL] missing reference pdf: {REFERENCE_PDF}")
        print(
            "[HINT] download with: curl -L https://arxiv.org/pdf/1706.03762.pdf -o data/fixtures/reference_english.pdf"
        )
        return 2

    if settings.model_provider.lower() == "openai" and not settings.openai_api_key:
        print("[FAIL] OPENAI_API_KEY is empty (.env.local).")
        return 2

    requested_pages = int(os.getenv("SMOKE_REFERENCE_PAGES", "5"))
    deadline_sec = int(os.getenv("SMOKE_REFERENCE_TIMEOUT_SEC", "420"))

    source_pdf = REFERENCE_PDF
    tmp_dir = None
    if requested_pages > 0:
        total_pages, _ = _pdf_stats(REFERENCE_PDF)
        use_pages = min(requested_pages, total_pages)
        if use_pages < total_pages:
            tmp_dir = TemporaryDirectory()
            subset_pdf = Path(tmp_dir.name) / "reference_subset.pdf"
            src_doc = fitz.open(REFERENCE_PDF)
            out_doc = fitz.open()
            out_doc.insert_pdf(src_doc, from_page=0, to_page=use_pages - 1)
            out_doc.save(subset_pdf)
            out_doc.close()
            src_doc.close()
            source_pdf = subset_pdf

    in_pages, in_text_len = _pdf_stats(source_pdf)
    print(f"[INFO] reference input: pages={in_pages}, text_len={in_text_len}, file={source_pdf}", flush=True)

    user_id = int(os.getenv("SMOKE_TELEGRAM_USER_ID", "900001"))
    grant_credits(user_id, pages=max(in_pages + 10, 40), note="reference smoke credits", external_ref="ref-smoke")

    client = TestClient(app)
    with source_pdf.open("rb") as fh:
        create = client.post(
            "/v1/jobs",
            files={"file": (source_pdf.name, fh.read(), "application/pdf")},
            data={"source_lang": "en", "target_lang": "tr", "telegram_user_id": str(user_id)},
        )
    if create.status_code != 200:
        print(f"[FAIL] job create failed: {create.status_code} {create.text}")
        return 1

    job = create.json()["data"]
    job_id = job["job_id"]
    print(f"[INFO] job created: {job_id} pages={job['pages_total']} reserved={job['credits_reserved']}", flush=True)

    deadline = time.time() + deadline_sec
    data = None
    while time.time() < deadline:
        rs = client.get(f"/v1/jobs/{job_id}")
        if rs.status_code != 200:
            print(f"[FAIL] status query failed: {rs.status_code} {rs.text}")
            return 1
        data = rs.json()["data"]
        if data["status"] in {"completed", "failed"}:
            break
        time.sleep(2)

    if not data:
        print("[FAIL] no status data")
        return 1
    if data["status"] == "failed":
        print(f"[FAIL] job failed: code={data.get('failure_reason_code')} error={data.get('error')}")
        return 1
    if data["status"] != "completed":
        print("[FAIL] timeout waiting for completion")
        return 1

    dl = client.get(f"/v1/jobs/{job_id}/download", params={"telegram_user_id": user_id})
    if dl.status_code != 200:
        print(f"[FAIL] download failed: {dl.status_code} {dl.text}")
        return 1

    out_path = Path(settings.output_dir) / "reference_english_en_tr.translated.pdf"
    out_path.write_bytes(dl.content)
    out_pages, out_text_len = _pdf_stats(out_path)

    print(
        f"[INFO] output: pages={out_pages}, text_len={out_text_len}, charged={data['credits_charged']}, output={out_path}",
        flush=True,
    )

    if out_pages != in_pages:
        print(f"[FAIL] page mismatch: in={in_pages}, out={out_pages}")
        return 1
    if out_text_len < int(in_text_len * 0.35):
        print(f"[FAIL] translated text too low: in={in_text_len}, out={out_text_len}")
        return 1

    print("[DONE] reference PDF smoke passed.")
    if tmp_dir:
        tmp_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

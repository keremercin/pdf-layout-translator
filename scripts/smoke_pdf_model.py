import os
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from pdf_translator.api.main import app
from pdf_translator.config import settings
from pdf_translator.db import grant_credits


def _make_text_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "Merhaba. Bu belge bir smoke test dosyasidir.\n"
        "Amac: PDF ceviri akisinda layout bozulmadan temel kaliteyi kontrol etmek.\n"
        "Madde 1: Fiyat 1200 TL.\n"
        "Madde 2: Tarih 19 Subat 2026.\n"
    )
    rect = fitz.Rect(48, 60, 540, 760)
    page.insert_textbox(rect, text, fontsize=12)
    doc.save(path)
    doc.close()


def _make_scanned_like_pdf(path: Path) -> None:
    source = fitz.open()
    src_page = source.new_page()
    rect = fitz.Rect(48, 60, 540, 760)
    src_page.insert_textbox(
        rect,
        (
            "This page simulates a scanned PDF.\n"
            "The text should be extracted with OCR and translated.\n"
            "Order ID: A-5519\n"
            "Amount: 2480 USD\n"
        ),
        fontsize=12,
    )
    pix = src_page.get_pixmap(dpi=180)
    png = pix.tobytes("png")
    source.close()

    out = fitz.open()
    p = out.new_page()
    p.insert_image(p.rect, stream=png)
    out.save(path)
    out.close()


def _make_long_mixed_pdf(path: Path, pages: int = 12) -> None:
    pages = max(4, pages)
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        if i % 2 == 1:
            page.insert_textbox(
                fitz.Rect(40, 50, 555, 780),
                (
                    f"Chapter {i}\n"
                    "This is a long smoke scenario for layout preservation.\n"
                    "The page includes paragraph text, pseudo-table rows, and numbers.\n\n"
                    "Row | Product | Qty | Price\n"
                    f"{i:02d}  | Item-A  | {i+1}   | {100+i*7} USD\n"
                    f"{i+1:02d}  | Item-B  | {i+2}   | {120+i*5} USD\n"
                    f"{i+2:02d}  | Item-C  | {i+3}   | {90+i*6} USD\n\n"
                    "Footer note: Layout must stay stable after translation."
                ),
                fontsize=11,
            )
            page.draw_rect(fitz.Rect(40, 170, 555, 270), color=(0, 0, 0), width=0.8)
            page.draw_line(fitz.Point(40, 200), fitz.Point(555, 200), color=(0, 0, 0), width=0.5)
            page.draw_line(fitz.Point(40, 230), fitz.Point(555, 230), color=(0, 0, 0), width=0.5)
        else:
            tmp = fitz.open()
            src = tmp.new_page()
            src.insert_textbox(
                fitz.Rect(48, 60, 540, 760),
                (
                    f"Scanned-like page {i}\n"
                    "The engine should replace source text cleanly.\n"
                    "Reference: INV-2026-8891\n"
                    f"Line count hint: {i * 3}\n"
                    "All old glyphs must be hidden before inserting translated text."
                ),
                fontsize=12,
            )
            pix = src.get_pixmap(dpi=180)
            tmp.close()
            page.insert_image(page.rect, stream=pix.tobytes("png"))

    doc.save(path)
    doc.close()


def _read_pdf_text_len(path: Path) -> int:
    doc = fitz.open(path)
    try:
        return sum(len((p.get_text("text") or "").strip()) for p in doc)
    finally:
        doc.close()


def _run_job(
    client: TestClient,
    user_id: int,
    pdf_path: Path,
    source_lang: str,
    target_lang: str,
    min_text_len: int = 1,
) -> bool:
    with pdf_path.open("rb") as fh:
        response = client.post(
            "/v1/jobs",
            files={"file": (pdf_path.name, fh.read(), "application/pdf")},
            data={
                "source_lang": source_lang,
                "target_lang": target_lang,
                "telegram_user_id": str(user_id),
            },
        )
    if response.status_code != 200:
        print(f"[FAIL] create job for {pdf_path.name}: {response.status_code} {response.text}")
        return False

    job = response.json()["data"]
    job_id = job["job_id"]
    print(f"[INFO] job created: {job_id} pages={job['pages_total']} reserved={job['credits_reserved']}")

    deadline = time.time() + 180
    while time.time() < deadline:
        rs = client.get(f"/v1/jobs/{job_id}")
        if rs.status_code != 200:
            print(f"[FAIL] status query failed for {job_id}: {rs.status_code} {rs.text}")
            return False
        data = rs.json()["data"]
        if data["status"] in {"completed", "failed"}:
            break
        time.sleep(1.0)
    else:
        print(f"[FAIL] timeout waiting job {job_id}")
        return False

    if data["status"] == "failed":
        print(
            f"[FAIL] job {job_id} failed: code={data.get('failure_reason_code')} error={data.get('error')}"
        )
        return False

    dl = client.get(f"/v1/jobs/{job_id}/download", params={"telegram_user_id": user_id})
    if dl.status_code != 200:
        print(f"[FAIL] download failed for {job_id}: {dl.status_code} {dl.text}")
        return False

    out_path = Path(settings.output_dir) / f"smoke_{pdf_path.stem}_{source_lang}_{target_lang}.pdf"
    out_path.write_bytes(dl.content)
    text_len = _read_pdf_text_len(out_path)
    if text_len < min_text_len:
        print(
            f"[FAIL] job={job_id} output text too low: got={text_len}, expected>={min_text_len}, output={out_path}"
        )
        return False
    print(
        f"[OK] job={job_id} charged={data['credits_charged']} processed={data['pages_processed']}/{data['pages_total']} output={out_path} text_len={text_len}"
    )
    return True


def main() -> int:
    if settings.model_provider.lower() != "openai":
        print(f"[WARN] MODEL_PROVIDER={settings.model_provider}, expected 'openai' for this smoke.")
    if not settings.openai_api_key and settings.model_provider.lower() == "openai":
        print("[FAIL] OPENAI_API_KEY is empty. Put it into .env.local and retry.")
        return 2

    smoke_dir = Path("data/smoke")
    smoke_dir.mkdir(parents=True, exist_ok=True)
    text_pdf = smoke_dir / "sample_text.pdf"
    scanned_pdf = smoke_dir / "sample_scanned.pdf"
    long_pdf = smoke_dir / "sample_long_mixed.pdf"
    _make_text_pdf(text_pdf)
    _make_scanned_like_pdf(scanned_pdf)
    _make_long_mixed_pdf(long_pdf, pages=int(os.getenv("SMOKE_LONG_PAGES", "12")))

    user_id = int(os.getenv("SMOKE_TELEGRAM_USER_ID", "900001"))
    grant_credits(user_id, pages=300, note="smoke test credits", external_ref="smoke-run")

    client = TestClient(app)
    ok_text = _run_job(client, user_id, text_pdf, source_lang="tr", target_lang="en", min_text_len=80)
    ok_scan = _run_job(client, user_id, scanned_pdf, source_lang="en", target_lang="tr", min_text_len=60)
    ok_long = _run_job(client, user_id, long_pdf, source_lang="en", target_lang="tr", min_text_len=1200)

    if ok_text and ok_scan and ok_long:
        print("[DONE] smoke test passed for text-layer, scanned-like, and long mixed PDFs.")
        return 0
    print("[DONE] smoke test completed with failures.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

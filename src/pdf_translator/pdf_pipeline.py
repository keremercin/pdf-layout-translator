from pathlib import Path

import fitz

from pdf_translator.openrouter import OpenRouterClient


def _has_text_layer(page: fitz.Page) -> bool:
    text = page.get_text("text").strip()
    return len(text) > 20


def _translate_blocks_text_pdf(
    page: fitz.Page,
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
) -> None:
    blocks = page.get_text("blocks")
    for block in blocks:
        x0, y0, x1, y1, text, *_ = block
        if not text or not text.strip():
            continue
        src = text.strip()
        if len(src) < 2:
            continue
        translated = client.translate_text(src, source_lang=source_lang, target_lang=target_lang)
        rect = fitz.Rect(x0, y0, x1, y1)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_textbox(rect, translated, fontsize=9, color=(0, 0, 0), align=0)


def _translate_blocks_scanned_pdf(
    page: fitz.Page,
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
) -> None:
    pix = page.get_pixmap(dpi=170)
    ocr_blocks = client.ocr_page(pix.tobytes("png"), source_lang=source_lang)
    for b in ocr_blocks:
        text = str(b.get("text", "")).strip()
        if not text:
            continue
        translated = client.translate_text(text, source_lang=source_lang, target_lang=target_lang)
        rect = fitz.Rect(float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))
        page.insert_textbox(rect, translated, fontsize=9, color=(0, 0, 0), align=0)


def translate_pdf(input_path: str, output_path: str, source_lang: str, target_lang: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    client = OpenRouterClient()

    doc = fitz.open(input_path)
    try:
        for page in doc:
            if _has_text_layer(page):
                _translate_blocks_text_pdf(page, client, source_lang, target_lang)
            else:
                _translate_blocks_scanned_pdf(page, client, source_lang, target_lang)
        doc.save(output_path)
    finally:
        doc.close()

from collections.abc import Callable
from pathlib import Path

import fitz

from pdf_translator.config import settings
from pdf_translator.openrouter import OpenRouterClient


def _has_text_layer(page: fitz.Page) -> bool:
    text = page.get_text("text").strip()
    return len(text) > 20


def _chunk_text(text: str, chunk_size: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", cursor, end)
            if boundary > cursor + 150:
                end = boundary
        part = text[cursor:end].strip()
        if part:
            chunks.append(part)
        cursor = end
    return chunks


def _translate_text(
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
    text: str,
    cache_get: Callable[[str, str, str], str | None] | None,
    cache_set: Callable[[str, str, str, str], None] | None,
) -> str:
    cached = cache_get(source_lang, target_lang, text) if cache_get else None
    if cached:
        return cached

    translated = client.translate_text(text, source_lang=source_lang, target_lang=target_lang)
    if cache_set:
        cache_set(source_lang, target_lang, text, translated)
    return translated


def _translate_blocks_text_pdf(
    page: fitz.Page,
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
    cache_get: Callable[[str, str, str], str | None] | None,
    cache_set: Callable[[str, str, str, str], None] | None,
) -> int:
    blocks = page.get_text("blocks")
    translated_count = 0

    for block in blocks:
        x0, y0, x1, y1, text, *_ = block
        src = (text or "").strip()
        if len(src) < 2:
            continue

        translated_parts = []
        for chunk in _chunk_text(src, settings.block_chunk_chars):
            translated_parts.append(
                _translate_text(client, source_lang, target_lang, chunk, cache_get=cache_get, cache_set=cache_set)
            )

        translated = "\n".join(translated_parts).strip()
        if not translated:
            continue

        rect = fitz.Rect(x0, y0, x1, y1)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page.insert_textbox(rect, translated, fontsize=9, color=(0, 0, 0), align=0)
        translated_count += 1

    return translated_count


def _translate_blocks_scanned_pdf(
    page: fitz.Page,
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
    cache_get: Callable[[str, str, str], str | None] | None,
    cache_set: Callable[[str, str, str, str], None] | None,
) -> int:
    pix = page.get_pixmap(dpi=170)
    ocr_blocks = client.ocr_page(pix.tobytes("png"), source_lang=source_lang)
    translated_count = 0

    for b in ocr_blocks:
        src = str(b.get("text", "")).strip()
        if len(src) < 2:
            continue

        translated_parts = []
        for chunk in _chunk_text(src, settings.block_chunk_chars):
            translated_parts.append(
                _translate_text(client, source_lang, target_lang, chunk, cache_get=cache_get, cache_set=cache_set)
            )

        translated = "\n".join(translated_parts).strip()
        if not translated:
            continue

        rect = fitz.Rect(float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))
        page.insert_textbox(rect, translated, fontsize=9, color=(0, 0, 0), align=0)
        translated_count += 1

    return translated_count


def translate_pdf(
    input_path: str,
    output_path: str,
    source_lang: str,
    target_lang: str,
    on_page_done: Callable[[int, str], None] | None = None,
    cache_get: Callable[[str, str, str], str | None] | None = None,
    cache_set: Callable[[str, str, str, str], None] | None = None,
) -> dict:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    client = OpenRouterClient()

    doc = fitz.open(input_path)
    pages_total = len(doc)
    text_pages = 0
    ocr_pages = 0

    try:
        for i, page in enumerate(doc, start=1):
            if _has_text_layer(page):
                _translate_blocks_text_pdf(
                    page,
                    client,
                    source_lang,
                    target_lang,
                    cache_get=cache_get,
                    cache_set=cache_set,
                )
                text_pages += 1
                mode = "text_layer"
            else:
                _translate_blocks_scanned_pdf(
                    page,
                    client,
                    source_lang,
                    target_lang,
                    cache_get=cache_get,
                    cache_set=cache_set,
                )
                ocr_pages += 1
                mode = "ocr"

            if on_page_done:
                on_page_done(i, mode)

        doc.save(output_path)
    finally:
        doc.close()

    return {
        "pages_total": pages_total,
        "text_pages": text_pages,
        "ocr_pages": ocr_pages,
    }

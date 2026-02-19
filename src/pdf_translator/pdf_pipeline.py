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


def _color_int_to_rgb(color_int: int | None) -> tuple[float, float, float]:
    if color_int is None:
        return (0.0, 0.0, 0.0)
    r = (color_int >> 16) & 255
    g = (color_int >> 8) & 255
    b = color_int & 255
    return (r / 255.0, g / 255.0, b / 255.0)


def _paint_white(page: fitz.Page, rect: fitz.Rect) -> None:
    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)


def _fit_and_insert_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    preferred_size: float,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bool:
    size = max(6.0, min(20.0, preferred_size))
    for _ in range(8):
        rc = page.insert_textbox(rect, text, fontsize=size, color=color, align=0, overlay=True)
        if rc >= 0:
            return True
        size -= 1.0
        if size < 6.0:
            break
    return False


def _insert_fallback_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    color: tuple[float, float, float] = (0, 0, 0),
) -> None:
    x = max(2.0, rect.x0)
    y = max(8.0, rect.y0 + 8.0)
    page.insert_text(fitz.Point(x, y), text[:1200], fontsize=8, color=color, overlay=True)


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
    text_dict = page.get_text("dict")
    translated_count = 0

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            src = "".join((s.get("text") or "") for s in spans).strip()
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

            x0, y0, x1, y1 = line["bbox"]
            rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
            first_span = spans[0]
            preferred_size = float(first_span.get("size", 10.0))
            color = _color_int_to_rgb(first_span.get("color"))

            _paint_white(page, rect)
            if not _fit_and_insert_text(page, rect, translated, preferred_size=preferred_size, color=color):
                _insert_fallback_text(page, rect, translated, color=color)
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
    dpi = 170
    pix = page.get_pixmap(dpi=dpi)
    ocr_blocks = client.ocr_page(pix.tobytes("png"), source_lang=source_lang)
    translated_count = 0
    max_x = 0.0
    max_y = 0.0
    for b in ocr_blocks:
        try:
            max_x = max(max_x, float(b.get("x1", 0)))
            max_y = max(max_y, float(b.get("y1", 0)))
        except (TypeError, ValueError):
            continue

    # OCR providers may return either image-pixel coordinates or page-point coordinates.
    if max_x > page.rect.width * 1.25 or max_y > page.rect.height * 1.25:
        sx = page.rect.width / max(pix.width, 1)
        sy = page.rect.height / max(pix.height, 1)
    else:
        sx = 1.0
        sy = 1.0

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

        x0 = float(b["x0"]) * sx
        y0 = float(b["y0"]) * sy
        x1 = float(b["x1"]) * sx
        y1 = float(b["y1"]) * sy
        rect = fitz.Rect(x0, y0, x1, y1)
        if rect.width < 4 or rect.height < 4:
            continue

        # Erase source glyphs in scanned image region before placing translation.
        _paint_white(page, rect)
        preferred_size = max(7.0, min(16.0, rect.height * 0.72))
        if not _fit_and_insert_text(page, rect, translated, preferred_size=preferred_size, color=(0, 0, 0)):
            _insert_fallback_text(page, rect, translated, color=(0, 0, 0))
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

import re
from collections.abc import Callable
from pathlib import Path

import fitz

from pdf_translator.config import settings
from pdf_translator.openrouter import OpenRouterClient

_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FONT_FILES = {
    "noto_sans": _FONT_DIR / "NotoSans-Regular.ttf",
    "noto_sans_bold": _FONT_DIR / "NotoSans-Bold.ttf",
    "noto_serif": _FONT_DIR / "NotoSerif-Regular.ttf",
    "noto_serif_bold": _FONT_DIR / "NotoSerif-Bold.ttf",
}


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


def _normalize_source_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _should_translate_text(text: str) -> bool:
    if len(text) < 3:
        return False
    alpha = sum(ch.isalpha() for ch in text)
    return alpha >= 3 and (alpha / max(len(text), 1)) > 0.30


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
    fontname: str,
    align: int,
    color: tuple[float, float, float] = (0, 0, 0),
) -> bool:
    size = max(6.0, min(20.0, preferred_size))
    for _ in range(8):
        rc = page.insert_textbox(rect, text, fontsize=size, fontname=fontname, color=color, align=align, overlay=True)
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
    fontname: str,
    color: tuple[float, float, float] = (0, 0, 0),
) -> None:
    x = max(2.0, rect.x0)
    y = max(8.0, rect.y0 + 8.0)
    page.insert_text(fitz.Point(x, y), text[:1200], fontsize=8, fontname=fontname, color=color, overlay=True)


def _ensure_fonts(page: fitz.Page) -> None:
    for alias, path in _FONT_FILES.items():
        if path.exists():
            page.insert_font(fontname=alias, fontfile=str(path))


def _span_style(spans: list[dict]) -> tuple[str, bool]:
    first = spans[0] if spans else {}
    name = str(first.get("font", "")).lower()
    flags = int(first.get("flags", 0))
    bold = "bold" in name or bool(flags & (1 << 4))
    serif = "times" in name or "serif" in name or bool(flags & 1)
    if serif and bold:
        return "noto_serif_bold", True
    if serif:
        return "noto_serif", False
    if bold:
        return "noto_sans_bold", True
    return "noto_sans", False


def _line_align(page: fitz.Page, rect: fitz.Rect) -> int:
    center = page.rect.width / 2.0
    rect_center = (rect.x0 + rect.x1) / 2.0
    if abs(rect_center - center) <= page.rect.width * 0.08:
        return 1
    return 0


def _is_vertical_or_margin_line(page: fitz.Page, rect: fitz.Rect) -> bool:
    if rect.width <= 0 or rect.height <= 0:
        return True
    # Very tall and narrow shapes are usually rotated side labels (e.g. arXiv margin id)
    if rect.height > rect.width * 3.5:
        return True

    left_margin = page.rect.width * 0.08
    right_margin = page.rect.width * 0.92
    if rect.x1 < left_margin or rect.x0 > right_margin:
        if rect.height > 25:
            return True
    return False


def _translate_text(
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
    text: str,
    max_chars: int | None,
    max_lines: int | None,
    cache_get: Callable[[str, str, str], str | None] | None,
    cache_set: Callable[[str, str, str, str], None] | None,
) -> str:
    cache_text = text
    if max_chars or max_lines:
        cache_text = f"{text}||mc={max_chars or 0}||ml={max_lines or 0}"

    cached = cache_get(source_lang, target_lang, cache_text) if cache_get else None
    if cached:
        return cached

    translated = client.translate_text(
        text,
        source_lang=source_lang,
        target_lang=target_lang,
        max_chars=max_chars,
        max_lines=max_lines,
    )
    if cache_set:
        cache_set(source_lang, target_lang, cache_text, translated)
    return translated


def _translate_blocks_text_pdf(
    page: fitz.Page,
    client: OpenRouterClient,
    source_lang: str,
    target_lang: str,
    cache_get: Callable[[str, str, str], str | None] | None,
    cache_set: Callable[[str, str, str, str], None] | None,
) -> int:
    _ensure_fonts(page)
    text_dict = page.get_text("dict")
    translated_count = 0

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            x0, y0, x1, y1 = line["bbox"]
            rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
            if _is_vertical_or_margin_line(page, rect):
                continue

            src = _normalize_source_text(" ".join((s.get("text") or "").strip() for s in spans))
            if not _should_translate_text(src):
                continue

            translated_parts = []
            for chunk in _chunk_text(src, settings.block_chunk_chars):
                translated_parts.append(
                    _translate_text(
                        client,
                        source_lang,
                        target_lang,
                        chunk,
                        max_chars=max(24, int(len(chunk) * 1.12)),
                        max_lines=1,
                        cache_get=cache_get,
                        cache_set=cache_set,
                    )
                )

            translated = "\n".join(translated_parts).strip()
            if not translated:
                continue

            first_span = spans[0]
            preferred_size = float(first_span.get("size", 10.0))
            color = _color_int_to_rgb(first_span.get("color"))
            fontname, _ = _span_style(spans)
            align = _line_align(page, rect)

            _paint_white(page, rect)
            if not _fit_and_insert_text(
                page,
                rect,
                translated,
                preferred_size=preferred_size,
                fontname=fontname,
                align=align,
                color=color,
            ):
                _insert_fallback_text(page, rect, translated, fontname=fontname, color=color)
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
    _ensure_fonts(page)
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
        src = _normalize_source_text(str(b.get("text", "")))
        if not _should_translate_text(src):
            continue

        translated_parts = []
        for chunk in _chunk_text(src, settings.block_chunk_chars):
            translated_parts.append(
                _translate_text(
                    client,
                    source_lang,
                    target_lang,
                    chunk,
                    max_chars=max(24, int(len(chunk) * 1.18)),
                    max_lines=2,
                    cache_get=cache_get,
                    cache_set=cache_set,
                )
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
        if not _fit_and_insert_text(
            page,
            rect,
            translated,
            preferred_size=preferred_size,
            fontname="noto_sans",
            align=0,
            color=(0, 0, 0),
        ):
            _insert_fallback_text(page, rect, translated, fontname="noto_sans", color=(0, 0, 0))
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

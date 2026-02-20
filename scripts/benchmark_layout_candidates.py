from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class PageMetric:
    page_no: int
    src_blocks: int
    out_blocks: int
    block_count_ratio: float
    mean_center_distance_norm: float
    mean_size_error: float
    score: float


def _block_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, txt, *_ = b
        t = (txt or "").strip()
        if len(t) < 2:
            continue
        rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
        if rect.width < 2 or rect.height < 2:
            continue
        rects.append(rect)
    return rects


def _center(rect: fitz.Rect) -> tuple[float, float]:
    return ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _match_metrics(src: list[fitz.Rect], out: list[fitz.Rect], page_diag: float) -> tuple[float, float]:
    if not src or not out:
        return 1.0, 1.0
    used: set[int] = set()
    dist_acc = 0.0
    size_acc = 0.0
    n = 0
    for s in src:
        sx, sy = _center(s)
        best_i = -1
        best_d = 1e18
        for i, o in enumerate(out):
            if i in used:
                continue
            ox, oy = _center(o)
            d = math.hypot(sx - ox, sy - oy)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i < 0:
            continue
        used.add(best_i)
        o = out[best_i]
        dist_norm = min(1.0, best_d / max(page_diag, 1.0))
        sw, sh = max(s.width, 1.0), max(s.height, 1.0)
        ow, oh = max(o.width, 1.0), max(o.height, 1.0)
        size_err = (abs(sw - ow) / sw + abs(sh - oh) / sh) / 2.0
        dist_acc += dist_norm
        size_acc += min(1.0, size_err)
        n += 1
    if n == 0:
        return 1.0, 1.0
    return dist_acc / n, size_acc / n


def benchmark(source_pdf: Path, candidate_pdf: Path, pages: int = 2) -> tuple[list[PageMetric], float]:
    src_doc = fitz.open(source_pdf)
    out_doc = fitz.open(candidate_pdf)
    limit = min(pages, len(src_doc), len(out_doc))
    metrics: list[PageMetric] = []
    try:
        for i in range(limit):
            s_page = src_doc[i]
            o_page = out_doc[i]
            s_blocks = _block_rects(s_page)
            o_blocks = _block_rects(o_page)
            w = max(s_page.rect.width, o_page.rect.width)
            h = max(s_page.rect.height, o_page.rect.height)
            diag = math.hypot(w, h)
            dist, size = _match_metrics(s_blocks, o_blocks, diag)
            ratio = min(len(s_blocks), len(o_blocks)) / max(len(s_blocks), len(o_blocks), 1)
            score = max(0.0, 100.0 * (1 - (0.45 * dist + 0.35 * size + 0.20 * (1 - ratio))))
            metrics.append(
                PageMetric(
                    page_no=i + 1,
                    src_blocks=len(s_blocks),
                    out_blocks=len(o_blocks),
                    block_count_ratio=ratio,
                    mean_center_distance_norm=dist,
                    mean_size_error=size,
                    score=score,
                )
            )
    finally:
        src_doc.close()
        out_doc.close()
    avg = sum(m.score for m in metrics) / max(len(metrics), 1)
    return metrics, avg


def main() -> int:
    src = Path("data/fixtures/reference_english.pdf")
    cands = {
        "our_engine": Path("outputs/reference_english_en_tr.translated.pdf"),
        "pdf2zh_mono": Path("outputs/bench_pdf2zh/reference_english-mono.pdf"),
        "pdf2zh_babeldoc_mono": Path("outputs/bench_pdf2zh_babeldoc/reference_english.tr.mono.pdf"),
    }
    print("Layout Benchmark (first 2 pages)")
    print(f"Source: {src}")
    for name, p in cands.items():
        if not p.exists():
            print(f"- {name}: missing ({p})")
            continue
        per_page, avg = benchmark(src, p, pages=2)
        print(f"\n{name}: avg_score={avg:.2f}")
        for m in per_page:
            print(
                f"  p{m.page_no}: score={m.score:.2f} blocks={m.out_blocks}/{m.src_blocks} "
                f"ratio={m.block_count_ratio:.3f} dist={m.mean_center_distance_norm:.3f} size_err={m.mean_size_error:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
make_blank_raster_auto.py

Создаёт растровый blank.pdf из source_page.pdf путём автоматического стирания
ВСЕХ слов, найденных pdfplumber'ом — без необходимости fields.json.

ЗАЧЕМ:
  scripts/make_blank_raster.py требует предварительно размеченный fields.json.
  Для крупных форм (декларация КНД 1152017 на 4 страницах с ~100 полей)
  разметка — огромная ручная работа. Но чтобы НАЧАТЬ разметку, нужен blank.

  Этот скрипт решает курицу-и-яйцо: стирает всё что нашёл pdfplumber и даёт
  pixel-perfect пустой бланк, который:
    1) не содержит персональных данных (все слова стёрты)
    2) сохраняет статическую вёрстку формы (рамки, заголовки, клетки)
    3) готов для разметки поверх

  НО: стирает также заголовки и лейблы формы («Раздел 1.1», «Код строки»,
  подписи колонок). Это неизбежный trade-off — pdfplumber не отличает
  статическую вёрстку от данных.

КАК ИСПОЛЬЗОВАТЬ:
  1) Запустить этот скрипт для получения полностью чистого blank
  2) Вернуть статические тексты через отдельный overlay слой с текстами формы
     (можно извлечь их один раз тем же pdfplumber'ом и сохранить в
     form_static_overlay.json)

ИЛИ: делать multi-page blank путём взятия страниц разных источников:
  - Текущая страница form-template из nalog.ru для статики
  - Только стирание dynamic полей в raster

Сейчас скрипт делает ПРОСТОЕ — стирает всё. Возврат статики — в следующем PR.

Usage:
    python scripts/make_blank_raster_auto.py \\
        --source templates/knd_1152017/source_page_p1.pdf \\
        --out    templates/knd_1152017/blank_p1.pdf \\
        [--dpi 200] [--padding 2] [--min-chars 1]

Параметры:
  --dpi        разрешение растеризации (default 200)
  --padding    отступ (pt) вокруг bbox каждого слова (default 2)
  --min-chars  не стирать слова короче N символов (default 1 = стирать всё).
               Установи =3 чтобы оставить короткие числовые коды.
"""
from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader


def build_auto_blank(
    source_path: Path,
    out_path: Path,
    dpi: int = 200,
    padding: float = 2.0,
    min_chars: int = 1,
) -> dict:
    """
    Растровый blank.pdf на основе автоматически найденных bbox'ов слов.

    Args:
        source_path: исходный заполненный PDF (1 страница)
        out_path: путь для сохранения blank.pdf
        dpi: разрешение растра
        padding: отступ вокруг bbox в точках
        min_chars: минимальная длина слова для стирания
    """
    source_bytes = source_path.read_bytes()

    # 1. pdfplumber извлекает все слова с их bbox (pt-система, origin top-left)
    with pdfplumber.open(BytesIO(source_bytes)) as pdf:
        if len(pdf.pages) != 1:
            raise ValueError(
                f"{source_path}: должно быть 1 страница, не {len(pdf.pages)}"
            )
        page = pdf.pages[0]
        page_w_pt = page.width
        page_h_pt = page.height
        words = page.extract_words(keep_blank_chars=False)

    # 2. Растеризуем через pypdfium2
    pdf_doc = pdfium.PdfDocument(source_bytes)
    pdf_page = pdf_doc[0]
    scale = dpi / 72.0
    img = pdf_page.render(scale=scale).to_pil()
    img_w_px, img_h_px = img.size
    pdf_doc.close()

    # 3. Стираем белыми прямоугольниками
    draw = ImageDraw.Draw(img)
    erased = 0
    skipped_short = 0

    for w in words:
        text = w["text"]
        if len(text) < min_chars:
            skipped_short += 1
            continue

        # pdfplumber: top/bottom в pt, origin top-left
        # PIL: тоже top-left → прямая конвертация через DPI
        x0_px = int((w["x0"] - padding) * scale)
        y0_px = int((w["top"] - padding) * scale)
        x1_px = int((w["x1"] + padding) * scale)
        y1_px = int((w["bottom"] + padding) * scale)

        # Ограничение
        x0_px = max(0, x0_px)
        y0_px = max(0, y0_px)
        x1_px = min(img_w_px, x1_px)
        y1_px = min(img_h_px, y1_px)

        if x1_px <= x0_px or y1_px <= y0_px:
            continue

        draw.rectangle([x0_px, y0_px, x1_px, y1_px], fill=(255, 255, 255))
        erased += 1

    # 4. PNG → embed как image в PDF через reportlab
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img_buf = BytesIO()
    img.save(img_buf, format="PNG", optimize=True)
    img_buf.seek(0)

    c = rl_canvas.Canvas(str(out_path), pagesize=(page_w_pt, page_h_pt))
    c.drawImage(ImageReader(img_buf), 0, 0, width=page_w_pt, height=page_h_pt)
    c.save()

    return {
        "erased_words": erased,
        "skipped_short": skipped_short,
        "total_words": len(words),
        "size_kb": out_path.stat().st_size / 1024,
        "page_size_pt": (page_w_pt, page_h_pt),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--padding", type=float, default=2.0)
    parser.add_argument("--min-chars", type=int, default=1)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"❌ Не найден source: {args.source}", file=sys.stderr)
        return 1

    try:
        stats = build_auto_blank(
            args.source, args.out,
            dpi=args.dpi, padding=args.padding, min_chars=args.min_chars,
        )
    except Exception as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        return 1

    print(f"✓ {args.out}")
    print(f"   стёрто: {stats['erased_words']}/{stats['total_words']} слов")
    if stats["skipped_short"]:
        print(f"   пропущено коротких: {stats['skipped_short']}")
    print(f"   размер: {stats['size_kb']:.1f} KB, страница: {stats['page_size_pt']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

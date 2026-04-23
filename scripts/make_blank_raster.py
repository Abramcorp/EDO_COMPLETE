#!/usr/bin/env python3
"""
make_blank_raster.py

Создаёт растровый blank.pdf из source_page.pdf: рендерит source в PNG,
замазывает белыми прямоугольниками координаты динамических полей, затем
вставляет PNG обратно как image layer в новый PDF.

ЗАЧЕМ:
  Старый скрипт make_blank_from_reference.py использовал pypdf merge_page
  для overlay белых прямоугольников. Это работает визуально, НО оригинальный
  text остаётся в content stream — pdfplumber находит «двойной текст» при
  извлечении. В итоговом рендере (overlay со значениями поверх blank) это
  проявляется как призрачные дублирующиеся символы рядом с рендеренными.

  Raster-blank решает это кардинально: в PDF только один объект — image.
  Никакого text layer нет. Overlay со значениями рисуется поверх чистого
  растра → результат идеален, без double-text.

ОТЛИЧИЯ ОТ make_blank_from_reference.py:
  + Нет double-text в итоговом рендере
  + Идеальная очистка (в пикселях, не в PDF-координатах)
  − Размер blank больше (~200-500 KB vs ~100 KB)
  − Нужен шаг растеризации — медленнее (секунда vs мгновенно)

Usage:
    python scripts/make_blank_raster.py \\
        --source templates/knd_1166002/source_page.pdf \\
        --fields templates/knd_1166002/fields.json \\
        --out    templates/knd_1166002/blank.pdf \\
        [--dpi 200] [--padding 3]

Параметры:
  --dpi     разрешение растеризации. 150 — достаточно, 200 — с запасом,
            300 — избыточно (PDF ~2 MB). Default 200.
  --padding отступ (в точках) для стирающих прямоугольников. Default 3.
"""
from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader


# ============================================================
# Чтение fields.json — только динамические поля
# ============================================================

def _iter_dynamic_fields(fields_json: dict):
    """Динамические поля (те, что надо стирать) из fields.json."""
    pages_def = fields_json.get("pages_def", {})
    for page_num, page_def in pages_def.items():
        fields = page_def.get("fields", {})
        for key, spec in fields.items():
            if key.startswith("_"):
                continue
            if spec.get("type") == "composite":
                continue
            if not spec.get("cells"):
                continue
            yield page_num, key, spec


def _field_bbox_pt(spec: dict, padding: float) -> tuple[float, float, float, float]:
    """Вычисляет bbox поля в pt (reportlab-coords, origin=bottom-left).

    Логика идентична make_blank_from_reference.py._field_bbox.
    """
    cells = spec["cells"]
    font_size = float(spec.get("font_size", 10.0))
    ftype = spec.get("type", "text_line")

    if ftype == "char_cells":
        xs = [c[0] for c in cells]
        ys = [c[1] for c in cells]
        x0 = min(xs) - padding
        x1 = max(xs) + font_size + padding
        y0 = min(ys) - padding
        y1 = max(ys) + font_size + padding
        return x0, y0, x1, y1

    # text_line
    x0, y0 = cells[0]
    sv = spec.get("sample_value") or ""
    if not sv:
        text_width = font_size * 25
    else:
        # Эвристика: символ ≈ 0.6 × font_size + 30% запас
        text_width = len(sv) * font_size * 0.6 * 1.3

    x1 = x0 + text_width + padding
    y1 = y0 + font_size + padding
    x0 -= padding
    y0 -= padding
    return x0, y0, x1, y1


# ============================================================
# Ядро
# ============================================================

def build_raster_blank(
    source_path: Path,
    fields_path: Path,
    out_path: Path,
    dpi: int = 200,
    padding: float = 3.0,
) -> dict:
    """Растровый blank.pdf. Возвращает статистику."""
    # 1. Растеризуем source_page в PIL Image
    source_bytes = source_path.read_bytes()
    pdf = pdfium.PdfDocument(source_bytes)
    if len(pdf) != 1:
        raise ValueError(f"{source_path}: должно быть 1 страница, не {len(pdf)}")
    page = pdf[0]
    page_w_pt = page.get_width()
    page_h_pt = page.get_height()

    scale = dpi / 72.0
    img = page.render(scale=scale).to_pil()
    img_w_px, img_h_px = img.size
    pdf.close()

    # 2. Конвертируем все bbox-ы из pt в пиксели и замазываем белым
    with fields_path.open(encoding="utf-8") as f:
        fields_data = json.load(f)

    draw = ImageDraw.Draw(img)

    erased_count = 0
    for _pnum, _key, spec in _iter_dynamic_fields(fields_data):
        x0_pt, y0_pt, x1_pt, y1_pt = _field_bbox_pt(spec, padding)

        # reportlab-coords (origin bottom-left) → PIL-coords (origin top-left)
        x0_px = int(x0_pt * scale)
        x1_px = int(x1_pt * scale)
        # инверсия Y: pil_y = height - rl_y
        y0_px = int((page_h_pt - y1_pt) * scale)
        y1_px = int((page_h_pt - y0_pt) * scale)

        # Ограничение
        x0_px = max(0, x0_px)
        y0_px = max(0, y0_px)
        x1_px = min(img_w_px, x1_px)
        y1_px = min(img_h_px, y1_px)
        if x1_px <= x0_px or y1_px <= y0_px:
            continue

        draw.rectangle([x0_px, y0_px, x1_px, y1_px], fill=(255, 255, 255))
        erased_count += 1

    # 3. Вставляем img обратно как image layer в PDF через reportlab
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # PIL Image → ImageReader для reportlab
    img_buf = BytesIO()
    img.save(img_buf, format="PNG", optimize=True)
    img_buf.seek(0)
    img_reader = ImageReader(img_buf)

    c = rl_canvas.Canvas(str(out_path), pagesize=(page_w_pt, page_h_pt))
    # drawImage(x, y, width, height) — растягиваем на всю страницу
    c.drawImage(img_reader, 0, 0, width=page_w_pt, height=page_h_pt)
    c.save()

    return {
        "erased_fields": erased_count,
        "source_dpi": dpi,
        "size_kb": out_path.stat().st_size / 1024,
        "image_size_px": (img_w_px, img_h_px),
        "page_size_pt": (page_w_pt, page_h_pt),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fields", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=200,
                        help="разрешение растеризации (default: 200)")
    parser.add_argument("--padding", type=float, default=3.0)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"❌ Не найден source: {args.source}", file=sys.stderr)
        return 1
    if not args.fields.exists():
        print(f"❌ Не найден fields.json: {args.fields}", file=sys.stderr)
        return 1

    try:
        stats = build_raster_blank(
            args.source, args.fields, args.out,
            dpi=args.dpi, padding=args.padding,
        )
    except Exception as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        return 1

    print(f"✓ {args.out}")
    print(f"   стёрто полей: {stats['erased_fields']}")
    print(f"   DPI: {stats['source_dpi']}, image: {stats['image_size_px']}, PDF pt: {stats['page_size_pt']}")
    print(f"   размер: {stats['size_kb']:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

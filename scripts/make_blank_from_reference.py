#!/usr/bin/env python3
"""
make_blank_from_reference.py

Создаёт чистый blank.pdf из заполненного source_page.pdf: накладывает белые
прямоугольники ("стирающие" слои) на координаты всех динамических полей
из fields.json, оставляя на странице только статические элементы формы
(заголовки, лейблы, рамки клеток).

Этот подход даёт pixel-perfect совпадение с эталоном — в отличие от
скачанного с nalog.ru бланка, который может отличаться по шрифту/полям.

Usage:
    python scripts/make_blank_from_reference.py \\
        --source templates/knd_1166002/source_page.pdf \\
        --fields templates/knd_1166002/fields.json \\
        --out    templates/knd_1166002/blank.pdf \\
        [--padding 2]

Как это работает:
  1. Читаем source_page.pdf (1 страница) в память
  2. Из fields.json берём все динамические поля (type != "composite", не _-префикс)
  3. Для каждого поля вычисляем bounding box по координатам cells + font_size
  4. Генерируем reportlab-overlay с белыми непрозрачными прямоугольниками
  5. Merge overlay на source через pypdf (zero-loss)
  6. Готовый blank.pdf сохраняется

Почему reportlab overlay, а не прямое редактирование PDF:
  - Прямое редактирование через pdfrw/pypdf ломает структуру содержимого
  - Overlay — zero-loss, не трогает исходные объекты страницы
  - Белый непрозрачный прямоугольник поверх текста даёт визуально чистый результат

Ограничения:
  - Если шрифт поля больше заявленного font_size — часть текста "вылезет".
    Решается параметром --padding (по умолчанию 2pt с каждой стороны).
  - Рамки знакомест (если есть) НЕ стираются — это правильно, они часть формы.
  - НЕ стирает константы формы, которые положены в _static_fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as rl_canvas


def _iter_dynamic_fields(fields_json: dict):
    """Yield (page_num, key, spec) только для динамических полей (то что надо стирать)."""
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


def _field_bbox(spec: dict, padding: float) -> tuple[float, float, float, float]:
    """
    Вычисляет (x0, y0, x1, y1) прямоугольник, покрывающий поле.

    Для char_cells: минимальный X первого cell и максимальный X последнего cell.
    Для text_line: от первого cell + ширина текста оценочно по sample_value.
                   Запас 30% для случая когда реальное значение длиннее sample.
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
        text_width = font_size * 25  # fallback если пусто
    else:
        # Эвристика: символ ≈ 0.6 × font_size + 30% запас (реальное значение может
        # быть длиннее sample, напр. ifns_full_name может быть длиннее чем sample)
        text_width = len(sv) * font_size * 0.6 * 1.3

    x1 = x0 + text_width + padding
    y1 = y0 + font_size + padding
    x0 -= padding
    y0 -= padding
    return x0, y0, x1, y1


def build_blank_pdf(
    source_path: Path,
    fields_path: Path,
    out_path: Path,
    padding: float = 2.0,
) -> int:
    """Основная логика. Возвращает число полей, которые были стёрты."""
    # Читаем source целиком в память — иначе PdfReader держит ссылку на закрытый файл
    source_bytes = source_path.read_bytes()
    reader = PdfReader(BytesIO(source_bytes))
    if len(reader.pages) != 1:
        raise ValueError(
            f"{source_path} должен содержать ровно 1 страницу, найдено {len(reader.pages)}"
        )

    page = reader.pages[0]
    page_w = float(page.mediabox.width)
    page_h = float(page.mediabox.height)

    with fields_path.open(encoding="utf-8") as f:
        fields_data = json.load(f)

    # Генерируем overlay с белыми прямоугольниками
    overlay_buf = BytesIO()
    c = rl_canvas.Canvas(overlay_buf, pagesize=(page_w, page_h))
    c.setFillColorRGB(1.0, 1.0, 1.0)
    c.setStrokeColorRGB(1.0, 1.0, 1.0)

    erased = 0
    for _page_num, _key, spec in _iter_dynamic_fields(fields_data):
        x0, y0, x1, y1 = _field_bbox(spec, padding)
        # Ограничиваем bbox в пределах страницы
        x0 = max(0.0, x0)
        y0 = max(0.0, y0)
        x1 = min(page_w, x1)
        y1 = min(page_h, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        c.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
        erased += 1

    c.save()

    # Merge на source — pypdf делает zero-loss overlay
    overlay_reader = PdfReader(BytesIO(overlay_buf.getvalue()))
    writer = PdfWriter()
    base = reader.pages[0]
    base.merge_page(overlay_reader.pages[0])
    writer.add_page(base)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)

    return erased


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", type=Path, required=True, help="source_page.pdf (заполненный эталон)")
    parser.add_argument("--fields", type=Path, required=True, help="fields.json с координатами полей")
    parser.add_argument("--out", type=Path, required=True, help="куда сохранить blank.pdf")
    parser.add_argument("--padding", type=float, default=2.0, help="отступ вокруг bbox (pt, default: 2.0)")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"❌ Не найден source: {args.source}", file=sys.stderr)
        return 1
    if not args.fields.exists():
        print(f"❌ Не найден fields.json: {args.fields}", file=sys.stderr)
        return 1

    try:
        n = build_blank_pdf(args.source, args.fields, args.out, padding=args.padding)
    except Exception as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        return 1

    size_kb = args.out.stat().st_size / 1024
    print(f"✓ {args.out}: стёрто {n} полей, размер {size_kb:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

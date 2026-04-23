#!/usr/bin/env python3
"""
extract_fields_from_reference.py

Извлекает координаты полей из реального эталонного PDF через pdfplumber.
Используется для полуавтоматической разметки templates/*/fields.json.

Usage:
    python scripts/extract_fields_from_reference.py \\
        --pdf templates/_user_reference/reference_tensor_6pages.pdf \\
        --page 4 \\
        --form-version 1166002 \\
        --out templates/knd_1166002/fields_auto.json

После автоматической разметки нужно вручную:
  1. Переименовать keys из содержимого в logical-names ("330573397709" → "taxpayer_inn")
  2. Убрать лишние совпадения (номера страниц, константные подписи формы)
  3. Добавить pad_char / align для полей

Работает для двух типов полей:
  - "char_cells": каждый символ в отдельной клетке (ИНН, ОКТМО — широко расставленные char)
  - "text_line": строка текста (имя файла, даты)

Детектор типа: если word состоит из N символов и все соседние символы на примерно
одинаковом расстоянии → char_cells (с координатами каждой клетки).
Иначе — text_line с координатой начала.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber


def detect_char_cells(chars_in_line: list[dict], tolerance: float = 1.5) -> bool:
    """Определяет, являются ли символы равномерно разнесёнными клетками."""
    if len(chars_in_line) < 3:
        return False
    gaps = [
        chars_in_line[i + 1]["x0"] - chars_in_line[i]["x1"]
        for i in range(len(chars_in_line) - 1)
    ]
    if not gaps:
        return False
    # Если все gaps близки к среднему → это клетки (равные промежутки)
    mean = sum(gaps) / len(gaps)
    return all(abs(g - mean) < tolerance for g in gaps) and mean > 2.0


def extract_fields(
    pdf_path: Path,
    page_idx: int,
) -> dict:
    """
    Разбирает указанную страницу PDF и формирует словарь полей в формате fields.json.

    Ключи — тексты найденных слов (потом переименовать вручную на logical-имена).
    """
    result = {"pages": 1, "pages_def": {"1": {"fields": {}}}}

    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_idx]
        page_height = page.height

        # Группируем слова по y-координате (одна строка)
        words = page.extract_words(keep_blank_chars=False, x_tolerance=1.0, y_tolerance=2.0)

        # Каждому слову получаем его символы с координатами через page.chars
        # Собираем по строкам: берём word, получаем все chars попадающие в его bbox
        chars = page.chars

        for w in words:
            txt = w["text"]
            if len(txt) < 2:
                continue
            # chars попадающие в bbox этого слова
            word_chars = [
                c for c in chars
                if w["x0"] - 0.5 <= c["x0"] <= w["x1"] + 0.5
                and w["top"] - 0.5 <= c["top"] <= w["bottom"] + 0.5
            ]
            if not word_chars:
                continue
            word_chars.sort(key=lambda c: c["x0"])

            is_cells = detect_char_cells(word_chars)

            # reportlab origin = bottom-left, pdfplumber origin = top-left → инвертируем Y
            if is_cells:
                cells = [
                    [round(c["x0"], 2), round(page_height - c["bottom"], 2)]
                    for c in word_chars
                ]
                field = {
                    "type": "char_cells",
                    "cells": cells,
                    "align": "left",
                    "font_size": round(word_chars[0]["size"], 1),
                    "sample_value": txt,
                }
            else:
                field = {
                    "type": "text_line",
                    "cells": [[round(w["x0"], 2), round(page_height - w["bottom"], 2)]],
                    "align": "left",
                    "font_size": round(word_chars[0]["size"], 1),
                    "sample_value": txt,
                }

            # Key = sample value, чтобы было понятно что это
            key = f"{txt[:40]}"
            # избегаем дубликатов
            k, i = key, 0
            while k in result["pages_def"]["1"]["fields"]:
                i += 1
                k = f"{key}__{i}"
            result["pages_def"]["1"]["fields"][k] = field

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True, help="0-indexed page")
    parser.add_argument("--form-version", required=True, help="e.g. 1166002")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"❌ PDF не найден: {args.pdf}", file=sys.stderr)
        return 1

    data = extract_fields(args.pdf, args.page)
    data["form_version"] = args.form_version
    data["fonts"] = {
        "primary": {"name": "DeclFont", "size": 10}
    }
    data["_note"] = (
        "Auto-extracted. РУЧНАЯ ДОРАБОТКА ТРЕБУЕТСЯ: "
        "(1) переименовать ключи в logical-имена, "
        "(2) удалить лишние (статические тексты формы), "
        "(3) проставить align/pad_char."
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total_fields = len(data["pages_def"]["1"]["fields"])
    print(f"✓ Извлечено {total_fields} полей → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

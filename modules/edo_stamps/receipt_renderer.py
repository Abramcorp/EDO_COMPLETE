"""
receipt_renderer.py — рендерер страниц квитанций ФНС (КНД 1166002 + 1166007).

Архитектура (см. ADR-003):
  1. Загрузить templates/knd_NNNNNNN/blank.pdf (чистый бланк)
  2. Загрузить templates/knd_NNNNNNN/fields.json (координатная карта)
  3. Для каждого динамического поля, подставить значение из ReceiptRenderData
  4. Сгенерировать reportlab overlay
  5. merge_page с blank → zero-loss pixel-perfect merge через pypdf
  6. Вернуть bytes

Публичные функции:
  - render_knd_1166002(data) -> bytes
  - render_knd_1166007(data) -> bytes
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas


# ============================================================
# Пути и константы
# ============================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates"


# ============================================================
# Регистрация шрифта (однократная)
# ============================================================

_FONT_REGISTERED = False
_FONT_NAME = "ReceiptFont"
_FONT_CANDIDATES = [
    # Linux/Debian (Railway image)
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    # edo_stamps fonts (есть в репо, копируется через sync_stamps.sh)
    Path(__file__).resolve().parent / "fonts" / "segoeui.ttf",
    Path(__file__).resolve().parent / "fonts" / "tahoma.ttf",
    # Windows системные — для разработки
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/tahoma.ttf"),
]


def _ensure_font_registered() -> str:
    """Регистрирует первый доступный шрифт. Возвращает имя зарегистрированного шрифта."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    for path in _FONT_CANDIDATES:
        if path.exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(path)))
            _FONT_REGISTERED = True
            return _FONT_NAME
    # В крайнем случае — встроенный Helvetica (латинский, кириллица не рендерится,
    # но не падает)
    return "Helvetica"


# ============================================================
# DTO входа
# ============================================================

@dataclass
class ReceiptRenderData:
    """Значения для подстановки в динамические поля квитанций."""
    # Налогоплательщик (декларант)
    taxpayer_inn: str
    taxpayer_fio: str                     # "РОМАНОВ ДМИТРИЙ ВЛАДИМИРОВИЧ" (обычно upper-case для 1166007)
    # Представитель (если не указан — совпадает с декларантом)
    representative_inn: str = ""
    representative_fio: str = ""          # "Куприянова Елена Евгеньевна"
    # Налоговый орган
    ifns_code: str = ""                   # 4 цифры
    ifns_full_name_line1: str = ""        # "УФНС России по Владимирской"
    ifns_full_name_line2: str = ""        # "области"
    ifns_full_name_upper: str = ""        # "УПРАВЛЕНИЕ ФЕДЕРАЛЬНОЙ НАЛОГОВОЙ СЛУЖБЫ ПО ВЛАДИМИРСКОЙ ОБЛАСТИ"
    # Декларация
    declaration_knd: str = "1152017"
    correction_number: int = 0
    tax_period_year: int = 2024
    # Квитанция
    file_name: str = ""                   # NO_USN_...
    submission_datetime: datetime | None = None
    acceptance_datetime: datetime | None = None
    registration_number: str = ""


# ============================================================
# Хелперы
# ============================================================

def _load_fields(knd: str) -> dict:
    path = _TEMPLATES_DIR / f"knd_{knd}" / "fields.json"
    if not path.exists():
        raise FileNotFoundError(f"fields.json не найден: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_blank(knd: str) -> bytes:
    path = _TEMPLATES_DIR / f"knd_{knd}" / "blank.pdf"
    if not path.exists():
        raise FileNotFoundError(
            f"blank.pdf не найден: {path}\n"
            f"Сгенерируй его: python scripts/make_blank_from_reference.py "
            f"--source templates/knd_{knd}/source_page.pdf "
            f"--fields templates/knd_{knd}/fields.json "
            f"--out templates/knd_{knd}/blank.pdf"
        )
    return path.read_bytes()


def _split_filename(filename: str, first_line_len: int = 54) -> tuple[str, str]:
    """
    Имя файла длинное — в эталоне переносится на 2 строки после ~54 символа.
    Возвращает (line1, line2).
    """
    if len(filename) <= first_line_len:
        return filename, ""
    return filename[:first_line_len], filename[first_line_len:]


# ============================================================
# Маппинги значений → названия полей в fields.json
# ============================================================

def _values_for_1166002(data: ReceiptRenderData) -> dict[str, str]:
    """Преобразует DTO в dict {field_name: value} для рендера."""
    rep_fio = data.representative_fio or data.taxpayer_fio
    rep_inn = data.representative_inn or data.taxpayer_inn

    submit = data.submission_datetime
    accept = data.acceptance_datetime

    file_line1, file_line2 = _split_filename(data.file_name)

    return {
        "representative_fio_line1": rep_fio + ",",
        "representative_inn": rep_inn,
        "ifns_full_name_line1": data.ifns_full_name_line1,
        "ifns_full_name_line2": data.ifns_full_name_line2,
        "ifns_code_after_name": f"{data.ifns_code})",
        "declarant_fio_and_inn_line": f"{data.taxpayer_fio}, {data.taxpayer_inn}",
        "declarant_inn_explicit": data.taxpayer_inn,
        "submission_date": submit.strftime("%d.%m.%Y") if submit else "",
        "submission_time": submit.strftime("%H.%M.%S") if submit else "",
        "declaration_name_and_knd": (
            "Налоговая декларация по налогу, уплачиваемому в связи с применением "
            "упрощенной системы налогообложения (КНД 1152017)"
        ),
        "correction_number": f"корректирующий ({data.correction_number})",
        "tax_period_code_and_year": f"за год, 34, {data.tax_period_year} год",
        "tax_period_year_only": str(data.tax_period_year),
        "file_name_line1": file_line1,
        "file_name_line2": file_line2,
        "ifns_code_reception": f"{data.ifns_code})",
        "reception_date": submit.strftime("%d.%m.%Y") if submit else "",
        "acceptance_date": accept.strftime("%d.%m.%Y") if accept else "",
        "registration_number": data.registration_number,
        # Поля штампа (stamp_*) — не заполняем здесь, их пишет apply_stamps
    }


def _values_for_1166007(data: ReceiptRenderData) -> dict[str, str]:
    rep_fio = data.representative_fio or data.taxpayer_fio
    rep_inn = data.representative_inn or data.taxpayer_inn
    file_line1, file_line2 = _split_filename(data.file_name)

    return {
        "representative_fio_line1": rep_fio + ",",
        "representative_inn": rep_inn,
        "ifns_code_header": data.ifns_code,
        "declarant_fio_and_inn_line": f"{data.taxpayer_fio}, {data.taxpayer_inn}",
        "declarant_inn_explicit": data.taxpayer_inn,
        "declaration_name_line1": (
            "Налоговая декларация по налогу, уплачиваемому в связи с применением упрощенной системы"
        ),
        "declaration_name_line2": (
            f"налогообложения {data.declaration_knd}, корректирующий ({data.correction_number}), "
            f"за год, {data.tax_period_year} год"
        ),
        "correction_number_only": f"корректирующий ({data.correction_number})",
        "tax_period_year_only": str(data.tax_period_year),
        "file_name_line1": file_line1,
        "file_name_line2": file_line2,
        "ifns_full_name_and_code": f"{data.ifns_full_name_upper}, {data.ifns_code}",
        "ifns_code_footer": data.ifns_code,
    }


# ============================================================
# Ядро рендера
# ============================================================

def _render_overlay(
    fields_data: dict,
    values: dict[str, str],
    page_w: float,
    page_h: float,
) -> bytes:
    """Рендерит reportlab overlay со значениями по координатам fields.json."""
    font_name = _ensure_font_registered()
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.setFillColorRGB(0.0, 0.0, 0.0)

    page_def = fields_data.get("pages_def", {}).get("1", {})
    fields = page_def.get("fields", {})

    for key, spec in fields.items():
        if key.startswith("_"):
            continue
        if spec.get("type") == "composite":
            continue
        # Поля stamp_* отрисовываются через apply_stamps, не здесь
        if key.startswith("stamp_"):
            continue

        value = values.get(key, "")
        if not value:
            continue

        cells = spec.get("cells") or []
        if not cells:
            continue

        font_size = float(spec.get("font_size", 8.5))
        try:
            c.setFont(font_name, font_size)
        except KeyError:
            c.setFont("Helvetica", font_size)

        ftype = spec.get("type", "text_line")
        if ftype == "char_cells":
            # Каждый символ в свою клетку
            align = spec.get("align", "left")
            n = len(cells)
            s = str(value)
            if align == "right":
                s = s.rjust(n)[-n:]
            elif align == "center":
                pad = max(0, (n - len(s)) // 2)
                s = (" " * pad + s).ljust(n)[:n]
            else:
                s = s.ljust(n)[:n]
            for i, ch in enumerate(s):
                if ch.strip():
                    x, y = cells[i]
                    c.drawString(x, y, ch)
        else:  # text_line
            x, y = cells[0]
            c.drawString(x, y, str(value))

    c.save()
    return buf.getvalue()


def _render_page(knd: str, values: dict[str, str]) -> bytes:
    """Ядро: подложка blank + overlay → готовая страница."""
    blank_bytes = _load_blank(knd)
    fields_data = _load_fields(knd)

    blank_reader = PdfReader(BytesIO(blank_bytes))
    base_page = blank_reader.pages[0]
    page_w = float(base_page.mediabox.width)
    page_h = float(base_page.mediabox.height)

    overlay_bytes = _render_overlay(fields_data, values, page_w, page_h)
    overlay_reader = PdfReader(BytesIO(overlay_bytes))

    writer = PdfWriter()
    base_page.merge_page(overlay_reader.pages[0])
    writer.add_page(base_page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ============================================================
# Публичный API
# ============================================================

def render_knd_1166002(data: ReceiptRenderData) -> bytes:
    """Рендерит страницу КНД 1166002 (квитанция о приёме)."""
    return _render_page("1166002", _values_for_1166002(data))


def render_knd_1166007(data: ReceiptRenderData) -> bytes:
    """Рендерит страницу КНД 1166007 (извещение о вводе)."""
    return _render_page("1166007", _values_for_1166007(data))


def render_receipt_pages(data: ReceiptRenderData) -> bytes:
    """
    Рендерит ОБЕ страницы квитанций как единый 2-страничный PDF.

    Используется из build_receipt_pages() в __init__.py → pipeline.
    """
    page1 = render_knd_1166002(data)
    page2 = render_knd_1166007(data)

    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(page1)).pages[0])
    writer.add_page(PdfReader(BytesIO(page2)).pages[0])

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


__all__ = [
    "ReceiptRenderData",
    "render_knd_1166002",
    "render_knd_1166007",
    "render_receipt_pages",
]

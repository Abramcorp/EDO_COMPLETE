"""
PdfOverlayFiller — pixel-perfect рендер декларации КНД 1152017.

Алгоритм (ADR-002):
  1. Загрузить официальную подложку ФНС: templates/knd_1152017/blank_YYYY.pdf
  2. Загрузить координатную карту: templates/knd_1152017/fields_YYYY.json
  3. Сгенерировать overlay-слой через reportlab canvas
  4. Merge overlay на подложку через pypdf (zero-loss)
  5. Вернуть bytes

Шрифт: регистрируется при первом вызове из templates/knd_1152017/fonts/.
Default: PT Sans (MSP)  / Liberation Sans (fallback).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas


# ============================================================
# Пути
# ============================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "knd_1152017"


# ============================================================
# Регистрация шрифта (однократная)
# ============================================================

_FONT_REGISTERED = False
_DEFAULT_FONT_NAME = "DeclFont"
_FONT_CANDIDATES = [
    ("PT Sans Regular",   _TEMPLATES_DIR / "fonts" / "PTSans-Regular.ttf"),
    ("Liberation Sans",   Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")),
    ("DejaVu Sans",       Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
]


def _ensure_font_registered() -> str:
    """Регистрирует первый найденный шрифт из кандидатов. Возвращает имя."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _DEFAULT_FONT_NAME
    for _display_name, path in _FONT_CANDIDATES:
        if path.exists():
            pdfmetrics.registerFont(TTFont(_DEFAULT_FONT_NAME, str(path)))
            _FONT_REGISTERED = True
            return _DEFAULT_FONT_NAME
    raise RuntimeError(
        "Не найден ни один шрифт для рендера декларации. "
        "Положи PTSans-Regular.ttf в templates/knd_1152017/fonts/ "
        "или установи fonts-liberation."
    )


# ============================================================
# Координатная карта
# ============================================================

@dataclass
class FieldSpec:
    """Описание одного поля в fields_YYYY.json."""
    type: Literal["char_cells", "checkbox"]
    cells: list[list[float]]           # [[x, y], ...] в points (reportlab origin = bottom-left)
    align: Literal["left", "right", "center"] = "left"
    font_size: float = 11.0
    pad_char: str = " "


def _load_fields_map(year: int) -> dict:
    """Загружает fields_YYYY.json. Fallback на ближайший доступный год."""
    for candidate_year in (year, year - 1):
        path = _TEMPLATES_DIR / f"fields_{candidate_year}.json"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"Не найден fields_{year}.json (и fallback fields_{year-1}.json). "
        f"Заложить в templates/knd_1152017/ в Фазе 0a."
    )


def _locate_blank_pdf(year: int) -> Path:
    """Возвращает путь к подложке blank_YYYY.pdf. Fallback на предыдущий год."""
    for candidate_year in (year, year - 1):
        path = _TEMPLATES_DIR / f"blank_{candidate_year}.pdf"
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Не найдена подложка blank_{year}.pdf (и fallback blank_{year-1}.pdf). "
        f"Скачать с nalog.ru официальную форму КНД 1152017 для года {year}."
    )


# ============================================================
# PdfOverlayFiller
# ============================================================

class PdfOverlayFiller:
    """
    Рендерит декларацию КНД 1152017 для указанного налогового года.

    Использование:
        filler = PdfOverlayFiller(tax_period_year=2024)
        pdf_bytes = filler.render(taxpayer=..., tax_result=...)
    """

    def __init__(self, tax_period_year: int):
        self.year = tax_period_year
        self.fields_map = _load_fields_map(tax_period_year)
        self.blank_path = _locate_blank_pdf(tax_period_year)
        self.font_name = _ensure_font_registered()

    # ----------------------------------------------------------

    def render(self, *, taxpayer, tax_result) -> bytes:
        """Главный entry-point. Возвращает PDF bytes."""
        page_data = self._prepare_page_data(taxpayer, tax_result)
        overlay_bytes = self._build_overlay(page_data)
        return self._merge_with_blank(overlay_bytes)

    # ----------------------------------------------------------
    # Подготовка данных: превращаем decl_data/project_data в
    # {page_idx: {field_name: "string"}}
    # ----------------------------------------------------------

    def _prepare_page_data(self, taxpayer, tax_result) -> dict[int, dict[str, str]]:
        """
        Маппим Pydantic/TaxResult структуры в плоский dict, удобный для рендера.

        ЗАМЕТКА: конкретные маппинги полей зависят от того, как размечен
        fields_YYYY.json. Этот код — скелет. Дополняется вместе с fields.json
        в Фазе 0a.
        """
        decl = tax_result.decl_data
        s211 = decl.get("section_2_1_1", {})
        s11 = decl.get("section_1_1", {})

        # Титульный лист (стр. 1)
        page1 = {
            "inn": taxpayer.inn,
            "fio_surname": _split_fio(taxpayer.fio, 0),
            "fio_name": _split_fio(taxpayer.fio, 1),
            "fio_patronymic": _split_fio(taxpayer.fio, 2),
            "tax_period_year": str(self.year),
            "ifns_code": taxpayer.ifns_code,
            "oktmo_title": taxpayer.oktmo,
        }

        # Раздел 1.1 (стр. 2)
        page2 = {
            "inn": taxpayer.inn,
            "line_010_oktmo": taxpayer.oktmo,
            "line_020": _fmt_amount(s11.get("line_020")),
            "line_040": _fmt_amount(s11.get("line_040")),
            "line_050": _fmt_amount(s11.get("line_050")),
            "line_070": _fmt_amount(s11.get("line_070")),
            "line_080": _fmt_amount(s11.get("line_080")),
            "line_100": _fmt_amount(s11.get("line_100")),
            "line_110": _fmt_amount(s11.get("line_110")),
        }

        # Раздел 2.1.1 часть 1 (стр. 3)
        page3 = {
            "inn": taxpayer.inn,
            "line_101": str(s211.get("line_101", "")),
            "line_102": str(s211.get("line_102", "")),
            "line_110": _fmt_amount(s211.get("line_110")),
            "line_111": _fmt_amount(s211.get("line_111")),
            "line_112": _fmt_amount(s211.get("line_112")),
            "line_113": _fmt_amount(s211.get("line_113")),
            "line_120": _fmt_rate(s211.get("line_120")),
            "line_121": _fmt_rate(s211.get("line_121")),
            "line_122": _fmt_rate(s211.get("line_122")),
            "line_123": _fmt_rate(s211.get("line_123")),
            "line_130": _fmt_amount(s211.get("line_130")),
            "line_131": _fmt_amount(s211.get("line_131")),
            "line_132": _fmt_amount(s211.get("line_132")),
            "line_133": _fmt_amount(s211.get("line_133")),
        }

        # Раздел 2.1.1 часть 2 (стр. 4)
        page4 = {
            "inn": taxpayer.inn,
            "line_140": _fmt_amount(s211.get("line_140")),
            "line_141": _fmt_amount(s211.get("line_141")),
            "line_142": _fmt_amount(s211.get("line_142")),
            "line_143": _fmt_amount(s211.get("line_143")),
        }

        return {1: page1, 2: page2, 3: page3, 4: page4}

    # ----------------------------------------------------------
    # Генерация overlay через reportlab
    # ----------------------------------------------------------

    def _build_overlay(self, page_data: dict[int, dict[str, str]]) -> bytes:
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)

        pages_def = self.fields_map.get("pages_def", {})
        total_pages = int(self.fields_map.get("pages", 4))

        for page_idx in range(1, total_pages + 1):
            fields = pages_def.get(str(page_idx), {}).get("fields", {})
            values = page_data.get(page_idx, {})

            for field_name, spec_dict in fields.items():
                value = values.get(field_name)
                if value is None or value == "":
                    continue
                spec = FieldSpec(
                    type=spec_dict.get("type", "char_cells"),
                    cells=spec_dict.get("cells", []),
                    align=spec_dict.get("align", "left"),
                    font_size=float(spec_dict.get("font_size", 11.0)),
                    pad_char=spec_dict.get("pad_char", " "),
                )
                self._draw_field(c, spec, value)
            c.showPage()
        c.save()
        return buf.getvalue()

    def _draw_field(self, c: rl_canvas.Canvas, spec: FieldSpec, value: str) -> None:
        """Рисует значение value по клеткам spec.cells."""
        if spec.type == "checkbox":
            # Для checkbox клетка одна, value — "V" или "X"
            if not spec.cells:
                return
            x, y = spec.cells[0]
            c.setFont(self.font_name, spec.font_size)
            c.drawString(x, y, "V")
            return

        # char_cells: каждая буква в свою клетку
        n = len(spec.cells)
        s = str(value)

        if spec.align == "right":
            s = s.rjust(n)[-n:]
        elif spec.align == "center":
            pad_left = max(0, (n - len(s)) // 2)
            s = (" " * pad_left + s).ljust(n)[:n]
        else:  # left
            s = s.ljust(n)[:n]

        c.setFont(self.font_name, spec.font_size)
        for i, ch in enumerate(s):
            if ch.strip() == "":
                continue
            x, y = spec.cells[i]
            # drawCentredString если хотим центрировать символ внутри клетки
            c.drawString(x, y, ch)

    # ----------------------------------------------------------
    # Merge overlay с подложкой
    # ----------------------------------------------------------

    def _merge_with_blank(self, overlay_bytes: bytes) -> bytes:
        reader_base = PdfReader(str(self.blank_path))
        reader_overlay = PdfReader(BytesIO(overlay_bytes))
        writer = PdfWriter()

        n_base = len(reader_base.pages)
        n_overlay = len(reader_overlay.pages)

        for i in range(n_base):
            base_page = reader_base.pages[i]
            if i < n_overlay:
                base_page.merge_page(reader_overlay.pages[i])
            writer.add_page(base_page)

        out_buf = BytesIO()
        writer.write(out_buf)
        return out_buf.getvalue()


# ============================================================
# Хелперы
# ============================================================

def _split_fio(fio: str, idx: int) -> str:
    """Разбивает ФИО на [фамилия, имя, отчество]. Возвращает часть idx."""
    parts = fio.strip().split(maxsplit=2)
    if idx < len(parts):
        return parts[idx]
    return ""


def _fmt_amount(value: Any) -> str:
    """Целые рубли без копеек."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value)


def _fmt_rate(value: Any) -> str:
    """Ставка × 10: 60 → '60' (отображается в 3 клетках как '060' либо '6.0' в зависимости от поля)."""
    if value is None:
        return ""
    return str(int(value)) if isinstance(value, (int, float, Decimal)) else str(value)

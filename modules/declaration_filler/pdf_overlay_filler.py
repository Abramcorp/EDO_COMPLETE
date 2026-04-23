"""
PdfOverlayFiller — pixel-perfect рендер декларации КНД 1152017.

Реализует data flow из ADR-004:
  DeclarationData → PdfOverlayFiller.render() → bytes PDF

Алгоритм:
  1. Загрузить templates/knd_1152017/blank_YYYY.pdf (4 страницы, чистый бланк)
  2. Загрузить templates/knd_1152017/fields_YYYY.json (координатная карта)
  3. Маппим DeclarationData → dict плоских значений per-страница
  4. Через reportlab генерируем overlay layer
  5. Merge overlay с blank через pypdf (PdfWriter clone_from)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from .declaration_data import DeclarationData


# ============================================================
# Пути
# ============================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "knd_1152017"


# ============================================================
# Шрифт — Tahoma (общий с receipt_renderer для единообразия)
# ============================================================

_FONT_REGISTERED = False
_FONT_NAME = "DeclFont"
_FONT_CANDIDATES = [
    # ПРИОРИТЕТ 1: Tahoma — шрифт эталона ТЕНЗОР
    _PROJECT_ROOT / "modules" / "edo_stamps" / "fonts" / "tahoma.ttf",
    # ПРИОРИТЕТ 2: Segoe UI (КОНТУР)
    _PROJECT_ROOT / "modules" / "edo_stamps" / "fonts" / "segoeui.ttf",
    # Dev fallbacks
    Path("C:/Windows/Fonts/tahoma.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _ensure_font_registered() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    for path in _FONT_CANDIDATES:
        if path.exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(path)))
            _FONT_REGISTERED = True
            return _FONT_NAME
    return "Helvetica"  # крайний фолбек без кириллицы


# ============================================================
# FieldSpec
# ============================================================

@dataclass
class FieldSpec:
    type: Literal["char_cells", "text_line", "checkbox"]
    cells: list[list[float]]
    align: Literal["left", "right", "center"] = "left"
    font_size: float = 10.0


def _load_fields_map(year: int) -> dict:
    for candidate_year in (year, year - 1):
        path = _TEMPLATES_DIR / f"fields_{candidate_year}.json"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"Не найден fields_{year}.json (и fallback fields_{year-1}.json)."
    )


def _locate_blank_pdf(year: int) -> Path:
    for candidate_year in (year, year - 1):
        path = _TEMPLATES_DIR / f"blank_{candidate_year}.pdf"
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Не найден blank_{year}.pdf (и fallback blank_{year-1}.pdf)."
    )


# ============================================================
# Хелперы форматирования
# ============================================================

def _fmt_amount(value: Any) -> str:
    """Сумма без копеек (целые рубли). Ноль → пусто."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        v = int(value)
    elif isinstance(value, (int, float)):
        v = int(value)
    else:
        return str(value)
    return str(v) if v > 0 else ""


def _fmt_rate(value: Any) -> str:
    """Ставка в формате 'X.Y' (например '6.0')."""
    if value is None:
        return ""
    if isinstance(value, (Decimal, int, float)):
        return f"{float(value):.1f}"
    return str(value)


def _fmt_oktmo(value: str) -> str:
    if not value:
        return ""
    return str(value).strip()


# ============================================================
# PdfOverlayFiller
# ============================================================

class PdfOverlayFiller:
    """
    Рендерит декларацию КНД 1152017.

    Использование:
        filler = PdfOverlayFiller(tax_period_year=2025)
        pdf_bytes = filler.render(data)  # data: DeclarationData
    """

    def __init__(self, tax_period_year: int):
        self.year = tax_period_year
        self.fields_map = _load_fields_map(tax_period_year)
        self.blank_path = _locate_blank_pdf(tax_period_year)
        self.font_name = _ensure_font_registered()

    def render(self, data: DeclarationData) -> bytes:
        errors = data.validate()
        if errors:
            raise ValueError(f"DeclarationData невалидна: {errors}")

        page_values = self._prepare_values(data)
        overlay = self._build_overlay(page_values)
        return self._merge_with_blank(overlay)

    # --------------------------------------------------------

    def _prepare_values(self, data: DeclarationData) -> dict[str, dict[str, str]]:
        title = data.title

        # === Страница 1 — Титульный лист ===
        # correction_number: заполняется слева, справа прочерки.
        # "1" → "1--" (3 знакоместа), "10" → "10-" и т.д.
        corr = str(title.correction_number)
        corr_padded = corr + "-" * max(0, 3 - len(corr))

        page1 = {
            "inn": title.inn,
            "kpp": title.kpp,
            "page_number": "001",
            "correction_number": corr_padded,
            "tax_period_code": title.tax_period_code,
            "tax_period_year": str(title.tax_period_year),
            "ifns_code": title.ifns_code,
            "at_location_code": title.at_location_code,
            "taxpayer_name_line1": title.taxpayer_name_line1,
            "taxpayer_name_line2": title.taxpayer_name_line2,
            "taxpayer_name_line3": title.taxpayer_name_line3,
            "taxpayer_name_line4": title.taxpayer_name_line4,
            "phone": title.phone.lstrip("+"),
        }
        if title.signing_date:
            page1.update({
                "signing_date_day": f"{title.signing_date.day:02d}",
                "signing_date_month": f"{title.signing_date.month:02d}",
                "signing_date_year": f"{title.signing_date.year}",
            })

        # === Страницы 2-4 — колонтитул ===
        page2: dict[str, str] = {
            "inn_header": title.inn,
            "kpp_header": title.kpp,
            "page_number_header": "002",
        }
        page3 = dict(page2, page_number_header="003")
        page4 = dict(page2, page_number_header="004")

        # === Р.1.1 (страница 2) ===
        if data.section_1_1:
            s11 = data.section_1_1
            page2.update({
                "oktmo_q1": _fmt_oktmo(s11.oktmo_q1),
                "advance_q1": _fmt_amount(s11.advance_q1),
                "oktmo_h1": _fmt_oktmo(s11.oktmo_h1),
                "advance_h1": _fmt_amount(s11.advance_h1),
                "advance_h1_reduction": _fmt_amount(s11.advance_h1_reduction),
                "oktmo_9m": _fmt_oktmo(s11.oktmo_9m),
                "advance_9m": _fmt_amount(s11.advance_9m),
                "advance_9m_reduction": _fmt_amount(s11.advance_9m_reduction),
                "oktmo_y": _fmt_oktmo(s11.oktmo_y),
                "tax_year_payable": _fmt_amount(s11.tax_year_payable),
                "tax_year_reduction": _fmt_amount(s11.tax_year_reduction),
                "tax_year_payable_stp": _fmt_amount(s11.tax_year_payable_stp),
            })
            if title.signing_date:
                page2["signing_date_p2"] = title.signing_date.strftime("%d.%m.%Y")

        # === Р.2.1.1 (страницы 3 и 4) ===
        if data.section_2_1_1:
            s211 = data.section_2_1_1
            page3.update({
                "taxpayer_sign": str(s211.taxpayer_sign),
                "income_q1": _fmt_amount(s211.income_q1),
                "income_h1": _fmt_amount(s211.income_h1),
                "income_9m": _fmt_amount(s211.income_9m),
                "income_y": _fmt_amount(s211.income_y),
                "tax_rate_q1": _fmt_rate(s211.tax_rate_q1),
                "tax_rate_h1": _fmt_rate(s211.tax_rate_h1),
                "tax_rate_9m": _fmt_rate(s211.tax_rate_9m),
                "tax_rate_y": _fmt_rate(s211.tax_rate_y),
                "reduced_rate_basis": s211.reduced_rate_basis,
                "tax_calc_q1": _fmt_amount(s211.tax_calc_q1),
                "tax_calc_h1": _fmt_amount(s211.tax_calc_h1),
                "tax_calc_9m": _fmt_amount(s211.tax_calc_9m),
                "tax_calc_y": _fmt_amount(s211.tax_calc_y),
            })
            page4.update({
                "insurance_q1": _fmt_amount(s211.insurance_q1),
                "insurance_h1": _fmt_amount(s211.insurance_h1),
                "insurance_9m": _fmt_amount(s211.insurance_9m),
                "insurance_y": _fmt_amount(s211.insurance_y),
            })

        return {"1": page1, "2": page2, "3": page3, "4": page4}

    # --------------------------------------------------------

    def _build_overlay(self, page_values: dict[str, dict[str, str]]) -> bytes:
        w, h = self.fields_map.get("page_size_pt", [594.96, 841.92])
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(w, h))
        c.setFillColorRGB(0.0, 0.0, 0.0)

        pages_def = self.fields_map.get("pages_def", {})
        total_pages = int(self.fields_map.get("pages", 4))

        for page_num in range(1, total_pages + 1):
            page_key = str(page_num)
            page_def = pages_def.get(page_key, {})
            fields = page_def.get("fields", {})
            values = page_values.get(page_key, {})

            for field_name, spec_dict in fields.items():
                if field_name.startswith("_"):
                    continue
                value = values.get(field_name)
                if value is None or value == "":
                    continue
                spec = FieldSpec(
                    type=spec_dict.get("type", "char_cells"),
                    cells=spec_dict.get("cells", []),
                    align=spec_dict.get("align", "left"),
                    font_size=float(spec_dict.get("font_size", 10.0)),
                )
                self._draw_field(c, spec, str(value))
            c.showPage()

        c.save()
        return buf.getvalue()

    def _draw_field(self, c: rl_canvas.Canvas, spec: FieldSpec, value: str) -> None:
        if not spec.cells:
            return
        try:
            c.setFont(self.font_name, spec.font_size)
        except KeyError:
            c.setFont("Helvetica", spec.font_size)

        if spec.type == "text_line":
            x, y = spec.cells[0]
            c.drawString(x, y, value)
            return

        if spec.type == "checkbox":
            x, y = spec.cells[0]
            c.drawString(x, y, "V")
            return

        # char_cells
        n = len(spec.cells)
        s = value
        if spec.align == "right":
            s = s.rjust(n)[-n:]
        elif spec.align == "center":
            pad = max(0, (n - len(s)) // 2)
            s = (" " * pad + s).ljust(n)[:n]
        else:
            s = s.ljust(n)[:n]

        for i, ch in enumerate(s):
            if ch.strip():
                x, y = spec.cells[i]
                c.drawString(x, y, ch)

    # --------------------------------------------------------

    def _merge_with_blank(self, overlay_bytes: bytes) -> bytes:
        """Рекомендованный pypdf 6+ API без deprecation."""
        blank_reader = PdfReader(str(self.blank_path))
        overlay_reader = PdfReader(BytesIO(overlay_bytes))

        writer = PdfWriter(clone_from=blank_reader)

        n_overlay = len(overlay_reader.pages)
        for i in range(len(writer.pages)):
            if i < n_overlay:
                writer.pages[i].merge_page(overlay_reader.pages[i])

        out = BytesIO()
        writer.write(out)
        return out.getvalue()


# ============================================================
# Публичная функция
# ============================================================

def render_declaration(data: DeclarationData) -> bytes:
    """Рендерит декларацию из DeclarationData. Версия формы — по title.tax_period_year."""
    filler = PdfOverlayFiller(tax_period_year=data.title.tax_period_year)
    return filler.render(data)


__all__ = [
    "PdfOverlayFiller",
    "render_declaration",
    "FieldSpec",
]

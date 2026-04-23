"""
Pixel-diff тесты декларации КНД 1152017 против эталона ТЕНЗОРа.

Эталон (reference_tensor_6pages.pdf) содержит персональные данные и находится
в .gitignore. Тесты автоматически SKIP если его нет.

Структура эталона:
  page 0-3 — декларация КНД 1152017
  page 4   — квитанция о приёме (тестируется в test_pixel_diff_receipts.py)
  page 5   — извещение о вводе

Текущий diff (PR #13, замеры 2026-04):
  стр.1 (Титул):      ~9.5%  (≈ 200K pixels strong diff / 2.2M total)
  стр.2 (Р.1.1):      ~8.0%
  стр.3 (Р.2.1.1):    ~7.3%
  стр.4 (Р.2.1.1 пр): ~4.2%
  ИТОГО:              ~7.3%

Основные источники (в порядке убывания вклада):
  1. Статические лейблы формы — стёрты в raster blank, не восстановлены.
     Будут возвращены form_static overlay в следующем PR.
  2. ФИО налогоплательщика — в эталоне char_cells по знакоместам, в
     текущей разметке text_line. Требует переразметки taxpayer_name_*.
  3. Не все поля TitlePage реализованы: signer_*, representative_document,
     object_code, pages_count, appendices_pages.
  4. Мелкие baseline-сдвиги reportlab vs оригинального рендерера.

Целевые tolerance (на roadmap):
  PR #13 (этот):      < 15% — фиксируем текущее состояние
  после form_static:  <  5%
  после доразметки:   <  2%
  pixel-perfect:      <  1%
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from modules.declaration_filler.declaration_data import (
    DeclarationData,
    TitlePage,
    Section_1_1,
    Section_2_1_1,
    OBJECT_INCOME,
    TP_SIGN_IP_NO_EMPLOYEES,
    LOC_IP_RESIDENCE,
)
from modules.declaration_filler.pdf_overlay_filler import render_declaration
from tests.pixel_diff import PdfPixelDiff


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PDF = PROJECT_ROOT / "templates" / "_user_reference" / "reference_tensor_6pages.pdf"
REFERENCE_AVAILABLE = REFERENCE_PDF.exists()
_SKIP_REASON = (
    f"Эталон {REFERENCE_PDF.name} не найден. Положи локально — тест прогонится. "
    f"В CI этот тест skip'ается (файл в .gitignore, содержит ПД)."
)


@pytest.fixture
def romanov_data() -> DeclarationData:
    """Данные из эталона ТЕНЗОРа (Романов Д.В. УСН 2025)."""
    return DeclarationData(
        title=TitlePage(
            inn="330573397709",
            kpp="",
            correction_number=1,
            tax_period_year=2025,
            ifns_code="3300",
            at_location_code=LOC_IP_RESIDENCE,
            taxpayer_name_line1="Романов",
            taxpayer_name_line2="Дмитрий",
            taxpayer_name_line3="Владимирович",
            phone="79157503070",
            signing_date=date(2026, 1, 24),
            object_code=OBJECT_INCOME,
        ),
        section_1_1=Section_1_1(oktmo_q1="17701000"),
        section_2_1_1=Section_2_1_1(
            taxpayer_sign=TP_SIGN_IP_NO_EMPLOYEES,
            income_9m=Decimal("409517"),
            income_y=Decimal("409517"),
            tax_rate_q1=Decimal("6.0"),
            tax_rate_h1=Decimal("6.0"),
            tax_rate_9m=Decimal("6.0"),
            tax_rate_y=Decimal("6.0"),
            tax_calc_9m=Decimal("24571"),
            tax_calc_y=Decimal("24571"),
            insurance_9m=Decimal("24571"),
            insurance_y=Decimal("24571"),
        ),
    )


# ============================================================
# Per-page diff с реалистичным tolerance для MVP
# ============================================================

TOLERANCE_MVP = 0.15  # < 15%, будет снижаться по мере доработки


@pytest.mark.skipif(not REFERENCE_AVAILABLE, reason=_SKIP_REASON)
class TestPixelDiffDeclaration:
    """Сравнение нашего рендера декларации с эталонными страницами."""

    def _render_and_diff(self, data: DeclarationData, page: int):
        pdf = render_declaration(data)
        return PdfPixelDiff(pdf, REFERENCE_PDF, page_a=page, page_b=page, dpi=150)

    def test_page_1_title_within_tolerance(self, romanov_data):
        """Стр. 1 — Титульный лист."""
        diff = self._render_and_diff(romanov_data, page=0).compare()
        assert diff.diff_ratio < TOLERANCE_MVP, (
            f"Титульный лист: diff {diff.diff_ratio:.2%} > tolerance {TOLERANCE_MVP:.0%}. "
            f"Основные источники: статические лейблы формы (PR #14)."
        )

    def test_page_2_section_1_1_within_tolerance(self, romanov_data):
        """Стр. 2 — Р.1.1 суммы налога."""
        diff = self._render_and_diff(romanov_data, page=1).compare()
        assert diff.diff_ratio < TOLERANCE_MVP

    def test_page_3_section_2_1_1_within_tolerance(self, romanov_data):
        """Стр. 3 — Р.2.1.1 расчёт налога."""
        diff = self._render_and_diff(romanov_data, page=2).compare()
        assert diff.diff_ratio < TOLERANCE_MVP

    def test_page_4_section_2_1_1_cont_within_tolerance(self, romanov_data):
        """Стр. 4 — Р.2.1.1 продолжение (взносы)."""
        diff = self._render_and_diff(romanov_data, page=3).compare()
        assert diff.diff_ratio < TOLERANCE_MVP


# ============================================================
# Smoke-тесты harness'а (не требуют эталона)
# ============================================================

class TestHarnessSmoke:
    """Проверка самого PdfPixelDiff без эталона."""

    def test_identical_renders_give_zero_diff(self, romanov_data):
        pdf = render_declaration(romanov_data)
        diff = PdfPixelDiff(pdf, pdf, page_a=0, page_b=0, dpi=100)
        r = diff.compare()
        assert r.diff_ratio == 0.0

    def test_different_pages_give_nonzero_diff(self, romanov_data):
        """Стр. 1 (Титул) ≠ стр. 2 (Р.1.1)."""
        pdf = render_declaration(romanov_data)
        diff = PdfPixelDiff(pdf, pdf, page_a=0, page_b=1, dpi=100)
        r = diff.compare()
        assert r.strong_diff_pixels > 0

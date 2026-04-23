"""
Integration-тесты PdfOverlayFiller — полный pipeline DeclarationData → PDF.

Проверяем:
  - render() не падает на валидных данных (УСН-доходы и УСН-минус)
  - Валидация отсеивает невалидные DTO
  - Выход — валидный 4-страничный A4 PDF
  - Размер больше blank (значит overlay применён)
  - render_declaration() функциональный API работает
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from modules.declaration_filler.declaration_data import (
    DeclarationData,
    TitlePage,
    Section_1_1,
    Section_1_2,
    Section_2_1_1,
    Section_2_2,
    OBJECT_INCOME,
    OBJECT_INCOME_MINUS,
    TP_SIGN_IP_NO_EMPLOYEES,
    LOC_IP_RESIDENCE,
    TAX_PERIOD_YEAR,
)
from modules.declaration_filler.pdf_overlay_filler import (
    PdfOverlayFiller,
    render_declaration,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLANK_2025 = PROJECT_ROOT / "templates" / "knd_1152017" / "blank_2025.pdf"


@pytest.fixture
def romanov_data() -> DeclarationData:
    """
    Данные из эталона ТЕНЗОР — Романов Д.В. УСН-доходы 2025.
    Доход 409517, налог 24571, взносы 24571 → к уплате 0.
    """
    return DeclarationData(
        title=TitlePage(
            inn="330573397709",
            kpp="",
            correction_number=1,
            tax_period_code=TAX_PERIOD_YEAR,
            tax_period_year=2025,
            ifns_code="3300",
            at_location_code=LOC_IP_RESIDENCE,
            taxpayer_name_line1="Романов",
            taxpayer_name_line2="Дмитрий",
            taxpayer_name_line3="Владимирович",
            phone="79157503070",
            pages_count=4,
            signing_date=date(2026, 1, 24),
            object_code=OBJECT_INCOME,
        ),
        section_1_1=Section_1_1(
            oktmo_q1="17701000",
        ),
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


@pytest.fixture
def usn_minus_data() -> DeclarationData:
    """Валидные данные для УСН-доходы-минус-расходы."""
    return DeclarationData(
        title=TitlePage(
            inn="7712345678",
            kpp="771201001",
            correction_number=0,
            tax_period_year=2025,
            ifns_code="7712",
            taxpayer_name_line1="ООО",
            taxpayer_name_line2="Пример",
            signing_date=date(2026, 3, 28),
            object_code=OBJECT_INCOME_MINUS,
        ),
        section_1_2=Section_1_2(
            oktmo_y="45382000",
            tax_year_payable=Decimal("100000"),
        ),
        section_2_2=Section_2_2(
            income_y=Decimal("5000000"),
            expenses_y=Decimal("4333333"),
            tax_base_y=Decimal("666667"),
            tax_rate_y=Decimal("15.0"),
            tax_calc_y=Decimal("100000"),
        ),
    )


# ============================================================
# Smoke-тесты рендера
# ============================================================

@pytest.mark.skipif(not BLANK_2025.exists(), reason="blank_2025.pdf отсутствует")
class TestRenderDeclarationSmoke:
    def test_render_does_not_raise_on_valid(self, romanov_data):
        pdf = render_declaration(romanov_data)
        assert pdf.startswith(b"%PDF")

    def test_output_has_4_pages(self, romanov_data):
        pdf = render_declaration(romanov_data)
        reader = PdfReader(BytesIO(pdf))
        assert len(reader.pages) == 4

    def test_output_all_pages_a4(self, romanov_data):
        pdf = render_declaration(romanov_data)
        reader = PdfReader(BytesIO(pdf))
        for i, page in enumerate(reader.pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            assert 590 < w < 600, f"стр.{i+1}: ширина {w}"
            assert 835 < h < 850, f"стр.{i+1}: высота {h}"

    def test_output_bigger_than_blank(self, romanov_data):
        """Overlay должен реально добавляться — значит размер > blank."""
        blank_size = BLANK_2025.stat().st_size
        pdf = render_declaration(romanov_data)
        assert len(pdf) > blank_size

    def test_render_with_usn_minus(self, usn_minus_data):
        """УСН-минус-расходы тоже рендерится (секции 1.2/2.2 пока не размечены,
        но render должен отработать без исключений)."""
        pdf = render_declaration(usn_minus_data)
        assert pdf.startswith(b"%PDF")
        reader = PdfReader(BytesIO(pdf))
        assert len(reader.pages) == 4


# ============================================================
# Валидация в render()
# ============================================================

class TestRenderValidation:
    def test_invalid_inn_raises(self):
        bad = DeclarationData(
            title=TitlePage(
                inn="123",  # невалидный
                tax_period_year=2025,
                ifns_code="3300",
                object_code=OBJECT_INCOME,
            ),
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        with pytest.raises(ValueError, match="невалидна"):
            render_declaration(bad)

    def test_missing_section_for_object_code_raises(self):
        bad = DeclarationData(
            title=TitlePage(
                inn="330573397709",
                tax_period_year=2025,
                ifns_code="3300",
                object_code=OBJECT_INCOME,  # требует section_1_1 и section_2_1_1
            ),
            # Секции не заданы → validate() вернёт ошибки
        )
        with pytest.raises(ValueError, match="невалидна"):
            render_declaration(bad)


# ============================================================
# Поведение class-based API
# ============================================================

@pytest.mark.skipif(not BLANK_2025.exists(), reason="blank_2025.pdf отсутствует")
class TestPdfOverlayFillerClass:
    def test_init_requires_existing_fields_and_blank(self):
        """Для 2025 оба файла должны существовать."""
        filler = PdfOverlayFiller(tax_period_year=2025)
        assert filler.year == 2025
        assert filler.blank_path.exists()
        assert "pages_def" in filler.fields_map

    def test_year_fallback_to_prev(self):
        """Для 2026 нет файлов → должен fallback на 2025."""
        filler = PdfOverlayFiller(tax_period_year=2026)
        assert filler.blank_path.name == "blank_2025.pdf"

    def test_year_2024_not_yet_supported(self):
        """Для 2024 нет файлов и fallback на 2023 тоже нет → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            PdfOverlayFiller(tax_period_year=2024)

    def test_repeated_renders_deterministic(self, romanov_data):
        """Повторный render тех же данных даёт тот же размер."""
        a = render_declaration(romanov_data)
        b = render_declaration(romanov_data)
        assert abs(len(a) - len(b)) < max(len(a), len(b)) * 0.01

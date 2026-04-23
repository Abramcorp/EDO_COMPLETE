"""
Тесты DeclarationData DTO — типобезопасность, валидация, консистентность
между object_code и секциями.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from modules.declaration_filler.declaration_data import (
    DeclarationData,
    TitlePage,
    Section_1_1,
    Section_1_2,
    Section_2_1_1,
    Section_2_2,
    OBJECT_INCOME,
    OBJECT_INCOME_MINUS,
    TAX_PERIOD_YEAR,
    LOC_IP_RESIDENCE,
    TP_SIGN_IP_NO_EMPLOYEES,
)


# ============================================================
# Fixtures
# ============================================================

def _valid_title(object_code=OBJECT_INCOME) -> TitlePage:
    return TitlePage(
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
        phone="+79157503070",
        pages_count=4,
        signing_date=date(2026, 1, 24),
        object_code=object_code,
    )


def _valid_usn_income_data() -> DeclarationData:
    """Минимальная декларация УСН-доходы ИП без работников."""
    return DeclarationData(
        title=_valid_title(OBJECT_INCOME),
        section_1_1=Section_1_1(
            oktmo_y="17701000",
            tax_year_payable=Decimal("15000"),
        ),
        section_2_1_1=Section_2_1_1(
            taxpayer_sign=TP_SIGN_IP_NO_EMPLOYEES,
            income_y=Decimal("250000"),
            tax_rate_y=Decimal("6.0"),
            tax_calc_y=Decimal("15000"),
        ),
    )


def _valid_usn_minus_data() -> DeclarationData:
    return DeclarationData(
        title=_valid_title(OBJECT_INCOME_MINUS),
        section_1_2=Section_1_2(
            oktmo_y="17701000",
            tax_year_payable=Decimal("10000"),
        ),
        section_2_2=Section_2_2(
            income_y=Decimal("500000"),
            expenses_y=Decimal("433333"),
            tax_base_y=Decimal("66667"),
            tax_rate_y=Decimal("15.0"),
            tax_calc_y=Decimal("10000"),
        ),
    )


# ============================================================
# Базовая валидация
# ============================================================

class TestDeclarationDataValidation:
    def test_valid_usn_income_passes(self):
        data = _valid_usn_income_data()
        errors = data.validate()
        assert errors == [], f"Неожиданные ошибки: {errors}"

    def test_valid_usn_minus_passes(self):
        data = _valid_usn_minus_data()
        errors = data.validate()
        assert errors == [], f"Неожиданные ошибки: {errors}"

    def test_bad_inn_fails(self):
        t = _valid_title()
        t.inn = "123"  # слишком короткий
        data = DeclarationData(
            title=t,
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        errors = data.validate()
        assert any("inn" in e.lower() for e in errors)

    def test_alphanumeric_inn_fails(self):
        t = _valid_title()
        t.inn = "ABCDEFGHIJKL"  # 12 символов но не цифры
        data = DeclarationData(
            title=t,
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        errors = data.validate()
        assert any("inn" in e.lower() for e in errors)

    def test_legal_entity_requires_kpp(self):
        t = _valid_title()
        t.inn = "7700123456"  # 10 цифр = ЮЛ
        t.kpp = ""             # КПП не указан
        data = DeclarationData(
            title=t,
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        errors = data.validate()
        assert any("кпп" in e.lower() or "kpp" in e.lower() for e in errors)

    def test_bad_ifns_code_fails(self):
        t = _valid_title()
        t.ifns_code = "33"  # 2 цифры
        data = DeclarationData(
            title=t,
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        errors = data.validate()
        assert any("ifns" in e.lower() for e in errors)

    def test_out_of_range_year_fails(self):
        t = _valid_title()
        t.tax_period_year = 1999
        data = DeclarationData(
            title=t,
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
        )
        errors = data.validate()
        assert any("year" in e.lower() for e in errors)


class TestObjectCodeConsistency:
    def test_income_requires_sections_1_1_and_2_1_1(self):
        data = DeclarationData(title=_valid_title(OBJECT_INCOME))
        errors = data.validate()
        assert any("section_1_1" in e for e in errors)
        assert any("section_2_1_1" in e for e in errors)

    def test_income_minus_requires_sections_1_2_and_2_2(self):
        data = DeclarationData(title=_valid_title(OBJECT_INCOME_MINUS))
        errors = data.validate()
        assert any("section_1_2" in e for e in errors)
        assert any("section_2_2" in e for e in errors)

    def test_income_rejects_minus_sections(self):
        """Если object_code=1, не должно быть section_1_2 / section_2_2."""
        data = DeclarationData(
            title=_valid_title(OBJECT_INCOME),
            section_1_1=Section_1_1(),
            section_2_1_1=Section_2_1_1(),
            section_1_2=Section_1_2(),  # ошибка
            section_2_2=Section_2_2(),
        )
        errors = data.validate()
        assert any("section_1_2" in e for e in errors)


class TestSections:
    """Смоук — что секции можно создать с дефолтами."""

    def test_section_1_1_defaults(self):
        s = Section_1_1()
        assert s.advance_q1 == Decimal("0")
        assert s.tax_year_payable == Decimal("0")
        assert s.oktmo_q1 == ""

    def test_section_2_1_1_default_rate(self):
        s = Section_2_1_1()
        # Стандартная ставка для УСН-доходы 6%
        assert s.tax_rate_y == Decimal("6.0")
        assert s.taxpayer_sign == TP_SIGN_IP_NO_EMPLOYEES

    def test_section_2_2_default_rate(self):
        s = Section_2_2()
        # Стандартная ставка для УСН-доходы-расходы 15%
        assert s.tax_rate_y == Decimal("15.0")

    def test_section_1_2_has_minimum_tax(self):
        """Минимальный налог — особенность УСН-доходы-расходы."""
        s = Section_1_2()
        assert hasattr(s, "minimum_tax")


class TestRealReference:
    """Данные эталона Романов УСН 2025 (из ADR-003) — проходят валидацию."""

    def test_romanov_tensor_reference(self):
        data = DeclarationData(
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
                phone="+79157503070",
                pages_count=4,
                signing_date=date(2026, 1, 24),
                object_code=OBJECT_INCOME,
            ),
            section_1_1=Section_1_1(
                oktmo_y="17701000",
                tax_year_payable=Decimal("15000"),
            ),
            section_2_1_1=Section_2_1_1(
                taxpayer_sign=TP_SIGN_IP_NO_EMPLOYEES,
                income_y=Decimal("250000"),
                tax_rate_y=Decimal("6.0"),
                tax_calc_y=Decimal("15000"),
            ),
        )
        errors = data.validate()
        assert errors == []

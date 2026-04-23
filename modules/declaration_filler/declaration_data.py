"""
declaration_data.py — единый DTO для всех полей декларации КНД 1152017.

Центральная структура данных (ADR-004). Служит мостом между:
  * input-источниками (xls_reader_tensor/kontur, tax_engine.calculate())
  * рендером (pdf_overlay_filler.PdfOverlayFiller.render())

Структура отражает разделы формы КНД 1152017:
  - TitlePage         — стр. 1, титульный лист
  - Section_1_1       — стр. 2, Р.1.1 (УСН-доходы, суммы к уплате)
  - Section_1_2       — стр. 2, Р.1.2 (УСН-доходы-расходы, суммы к уплате)
  - Section_2_1_1     — стр. 3-4, Р.2.1.1 (расчёт УСН-доходы)
  - Section_2_1_2     — Р.2.1.2 (торговый сбор, только Москва)
  - Section_2_2       — Р.2.2 (расчёт УСН-доходы-расходы)
  - Section_3         — Р.3 (целевые поступления)

Минимальная декларация УСН-доходы для ИП без работников:
  TitlePage + Section_1_1 + Section_2_1_1 — 4 страницы.

Минимальная декларация УСН-доходы-расходы:
  TitlePage + Section_1_2 + Section_2_2 — 4 страницы.

Выбор режима определяется полем DeclarationData.object_code:
  1 — доходы
  2 — доходы, уменьшенные на величину расходов
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Optional


# ============================================================
# Справочники (enum-как константы)
# ============================================================

# Коды налогового периода (tax_period_code)
TAX_PERIOD_Q1 = "21"
TAX_PERIOD_H1 = "31"
TAX_PERIOD_9M = "33"
TAX_PERIOD_YEAR = "34"
TAX_PERIOD_REORG = "50"  # последний перед реорганизацией
TAX_PERIOD_CLOSE = "95"  # при прекращении деятельности

# Коды "по месту нахождения (учёта)" (at_location_code)
LOC_IP_RESIDENCE = "120"     # по месту жительства ИП
LOC_ORG_ADDRESS = "210"      # по месту нахождения организации
LOC_ORG_LARGE = "215"        # по месту нахождения крупнейшего налогоплательщика

# Признак налогоплательщика (taxpayer_sign) для Р.2.1.1
TP_SIGN_WITH_EMPLOYEES = 1   # производящий выплаты физлицам
TP_SIGN_IP_NO_EMPLOYEES = 2  # ИП без работников
TP_SIGN_IP_TAX_HOLIDAY = 3   # ИП на налоговых каникулах

# Объект налогообложения (object_code)
OBJECT_INCOME = 1        # УСН-доходы
OBJECT_INCOME_MINUS = 2  # УСН-доходы минус расходы

# Тип подписанта (signer_type)
SIGNER_TAXPAYER = 1      # сам налогоплательщик
SIGNER_REPRESENTATIVE = 2  # представитель


# ============================================================
# Секции формы
# ============================================================

@dataclass
class TitlePage:
    """Стр. 1 — Титульный лист. Обязательна всегда."""

    # Идентификация
    inn: str                            # 10 или 12 цифр (ЮЛ=10, ИП/физлицо=12)
    kpp: str = ""                       # 9 цифр для ЮЛ, пусто для ИП
    page_number: str = "001"            # трёхзначный номер страницы

    # Период и тип декларации
    correction_number: int = 0          # 0 = первичная, 1,2,... = уточнённые
    tax_period_code: str = TAX_PERIOD_YEAR  # "34" для годовой
    tax_period_year: int = 0            # YYYY

    # Налоговый орган и место учёта
    ifns_code: str = ""                 # 4 цифры
    at_location_code: str = LOC_IP_RESIDENCE  # "120" / "210" / "215"

    # ФИО / наименование — форма позволяет 4 строки (каждая в своей линии бланка)
    taxpayer_name_line1: str = ""       # Для ЮЛ: полное наименование ч.1. Для ИП: Фамилия
    taxpayer_name_line2: str = ""       # ЮЛ ч.2 / Имя
    taxpayer_name_line3: str = ""       # ЮЛ ч.3 / Отчество
    taxpayer_name_line4: str = ""       # ЮЛ ч.4 / пусто

    # Реорганизация (обычно пусто)
    reorganization_form_code: int = 0
    reorganized_inn: str = ""
    reorganized_kpp: str = ""

    # Контакт
    phone: str = ""                     # номер контактного телефона

    # Количество страниц
    pages_count: int = 0                # автоматически по количеству разделов
    appendices_pages: int = 0           # листы приложения подтверждающих документов

    # Подпись
    signer_type: int = SIGNER_TAXPAYER
    signer_name_line1: str = ""         # для представителя / руководителя
    signer_name_line2: str = ""
    signer_name_line3: str = ""
    signing_date: Optional[date] = None

    # Для представителя
    representative_document: str = ""   # "Доверенность № ... от ..."

    # Объект налогообложения (1 или 2) — дублирован на титуле
    object_code: Literal[1, 2] = OBJECT_INCOME


@dataclass
class Section_1_1:
    """Р.1.1 — УСН-доходы. Сумма налога к уплате/уменьшению по кварталам."""

    # Q1 (по сроку 28.04)
    oktmo_q1: str = ""                  # строка 010 — ОКТМО по месту жительства ИП
    advance_q1: Decimal = Decimal("0")  # строка 020

    # Q2 / H1 (по сроку 28.07)
    oktmo_h1: str = ""                  # строка 030 (только если ОКТМО сменился)
    advance_h1: Decimal = Decimal("0")  # строка 040
    advance_h1_reduction: Decimal = Decimal("0")  # строка 050

    # Q3 / 9M (по сроку 28.10)
    oktmo_9m: str = ""                  # строка 060
    advance_9m: Decimal = Decimal("0")  # строка 070
    advance_9m_reduction: Decimal = Decimal("0")  # строка 080

    # Годовой итог (по сроку 28.03 следующего года)
    oktmo_y: str = ""                   # строка 090
    tax_year_payable: Decimal = Decimal("0")     # строка 100
    tax_year_reduction: Decimal = Decimal("0")   # строка 110
    tax_year_payable_stp: Decimal = Decimal("0") # строка 101 (сумма уплаченная по ПСН, засчитываемая)


@dataclass
class Section_2_1_1:
    """Р.2.1.1 — расчёт налога по УСН-доходы. Занимает стр. 3-4 формы."""

    # Признак (стр. 102)
    taxpayer_sign: int = TP_SIGN_IP_NO_EMPLOYEES

    # Доходы (нарастающим итогом, в рублях) — строки 110, 111, 112, 113
    income_q1: Decimal = Decimal("0")
    income_h1: Decimal = Decimal("0")
    income_9m: Decimal = Decimal("0")
    income_y: Decimal = Decimal("0")

    # Ставка налога (в процентах) — строки 120, 121, 122, 123
    tax_rate_q1: Decimal = Decimal("6.0")
    tax_rate_h1: Decimal = Decimal("6.0")
    tax_rate_9m: Decimal = Decimal("6.0")
    tax_rate_y: Decimal = Decimal("6.0")

    # Обоснование пониженной ставки (строка 124) — код пониженной ставки если применяется
    reduced_rate_basis: str = ""

    # Исчисленная сумма (строки 130, 131, 132, 133)
    tax_calc_q1: Decimal = Decimal("0")
    tax_calc_h1: Decimal = Decimal("0")
    tax_calc_9m: Decimal = Decimal("0")
    tax_calc_y: Decimal = Decimal("0")

    # Страховые взносы (строки 140, 141, 142, 143) — уменьшают налог
    insurance_q1: Decimal = Decimal("0")
    insurance_h1: Decimal = Decimal("0")
    insurance_9m: Decimal = Decimal("0")
    insurance_y: Decimal = Decimal("0")


@dataclass
class Section_1_2:
    """Р.1.2 — УСН-доходы-минус-расходы. Аналогичная структура Section_1_1 + минимальный налог."""
    oktmo_q1: str = ""
    advance_q1: Decimal = Decimal("0")
    oktmo_h1: str = ""
    advance_h1: Decimal = Decimal("0")
    advance_h1_reduction: Decimal = Decimal("0")
    oktmo_9m: str = ""
    advance_9m: Decimal = Decimal("0")
    advance_9m_reduction: Decimal = Decimal("0")
    oktmo_y: str = ""
    tax_year_payable: Decimal = Decimal("0")
    tax_year_reduction: Decimal = Decimal("0")
    # Особенность объекта "доходы-расходы" — минимальный налог 1% от доходов
    minimum_tax: Decimal = Decimal("0")


@dataclass
class Section_2_2:
    """Р.2.2 — расчёт по УСН-доходы-расходы."""
    income_q1: Decimal = Decimal("0")
    income_h1: Decimal = Decimal("0")
    income_9m: Decimal = Decimal("0")
    income_y: Decimal = Decimal("0")

    expenses_q1: Decimal = Decimal("0")
    expenses_h1: Decimal = Decimal("0")
    expenses_9m: Decimal = Decimal("0")
    expenses_y: Decimal = Decimal("0")

    # Убыток прошлых лет (уменьшает базу)
    prior_year_loss: Decimal = Decimal("0")

    # Налоговая база — строки 240-243
    tax_base_q1: Decimal = Decimal("0")
    tax_base_h1: Decimal = Decimal("0")
    tax_base_9m: Decimal = Decimal("0")
    tax_base_y: Decimal = Decimal("0")

    # Ставки (обычно 15%, но регионы могут снижать до 5%) — строки 260-263
    tax_rate_q1: Decimal = Decimal("15.0")
    tax_rate_h1: Decimal = Decimal("15.0")
    tax_rate_9m: Decimal = Decimal("15.0")
    tax_rate_y: Decimal = Decimal("15.0")

    reduced_rate_basis: str = ""

    # Исчисленный налог (строки 270-273)
    tax_calc_q1: Decimal = Decimal("0")
    tax_calc_h1: Decimal = Decimal("0")
    tax_calc_9m: Decimal = Decimal("0")
    tax_calc_y: Decimal = Decimal("0")

    # Минимальный налог (1% от доходов, строка 280)
    minimum_tax: Decimal = Decimal("0")


# ============================================================
# Основной DTO
# ============================================================

@dataclass
class DeclarationData:
    """
    Полный набор данных для рендера декларации КНД 1152017.

    Поля section_* опциональны — заполняется только то, что нужно по
    объекту налогообложения:
      object_code=1 (доходы)        → section_1_1, section_2_1_1
      object_code=2 (доходы-расходы) → section_1_2, section_2_2
    """
    title: TitlePage

    # Режим УСН-доходы
    section_1_1: Optional[Section_1_1] = None
    section_2_1_1: Optional[Section_2_1_1] = None

    # Режим УСН-доходы-расходы
    section_1_2: Optional[Section_1_2] = None
    section_2_2: Optional[Section_2_2] = None

    # Р.3 / Р.2.1.2 / Р.4 — реализуем по мере необходимости
    # section_2_1_2: Optional[Section_2_1_2] = None  # торговый сбор
    # section_3:     Optional[Section_3]     = None  # целевые поступления
    # section_4:     Optional[Section_4]     = None  # новая форма 2024+

    def validate(self) -> list[str]:
        """
        Базовая проверка целостности — возвращает список ошибок (пустой если ок).
        """
        errors: list[str] = []
        if not self.title:
            errors.append("title отсутствует")
            return errors

        # ИНН: 10 или 12 цифр
        if not self.title.inn.isdigit() or len(self.title.inn) not in (10, 12):
            errors.append(f"title.inn: {self.title.inn!r} должен быть 10 или 12 цифр")

        # КПП для ЮЛ обязателен
        if len(self.title.inn) == 10 and (not self.title.kpp.isdigit() or len(self.title.kpp) != 9):
            errors.append("title.kpp: для ЮЛ (ИНН=10) требуется 9-значный КПП")

        # ИФНС
        if not self.title.ifns_code.isdigit() or len(self.title.ifns_code) != 4:
            errors.append(f"title.ifns_code: {self.title.ifns_code!r} должен быть 4 цифры")

        # Период
        if self.title.tax_period_year < 2020 or self.title.tax_period_year > 2030:
            errors.append(f"title.tax_period_year: {self.title.tax_period_year} вне разумного диапазона")

        # Консистентность секций и object_code
        if self.title.object_code == OBJECT_INCOME:
            if self.section_1_1 is None:
                errors.append("object_code=1 (доходы) требует section_1_1")
            if self.section_2_1_1 is None:
                errors.append("object_code=1 (доходы) требует section_2_1_1")
            if self.section_1_2 is not None or self.section_2_2 is not None:
                errors.append("object_code=1 не должен содержать section_1_2 или section_2_2")
        elif self.title.object_code == OBJECT_INCOME_MINUS:
            if self.section_1_2 is None:
                errors.append("object_code=2 (доходы-расходы) требует section_1_2")
            if self.section_2_2 is None:
                errors.append("object_code=2 (доходы-расходы) требует section_2_2")
            if self.section_1_1 is not None or self.section_2_1_1 is not None:
                errors.append("object_code=2 не должен содержать section_1_1 или section_2_1_1")

        return errors


__all__ = [
    "DeclarationData",
    "TitlePage",
    "Section_1_1",
    "Section_1_2",
    "Section_2_1_1",
    "Section_2_2",
    # Константы
    "TAX_PERIOD_YEAR", "TAX_PERIOD_Q1", "TAX_PERIOD_H1", "TAX_PERIOD_9M",
    "LOC_IP_RESIDENCE", "LOC_ORG_ADDRESS",
    "TP_SIGN_WITH_EMPLOYEES", "TP_SIGN_IP_NO_EMPLOYEES", "TP_SIGN_IP_TAX_HOLIDAY",
    "OBJECT_INCOME", "OBJECT_INCOME_MINUS",
    "SIGNER_TAXPAYER", "SIGNER_REPRESENTATIVE",
]

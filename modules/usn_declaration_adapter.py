"""
EDO_COMPLETE adapter: bridges declaration_filler.TaxResult -> fill_declaration().

tax_engine.get_declaration_data() (modules.declaration_filler) выдаёт decl_data
в одном формате, а excel_declaration._fill_2024 / _fill_2025 (копия из
usn-declaration) ждут немного другой. Этот модуль перепаковывает ключи и
вызывает fill_declaration -> convert_xlsx_to_pdf, возвращая PDF bytes.

Копия modules/usn_declaration/ НЕ модифицируется этим адаптером.
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from modules.usn_declaration.services.excel_declaration import (
    fill_declaration,
    get_template_for_year,
)
from modules.usn_declaration.services.xlsx_to_pdf import convert_xlsx_to_pdf


# КБК УСН "Доходы" 6 % (используется в шаблоне 2025)
_KBK_USN_INCOME = "18210501011011000110"


def _to_int(v: Any) -> int:
    """Decimal/str/int/float -> int (КНД 1152017 хранит целые рубли)."""
    if v is None:
        return 0
    return int(Decimal(str(v)))


def _build_project_data(taxpayer, tax_period_year: int) -> dict[str, Any]:
    return {
        "inn": taxpayer.inn,
        "tax_period_year": tax_period_year,
        "ifns_code": taxpayer.ifns_code,
        "oktmo": taxpayer.oktmo,
        "fio": taxpayer.fio,
        "phone": "",
        "kpp": "",
    }


def _build_decl_data_2024(*, tax_result, signing_date: datetime, correction_number: int) -> dict[str, Any]:
    """Перепаковка под _fill_2024 (форма ФНС от 02.10.2024)."""
    src211 = tax_result.decl_data.get("section_2_1_1", {})
    src11 = tax_result.decl_data.get("section_1_1", {})

    # _fill_2024 читает sec211["line_101"] и пишет в ячейку Excel-line_102
    # (см. комментарий "old key was line_101"). Это признак налогоплательщика 1/2.
    # У tax_engine это в line_102. Переносим.
    s211 = {
        "line_101": str(src211.get("line_102", 2)),
        "line_110": _to_int(src211.get("line_110", 0)),
        "line_111": _to_int(src211.get("line_111", 0)),
        "line_112": _to_int(src211.get("line_112", 0)),
        "line_113": _to_int(src211.get("line_113", 0)),
        # tax_engine кладёт rate*10 (60); _fill_2024 ждёт float (6.0)
        "line_120": float(Decimal(str(src211.get("line_120", 60))) / 10),
        "line_121": float(Decimal(str(src211.get("line_121", 60))) / 10),
        "line_122": float(Decimal(str(src211.get("line_122", 60))) / 10),
        "line_123": float(Decimal(str(src211.get("line_123", 60))) / 10),
        "line_130": _to_int(src211.get("line_130", 0)),
        "line_131": _to_int(src211.get("line_131", 0)),
        "line_132": _to_int(src211.get("line_132", 0)),
        "line_133": _to_int(src211.get("line_133", 0)),
        "line_140": _to_int(src211.get("line_140", 0)),
        "line_141": _to_int(src211.get("line_141", 0)),
        "line_142": _to_int(src211.get("line_142", 0)),
        "line_143": _to_int(src211.get("line_143", 0)),
    }

    # ОКТМО _fill_2024 берёт из project_data, не из section_1_1.
    s11 = {
        "line_020": _to_int(src11.get("line_020", 0)),
        "line_040": _to_int(src11.get("line_040", 0)),
        "line_050": _to_int(src11.get("line_050", 0)),
        "line_070": _to_int(src11.get("line_070", 0)),
        "line_080": _to_int(src11.get("line_080", 0)),
        "line_100": _to_int(src11.get("line_100", 0)),
        "line_110": _to_int(src11.get("line_110", 0)),
        "line_101": 0,  # Сумма патента к зачёту - не применимо для чистой УСН
    }

    return {
        "date_presented": signing_date.strftime("%d.%m.%Y"),
        "period_code": "34",
        "correction_number": str(correction_number).zfill(3) if correction_number else "0",
        "section_1_1": s11,
        "section_2_1_1": s211,
    }


def _build_decl_data_2025(*, tax_result, signing_date: datetime, correction_number: int) -> dict[str, Any]:
    """Перепаковка под _fill_2025 (форма с листами стр.1/стр.2_Разд.1/стр.3_Разд.2).

    section_1 / section_2 не формируются tax_engine.get_declaration_data() —
    собираем по правилу из usn-declaration/app/routers/wizard.py:generate_declaration
    (строки ~497..520 на момент копии).
    """
    src211 = tax_result.decl_data.get("section_2_1_1", {})
    src11 = tax_result.decl_data.get("section_1_1", {})
    summary = tax_result.decl_data.get("summary", {})
    settings = tax_result.decl_data.get("settings", {})

    rate = float(Decimal(str(settings.get("tax_rate", "6.0"))))
    year_income = _to_int(src211.get("line_113", 0))
    year_computed_tax = _to_int(src211.get("line_133", 0))
    year_reduction = _to_int(src211.get("line_143", 0))
    year_to_pay = _to_int(summary.get("final_tax_due", 0))
    year_to_reduce = _to_int(summary.get("overpayment", 0))

    section_1 = {
        "kbk": _KBK_USN_INCOME,
        "line_030": _to_int(src11.get("line_020", 0)),
        "line_040": _to_int(src11.get("line_040", 0)),
        "line_050": _to_int(src11.get("line_070", 0)),
        "line_060": year_to_pay,
        "line_070": year_to_reduce,
    }

    section_2 = {
        "rate":     rate,
        "line_210": year_income,
        "line_240": year_income,  # для УСН "Доходы": база = доход
        "line_260": year_computed_tax,
        "line_280": year_reduction,
    }

    return {
        "date_presented": signing_date.strftime("%d.%m.%Y"),
        "period_code": "34",
        "correction_number": str(correction_number).zfill(3) if correction_number else "0",
        "section_1": section_1,
        "section_2": section_2,
    }


def _build_decl_data_legacy(*, tax_result, signing_date: datetime, correction_number: int) -> dict[str, Any]:
    """Перепаковка под _fill_old (legacy форма для tax_period_year не в TEMPLATES).
    По формату совпадает с 2024 (та же семантика line_101/line_120 как ждёт _fill_old).
    """
    return _build_decl_data_2024(
        tax_result=tax_result,
        signing_date=signing_date,
        correction_number=correction_number,
    )


def render_declaration_pdf_via_usn(
    *,
    taxpayer,
    tax_period_year: int,
    tax_result,
    signing_date: datetime,
    correction_number: int = 0,
) -> bytes:
    """Главная точка входа адаптера.

    1. Выбирает шаблон по году через get_template_for_year(...).
    2. Перепаковывает tax_result.decl_data в формат fill_declaration.
    3. Заполняет xlsx, конвертирует в PDF через soffice.
    4. Возвращает PDF bytes.

    Требует LibreOffice (soffice) на проде/в Docker для xlsx->PDF.
    """
    template = get_template_for_year(tax_period_year)
    if not template.exists():
        raise FileNotFoundError(f"Шаблон декларации не найден: {template}")

    project_data = _build_project_data(taxpayer, tax_period_year)

    name = template.name
    if "template_2024" in name:
        decl_data = _build_decl_data_2024(
            tax_result=tax_result, signing_date=signing_date, correction_number=correction_number,
        )
    elif "template_2025" in name:
        decl_data = _build_decl_data_2025(
            tax_result=tax_result, signing_date=signing_date, correction_number=correction_number,
        )
    else:
        decl_data = _build_decl_data_legacy(
            tax_result=tax_result, signing_date=signing_date, correction_number=correction_number,
        )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out_xlsx = tmp / "declaration.xlsx"
        out_pdf = tmp / "declaration.pdf"

        fill_declaration(template, out_xlsx, project_data, decl_data)
        convert_xlsx_to_pdf(out_xlsx, out_pdf)

        return out_pdf.read_bytes()

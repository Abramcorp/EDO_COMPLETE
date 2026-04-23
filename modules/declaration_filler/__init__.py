"""
Adapter для modules/declaration_filler/*.

Оригинальные сервисы из usn-declaration завязаны на БД/файлы/project_id.
Этот файл предоставляет stateless фасад под контракт core/pipeline.py.

ВАЖНО: файлы parser.py, classifier.py, tax_engine.py, declaration_generator.py,
ofd_parser.py, contributions_calculator.py должны быть скопированы сюда
через scripts/sync_sources.sh ДО импорта этого модуля.

Dictionaries для classifier должны лежать в modules/declaration_filler/dictionaries/.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType as _M
from typing import Any


# ============================================================
# DTOs (используются в core/pipeline.py и тестах)
# ============================================================

@dataclass
class BankOp:
    operation_date: date
    amount: Decimal
    direction: str  # "income" | "expense"
    purpose: str = ""
    counterparty: str | None = None
    counterparty_inn: str | None = None


@dataclass
class Statement:
    owner_inn: str | None
    owner_name: str | None
    period_start: date | None
    period_end: date | None
    operations: list[BankOp]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ClassifiedOps:
    """Квартальная разбивка доходов после классификации."""
    q1: Decimal = Decimal("0")
    q2: Decimal = Decimal("0")
    q3: Decimal = Decimal("0")
    q4: Decimal = Decimal("0")

    def as_dict(self) -> dict[str, Decimal]:
        return {"q1": self.q1, "q2": self.q2, "q3": self.q3, "q4": self.q4}


@dataclass
class TaxResult:
    """Результат TaxEngine, готовый к передаче в рендерер."""
    decl_data: dict[str, Any]
    project_data: dict[str, Any]


# ============================================================
# Lazy-импорты оригинальных модулей — только при реальном вызове.
# Это нужно, чтобы приложение запускалось до sync_sources.sh
# ============================================================

def _src_parser():
    from . import parser as _p  # type: ignore[no-redef]
    return _p


def _src_ofd():
    from . import ofd_parser as _p  # type: ignore[no-redef]
    return _p


def _src_classifier():
    from . import classifier as _p  # type: ignore[no-redef]
    return _p


def _src_tax():
    from . import tax_engine as _p  # type: ignore[no-redef]
    return _p


def _src_contrib():
    from . import contributions_calculator as _p  # type: ignore[no-redef]
    return _p


# NB: declaration_generator.py из usn-declaration исключён по ADR-002
# (рендер «визуально близкий», не pixel-perfect). Вместо него —
# templates/knd_1152017/blank_YYYY.pdf + PdfOverlayFiller.


# ============================================================
# parser.parse_1c_statement_bytes
# ============================================================

def _parse_1c_statement_bytes(data: bytes) -> Statement:
    """Байты .txt выписки 1С → DTO Statement."""
    src = _src_parser()
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        raw = src.BankStatementParser().parse(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    ops = [
        BankOp(
            operation_date=op["operation_date"],
            amount=op["amount"],
            direction=op["direction"],
            purpose=op.get("purpose") or "",
            counterparty=op.get("counterparty"),
            counterparty_inn=op.get("counterparty_inn"),
        )
        for op in raw.get("operations", [])
    ]
    return Statement(
        owner_inn=raw.get("owner_inn"),
        owner_name=raw.get("owner_name"),
        period_start=raw.get("period_start"),
        period_end=raw.get("period_end"),
        operations=ops,
        warnings=raw.get("warnings") or [],
    )


# ============================================================
# ofd_parser.parse_ofd_bytes
# ============================================================

def _parse_ofd_bytes(data: bytes) -> list[dict]:
    """Байты .xlsx с чеками ОФД → список чеков (dict)."""
    src = _src_ofd()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        raw = src.parse_ofd_file(tmp_path)
        return raw.get("receipts", [])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ============================================================
# classifier.classify_operations
# ============================================================

def _make_stateless_classifier():
    """Возвращает инстанс classifier, не требующий БД."""
    src = _src_classifier()

    class _Stateless(src.OperationClassifier):
        def __init__(self):
            # НЕ вызываем super().__init__ — он лезет в БД
            self.project_id = 0
            self.db_session = None
            self.income_markers = self._load_dictionary("income_markers.json")
            self.exclude_markers = self._load_dictionary("exclude_markers.json")
            self.custom_rules = {
                "keyword_income": [],
                "keyword_exclude": [],
                "counterparty_income": [],
                "counterparty_exclude": [],
            }

        def _load_custom_rules(self):
            return self.custom_rules

    return _Stateless()


def _classify_operations(stmt: Statement) -> ClassifiedOps:
    """Агрегирует доходы по кварталам после классификации."""
    clf = _make_stateless_classifier()
    ops_dicts = [
        {
            "operation_date": op.operation_date,
            "amount": op.amount,
            "direction": op.direction,
            "purpose": op.purpose,
            "counterparty": op.counterparty,
            "counterparty_inn": op.counterparty_inn,
        }
        for op in stmt.operations
    ]
    classified = clf.classify_batch(ops_dicts)

    result = ClassifiedOps()
    for op, cls in zip(stmt.operations, classified, strict=True):
        if cls.get("classification") != "income" or op.direction != "income":
            continue
        q = (op.operation_date.month - 1) // 3 + 1
        setattr(result, f"q{q}", getattr(result, f"q{q}") + op.amount)
    return result


# ============================================================
# tax_engine.calculate
# ============================================================

def _calculate_tax(
    *,
    classified: ClassifiedOps,
    ofd_receipts: list[dict],
    contributions,          # pydantic ContributionsInfo
    personnel,              # pydantic PersonnelInfo
    tax_period_year: int,
) -> TaxResult:
    """
    TaxEngine + compute_total_contributions → готовый decl_data для generate_pdf.
    """
    tax_src = _src_tax()
    contrib_src = _src_contrib()

    # ОФД cash добавляем к доходам. Упрощение: вся наличка в Q4.
    # TODO: распределять по датам чеков (r["receipt_date"]).
    ofd_cash_total = Decimal("0")
    for r in ofd_receipts:
        if r.get("payment_type") == "cash" and r.get("operation_type") != "refund":
            ofd_cash_total += Decimal(str(r.get("amount", 0)))

    income = classified.as_dict()
    if ofd_cash_total:
        income["q4"] = income["q4"] + ofd_cash_total

    year_income = sum(income.values(), start=Decimal("0"))

    # Автоматический расчёт взносов
    contrib_computed = contrib_src.compute_total_contributions(
        year=tax_period_year,
        year_income=float(year_income),
        has_employees=bool(personnel.has_employees),
        avg_salary=float(personnel.avg_salary or 0),
        num_employees=int(personnel.num_employees or 0),
    )

    # Если пользователь явно указал кумулятивные суммы — используем их,
    # иначе берём авто-расчёт.
    user_cum = {
        "q1": float(contributions.q1 or 0),
        "half_year": float(contributions.half_year or 0),
        "nine_months": float(contributions.nine_months or 0),
        "year": float(contributions.year or 0),
    }
    user_overrides = any(v > 0 for v in user_cum.values())

    contrib_for_engine = {
        "mode": "detailed",
        "cumulative": user_cum if user_overrides else contrib_computed["total_cumulative"],
    }

    project_settings = {
        "tax_rate": "6.0",
        "has_employees": bool(personnel.has_employees),
        "employee_start_quarter": personnel.employee_start_quarter,
        "uses_ens": True,
        "year": tax_period_year,
        "contribution_input_mode": "detailed",
    }

    engine = tax_src.TaxEngine(project_settings)
    calc = engine.calculate(income_data=income, contributions=contrib_for_engine)
    decl_data = engine.get_declaration_data(calc, project_settings)

    return TaxResult(decl_data=decl_data, project_data=project_settings)


tax_engine_calculate = _calculate_tax


# ============================================================
# render_declaration_pdf — PIXEL-PERFECT через PDF-подложку ФНС
# См. ADR-002-pixel-perfect-rendering.md
# ============================================================

def _render_declaration_pdf(
    *,
    taxpayer,              # pydantic TaxpayerInfo
    tax_period_year: int,
    tax_result: TaxResult,
) -> bytes:
    """
    Pixel-perfect рендер PDF декларации:
      1. Грузим официальный бланк ФНС templates/knd_1152017/blank_YYYY.pdf
      2. Генерируем overlay-слой (reportlab canvas) с текстом в координатах
         из templates/knd_1152017/fields_YYYY.json
      3. Merge overlay на подложку через pypdf (zero-loss)
      4. Возвращаем bytes

    РЕАЛИЗАЦИЯ в modules.declaration_filler.pdf_overlay_filler — отдельный файл,
    т.к. логика нетривиальная (разметка fields.json + тесты pixel-diff).
    Создаётся в Фазе 0a после разметки координат.
    """
    from .pdf_overlay_filler import PdfOverlayFiller
    filler = PdfOverlayFiller(tax_period_year=tax_period_year)
    return filler.render(
        taxpayer=taxpayer,
        tax_result=tax_result,
    )


render_declaration_pdf = _render_declaration_pdf


# ============================================================
# Public API — плоские функции, чтобы не конфликтовать с
# submodule-файлами (parser.py, classifier.py и т.д.), которые
# sync_sources.sh положит в эту папку.
# ============================================================
__all__ = [
    "Statement", "BankOp", "ClassifiedOps", "TaxResult",
    "parse_1c_statement_bytes",
    "parse_ofd_bytes",
    "classify_operations",
    "tax_engine_calculate",
    "render_declaration_pdf",
]


# Глобальные символы, по которым импортирует core/pipeline.py
parse_1c_statement_bytes = _parse_1c_statement_bytes
parse_ofd_bytes = _parse_ofd_bytes
classify_operations = _classify_operations

"""
POST /api/contributions/preview — расчёт страховых взносов автоматически.

Используется UI-wizard'ом для кнопки "Рассчитать автоматически" на шаге 3.
Не требует файла выписки — достаточно указать годовой доход + данные
о работниках (если есть).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.models import ContributionsPreviewRequest, ContributionsPreviewResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


@router.post(
    "/preview",
    response_model=ContributionsPreviewResponse,
    summary="Рассчитать страховые взносы ИП автоматически (для UI)",
)
def preview_contributions(req: ContributionsPreviewRequest) -> ContributionsPreviewResponse:
    """
    Возвращает кумулятивные суммы страховых взносов по периодам декларации,
    а также разбивку (ИП фикс + 1% + за работников).

    Формула в modules.declaration_filler.contributions_calculator.
    """
    try:
        from modules.declaration_filler.contributions_calculator import (
            compute_total_contributions,
        )
    except ImportError as e:
        raise HTTPException(500, f"Не удалось загрузить калькулятор взносов: {e}")

    try:
        result = compute_total_contributions(
            year=req.year,
            year_income=float(req.annual_income),
            has_employees=bool(req.has_employees),
            avg_salary=float(req.avg_salary or 0),
            num_employees=int(req.num_employees or 0),
        )
    except Exception as e:
        log.exception("Ошибка расчёта взносов")
        raise HTTPException(500, f"Ошибка расчёта: {e}")

    cum = result.get("total_cumulative", {})
    return ContributionsPreviewResponse(
        ip_fixed=int(result.get("ip_fixed", 0)),
        ip_1pct=int(result.get("ip_1pct", 0)),
        employee_total=int(result.get("employee_total", 0)),
        q1=int(cum.get("q1", 0)),
        half_year=int(cum.get("half_year", 0)),
        nine_months=int(cum.get("nine_months", 0)),
        year=int(cum.get("year", 0)),
    )

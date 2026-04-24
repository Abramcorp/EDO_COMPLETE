"""
POST /api/complete/create-declaration

Принимает multipart: statement (txt), ofd (xlsx, optional), meta (JSON).
Создаёт job в БД, запускает pipeline в фоне, возвращает job_id.
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import SessionLocal, get_session
from api.jobs import JobStore
from api.models import DeclarationRequest, ErrorInfo, JobAccepted
from core.errors import InputValidationError, PipelineError
from core.pipeline import PipelineInputs, run_pipeline
from core.progress import ProgressTracker

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/complete", tags=["complete"])


# ============================================================
# Limits (из env)
# ============================================================
MAX_STATEMENT_BYTES = int(os.environ.get("MAX_STATEMENT_SIZE_MB", "10")) * 1024 * 1024
MAX_OFD_BYTES = int(os.environ.get("MAX_OFD_SIZE_MB", "5")) * 1024 * 1024


# ============================================================
# Endpoint
# ============================================================

@router.post(
    "/create-declaration",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Создать декларацию УСН 6% с штампами ЭДО",
)
async def create_declaration(
    background_tasks: BackgroundTasks,
    statement: UploadFile = File(..., description="1С-выписка .txt"),
    meta: str = Form(..., description="JSON с DeclarationRequest"),
    ofd: UploadFile | None = File(None, description="Чеки ОФД .xlsx (опц.)"),
    session: AsyncSession = Depends(get_session),
) -> JobAccepted:
    # --- Валидация входов ---
    if not statement.filename or not statement.filename.lower().endswith(".txt"):
        raise HTTPException(400, "statement должен быть .txt файлом (формат 1С)")

    statement_bytes = await statement.read()
    if len(statement_bytes) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, f"Выписка больше {MAX_STATEMENT_BYTES // 1024 // 1024} МБ")
    if len(statement_bytes) == 0:
        raise HTTPException(400, "Пустой файл выписки")

    ofd_bytes: bytes | None = None
    if ofd is not None and ofd.filename:
        if not ofd.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(400, "ofd должен быть .xlsx или .xls")
        ofd_bytes = await ofd.read()
        if len(ofd_bytes) > MAX_OFD_BYTES:
            raise HTTPException(413, f"ОФД больше {MAX_OFD_BYTES // 1024 // 1024} МБ")
        if len(ofd_bytes) == 0:
            ofd_bytes = None  # пустой файл = не передан

    try:
        meta_dict = json.loads(meta)
        request = DeclarationRequest.model_validate(meta_dict)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(422, f"Невалидный meta: {e}")

    # --- Создание job ---
    store = JobStore(session)
    job_id = await store.create(
        input_meta={
            "inn": request.taxpayer.inn,
            "tax_period_year": request.tax_period_year,
            "has_ofd": ofd_bytes is not None,
            "stamps_enabled": request.stamps.enabled,
            "operator": request.stamps.operator.value if request.stamps.enabled else None,
        }
    )

    # --- Запуск pipeline в фоне ---
    inputs = PipelineInputs(
        statement_bytes=statement_bytes,
        ofd_bytes=ofd_bytes,
        request=request,
    )
    background_tasks.add_task(_run_job, job_id, inputs)

    return JobAccepted(
        job_id=job_id,
        status_url=f"/api/jobs/{job_id}",
        result_url=f"/api/jobs/{job_id}/result",
    )


# ============================================================
# Background task
# ============================================================

async def _run_job(job_id: UUID, inputs: PipelineInputs) -> None:
    """
    Выполняется в фоне после возврата 202.
    Открывает СВОЮ сессию БД (нельзя переиспользовать request-session — она уже закрыта).
    """
    async with SessionLocal() as session:
        store = JobStore(session)

        # Прогресс-колбэк с собственной короткой сессией (чтобы не блокировать основную)
        async def _progress(stage, pct):
            async with SessionLocal() as s2:
                await JobStore(s2).update_progress(job_id, stage, pct)

        tracker = ProgressTracker(_progress)

        try:
            await store.mark_running(job_id)
            pdf_bytes, filename = await run_pipeline(inputs, tracker)
            await store.mark_complete(job_id, pdf_bytes, filename)
            log.info("Job %s completed successfully", job_id)
        except PipelineError as e:
            log.warning("Job %s failed at %s: %s", job_id, e.stage.value, e.message)
            if e.cause:
                log.debug("Cause:\n%s", "".join(traceback.format_exception(e.cause)))
            await store.mark_failed(
                job_id,
                ErrorInfo(code=e.code, message=e.message, stage=e.stage),
            )
        except Exception as e:
            log.exception("Job %s crashed with unexpected error", job_id)
            await store.mark_failed(
                job_id,
                ErrorInfo(code="INTERNAL_ERROR", message=str(e)),
            )


# ============================================================
# POST /api/complete/parse-preview
# ------------------------------------------------------------
# Парсит выписку+ОФД и возвращает превью помесячно.
# Не создаёт job, не рендерит PDF. Нужно для UI-wizard:
# пользователь смотрит что спарсилось, редактирует перед генерацией.
# ============================================================

from pydantic import BaseModel

class MonthlyIncome(BaseModel):
    month: int  # 1..12
    cashless: Decimal  # безнал (1С-выписка, income)
    cash: Decimal  # наличка (ОФД чеки, payment_type=cash)

class ParsePreviewResponse(BaseModel):
    owner_inn: str | None
    owner_name: str | None
    period_start: str | None  # ISO date
    period_end: str | None
    operations_total: int
    income_operations: int
    monthly: list[MonthlyIncome]  # 12 элементов (jan..dec)
    warnings: list[str]


from decimal import Decimal


@router.post(
    "/parse-preview",
    response_model=ParsePreviewResponse,
    summary="Парсит выписку+ОФД, возвращает помесячные доходы (без генерации PDF)",
)
async def parse_preview(
    statement: UploadFile = File(..., description="1С-выписка .txt"),
    ofd: UploadFile | None = File(None, description="Чеки ОФД .xlsx (опц.)"),
    year: int = Form(..., ge=2020, le=2030, description="Отчётный год"),
) -> ParsePreviewResponse:
    """Быстрый preview парсинга. Не пишет в БД, выполняется синхронно."""
    if not statement.filename or not statement.filename.lower().endswith(".txt"):
        raise HTTPException(400, "statement должен быть .txt файлом")

    statement_bytes = await statement.read()
    if len(statement_bytes) == 0:
        raise HTTPException(400, "Пустой файл выписки")
    if len(statement_bytes) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, "Выписка слишком большая")

    ofd_bytes: bytes | None = None
    if ofd is not None and ofd.filename:
        if not ofd.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(400, "ofd должен быть .xlsx или .xls")
        ofd_bytes = await ofd.read()
        if len(ofd_bytes) > MAX_OFD_BYTES:
            raise HTTPException(413, "ОФД слишком большой")
        if len(ofd_bytes) == 0:
            ofd_bytes = None

    try:
        from modules.declaration_filler import (
            parse_1c_statement_bytes,
            parse_ofd_bytes,
            classify_operations_monthly,
        )
    except ImportError as e:
        raise HTTPException(500, f"Не удалось загрузить парсеры: {e}")

    # 1. Парсинг выписки
    try:
        stmt = parse_1c_statement_bytes(statement_bytes)
    except Exception as e:
        raise HTTPException(422, f"Ошибка парсинга выписки: {e}")

    # 2. Классификация по месяцам (безнал)
    try:
        monthly_cashless = classify_operations_monthly(stmt, year=year)  # dict[int, Decimal] 1..12
    except Exception as e:
        raise HTTPException(500, f"Ошибка классификации: {e}")

    income_ops = sum(
        1 for op in stmt.operations
        if op.direction == "income" and op.operation_date.year == year
    )

    # 3. ОФД по месяцам (наличка)
    monthly_cash: dict[int, Decimal] = {m: Decimal("0") for m in range(1, 13)}
    if ofd_bytes:
        try:
            receipts = parse_ofd_bytes(ofd_bytes)
            for r in receipts:
                if r.get("payment_type") != "cash":
                    continue
                if r.get("operation_type") == "refund":
                    continue
                rdate = r.get("receipt_date")
                if rdate is None:
                    continue
                if hasattr(rdate, "year") and rdate.year != year:
                    continue
                m = rdate.month if hasattr(rdate, "month") else None
                if m is None:
                    continue
                monthly_cash[m] += Decimal(str(r.get("amount", 0)))
        except Exception as e:
            log.warning("Не удалось распарсить ОФД: %s", e)
            stmt.warnings.append(f"ОФД проигнорирован из-за ошибки парсинга: {e}")

    monthly_list = [
        MonthlyIncome(
            month=m,
            cashless=monthly_cashless.get(m, Decimal("0")),
            cash=monthly_cash[m],
        )
        for m in range(1, 13)
    ]

    return ParsePreviewResponse(
        owner_inn=stmt.owner_inn,
        owner_name=stmt.owner_name,
        period_start=stmt.period_start.isoformat() if stmt.period_start else None,
        period_end=stmt.period_end.isoformat() if stmt.period_end else None,
        operations_total=len(stmt.operations),
        income_operations=income_ops,
        monthly=monthly_list,
        warnings=stmt.warnings[:20],  # первые 20
    )

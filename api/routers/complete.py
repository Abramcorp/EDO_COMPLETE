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

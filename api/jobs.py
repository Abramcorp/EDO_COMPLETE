"""
JobStore — CRUD слой для таблицы jobs.
Отделяет ORM от routers и pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import JobRow
from api.models import ErrorInfo, JobResponse, JobStatus, PipelineStage


class JobNotFoundError(Exception):
    pass


class JobNotReadyError(Exception):
    """Попытка получить result до завершения job'а."""
    pass


class JobStore:
    """Тонкая обёртка над AsyncSession для работы с jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- create ----------

    async def create(self, input_meta: dict) -> UUID:
        job_id = uuid4()
        now = datetime.now(UTC)
        row = JobRow(
            id=job_id,
            status=JobStatus.QUEUED.value,
            stage=PipelineStage.INITIALIZING.value,
            progress_pct=0,
            input_meta=input_meta,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.commit()
        return job_id

    # ---------- read ----------

    async def get(self, job_id: UUID) -> JobRow:
        row = await self.session.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(f"Job {job_id} not found")
        return row

    async def get_response(self, job_id: UUID, result_url_prefix: str = "/api/jobs") -> JobResponse:
        row = await self.get(job_id)
        result_url = (
            f"{result_url_prefix}/{row.id}/result"
            if row.status == JobStatus.COMPLETE.value
            else None
        )
        return JobResponse(
            id=row.id,
            status=JobStatus(row.status),
            stage=PipelineStage(row.stage),
            progress_pct=row.progress_pct,
            error=ErrorInfo(**row.error) if row.error else None,
            result_url=result_url,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_result(self, job_id: UUID) -> tuple[bytes, str]:
        """Возвращает (pdf_bytes, filename). Бросает JobNotReadyError если не complete."""
        row = await self.get(job_id)
        if row.status != JobStatus.COMPLETE.value or row.result_blob is None:
            raise JobNotReadyError(f"Job {job_id} is {row.status}")
        return bytes(row.result_blob), row.result_filename or f"declaration_{row.id}.pdf"

    # ---------- update ----------

    async def mark_running(self, job_id: UUID) -> None:
        row = await self.get(job_id)
        row.status = JobStatus.RUNNING.value
        row.updated_at = datetime.now(UTC)
        await self.session.commit()

    async def update_progress(
        self,
        job_id: UUID,
        stage: PipelineStage,
        progress_pct: int,
    ) -> None:
        row = await self.get(job_id)
        row.stage = stage.value
        row.progress_pct = max(0, min(100, progress_pct))
        row.updated_at = datetime.now(UTC)
        await self.session.commit()

    async def mark_complete(self, job_id: UUID, pdf_bytes: bytes, filename: str) -> None:
        row = await self.get(job_id)
        row.status = JobStatus.COMPLETE.value
        row.stage = PipelineStage.COMPLETE.value
        row.progress_pct = 100
        row.result_blob = pdf_bytes
        row.result_filename = filename
        row.updated_at = datetime.now(UTC)
        await self.session.commit()

    async def mark_failed(self, job_id: UUID, error: ErrorInfo) -> None:
        row = await self.get(job_id)
        row.status = JobStatus.FAILED.value
        row.error = error.model_dump(mode="json")
        row.updated_at = datetime.now(UTC)
        await self.session.commit()

    # ---------- cleanup ----------

    async def cleanup_stale(self, ttl_hours: int = 24) -> int:
        """
        Удаляет jobs старше ttl_hours. Вызывается при старте + периодически.
        Также помечает как failed все jobs, которые остались в running после рестарта контейнера.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
        result = await self.session.execute(
            delete(JobRow).where(JobRow.created_at < cutoff)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def recover_orphaned_running(self) -> int:
        """После рестарта: running-jobs уже не вернутся к жизни — помечаем как failed."""
        stmt = select(JobRow).where(JobRow.status == JobStatus.RUNNING.value)
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            row.status = JobStatus.FAILED.value
            row.error = {
                "code": "ORPHANED",
                "message": "Container restarted during processing",
                "stage": row.stage,
            }
            row.updated_at = datetime.now(UTC)
        await self.session.commit()
        return len(rows)

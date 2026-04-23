"""
GET /api/jobs/{id}         — статус
GET /api/jobs/{id}/result  — PDF (если complete)
"""
from __future__ import annotations

import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.jobs import JobNotFoundError, JobNotReadyError, JobStore
from api.models import JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    store = JobStore(session)
    try:
        return await store.get_response(job_id)
    except JobNotFoundError:
        raise HTTPException(404, "Job not found")


@router.get("/{job_id}/result")
async def get_job_result(
    job_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    store = JobStore(session)
    try:
        pdf_bytes, filename = await store.get_result(job_id)
    except JobNotFoundError:
        raise HTTPException(404, "Job not found")
    except JobNotReadyError as e:
        raise HTTPException(409, str(e))

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )

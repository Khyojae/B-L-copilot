"""추출 작업(ingest_job) 상태 조회. 기획안 5.1: 업로드 즉시 job_id를 반환하고
진행 상태를 폴링/SSE로 표시한다."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.db import get_session
from smart_e_bl.models import IngestJob
from smart_e_bl.models.enums import JobStatus

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    progress: int
    error_code: str | None = None
    error_message: str | None = None


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> JobResponse:
    job = await session.scalar(select(IngestJob).where(IngestJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        error_code=job.error_code,
        error_message=job.error_message,
    )

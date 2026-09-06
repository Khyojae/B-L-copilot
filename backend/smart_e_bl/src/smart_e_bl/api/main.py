"""API 프로세스.

여기서는 짧은 요청만 처리합니다. OCR·LLM 추출·추론처럼 오래 걸리는 작업은
ingest_job 에 넣고 워커 프로세스가 가져갑니다 — 기획안 5.1 의
"업로드 즉시 job_id 를 반환하고 진행 상태를 폴링/SSE 로 표시한다" 가 이 구조입니다.
GIL 아래에서 CPU 작업을 이벤트 루프에 올리면 API 전체가 멈춥니다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.config import settings
from smart_e_bl.db import async_engine, get_session
from smart_e_bl.models import IngestJob
from smart_e_bl.models.enums import JobStatus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await async_engine.dispose()


app = FastAPI(
    title="B/L Copilot API",
    version="0.1.0",
    lifespan=lifespan,
)


class HealthResponse(BaseModel):
    status: str
    profile: str
    schema_revision: str | None


class JobResponse(BaseModel):
    """기획안 5.1 진행 상태: 대기·추출중·완료·실패."""

    job_id: UUID
    status: JobStatus
    progress: int
    error_code: str | None = None
    error_message: str | None = None


@app.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """DB 연결과 적용된 마이그레이션 리비전을 함께 확인합니다."""
    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    return HealthResponse(
        status="ok", profile=settings.deployment_profile, schema_revision=revision
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID, session: AsyncSession = Depends(get_session)
) -> JobResponse:
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

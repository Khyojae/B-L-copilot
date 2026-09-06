"""API 프로세스.

여기서는 짧은 요청만 처리합니다. OCR·LLM 추출·추론처럼 오래 걸리는 작업은
ingest_job 에 넣고 워커 프로세스가 가져갑니다 — 기획안 5.1 의
"업로드 즉시 job_id 를 반환하고 진행 상태를 폴링/SSE 로 표시한다" 가 이 구조입니다.
GIL 아래에서 CPU 작업을 이벤트 루프에 올리면 API 전체가 멈춥니다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.api.routes import auth, jobs
from smart_e_bl.config import settings
from smart_e_bl.db import async_engine, get_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await async_engine.dispose()


app = FastAPI(
    title="B/L Copilot API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(jobs.router)


class HealthResponse(BaseModel):
    status: str
    profile: str
    schema_revision: str | None


@app.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """DB 연결과 적용된 마이그레이션 리비전을 함께 확인합니다."""
    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    return HealthResponse(
        status="ok", profile=settings.deployment_profile, schema_revision=revision
    )

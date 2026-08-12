"""DB 엔진과 세션.

API 프로세스는 async(asyncpg), 워커 프로세스는 sync(psycopg)를 씁니다.
OCR·추론은 CPU 를 오래 점유하므로 이벤트 루프에 올리지 않습니다.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from smart_e_bl.config import settings

async_engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    # max_connections 100 을 여러 워커가 나눠 쓰므로 보수적으로 잡습니다.
    pool_size=5,
    max_overflow=5,
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True, pool_size=2, max_overflow=2)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 의존성. 요청 단위 세션."""
    async with AsyncSessionLocal() as session:
        yield session


@contextmanager
def sync_session() -> Iterator[Session]:
    """워커용 동기 세션."""
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()

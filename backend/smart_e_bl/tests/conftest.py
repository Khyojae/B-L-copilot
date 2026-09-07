"""shipments 라우트 테스트 공용 픽스처.

DB 제약 상당수(추정 생성 금지, 대표값 유일성, 업로드 중복 검출 등 —
infra/postgres/README.md 참고)가 애플리케이션이 아니라 Postgres CHECK/UNIQUE
로 걸려 있어 sqlite나 세션 목으로는 검증할 수 없다. 그래서 실제 Postgres에
대해 돈다 — CI는 backend-ci.yml에서 postgres 서비스 컨테이너를 띄우고
alembic upgrade 까지 마친 뒤 이 스위트를 돌린다.

각 테스트는 SAVEPOINT로 격리한다. 라우트 핸들러가 내부에서
session.commit()을 부르지만(create_shipment 등),
join_transaction_mode="create_savepoint" 덕분에 그 커밋은 SAVEPOINT 해제로만
끝나고 바깥 트랜잭션은 살아있다 — 테스트가 끝나면 그 바깥 트랜잭션을
롤백해서 DB를 원상 복구한다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from smart_e_bl.api.main import app
from smart_e_bl.config import settings
from smart_e_bl.db import get_session
from smart_e_bl.deps import CurrentUser, get_current_user
from smart_e_bl.models import AppUser, Tenant

# pytest-asyncio는 테스트마다 새 이벤트 루프를 만든다. db.py의 async_engine은
# 앱 운영을 위한 풀링(pool_size=5)이 있어서, 한 루프에서 체크아웃한 asyncpg
# 커넥션을 다음 테스트(다른 루프)가 재사용하려다 "Event loop is closed"로
# 터진다. 테스트는 풀링 이득이 필요 없으니 NullPool로 매번 새 커넥션을 연다.
_test_engine = create_async_engine(settings.async_database_url, poolclass=NullPool)


@pytest.fixture(autouse=True)
def _isolated_storage_dir(tmp_path, monkeypatch):
    """업로드 테스트가 실제 data/documents 디렉터리를 건드리지 않게 한다."""
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with _test_engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as db:
            yield db
        await conn.rollback()


@pytest_asyncio.fixture
async def tenant(session: AsyncSession) -> Tenant:
    t = Tenant(code=f"T-{uuid.uuid4().hex[:8]}", name="테스트 테넌트")
    session.add(t)
    await session.flush()
    return t


@pytest_asyncio.fixture
async def user(session: AsyncSession, tenant: Tenant) -> AppUser:
    u = AppUser(
        tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        name="테스트 사용자",
        role="MEMBER",
        password_hash="x",
    )
    session.add(u)
    await session.flush()
    return u


@dataclass
class ClientFactory:
    """current_user를 바꿔가며 같은 트랜잭션 위에 클라이언트를 만든다(테넌트 격리 테스트용)."""

    session: AsyncSession

    def __call__(self, current: CurrentUser) -> AsyncClient:
        app.dependency_overrides[get_session] = lambda: self.session
        app.dependency_overrides[get_current_user] = lambda: current
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def make_client(session: AsyncSession) -> AsyncIterator[Callable[[CurrentUser], AsyncClient]]:
    yield ClientFactory(session)
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(
    make_client: Callable[[CurrentUser], AsyncClient], user: AppUser
) -> AsyncIterator[AsyncClient]:
    current = CurrentUser(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    async with make_client(current) as c:
        yield c


@pytest_asyncio.fixture
async def anonymous_client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """인증 헤더 없이 호출 — get_current_user를 오버라이드하지 않는다."""
    app.dependency_overrides[get_session] = lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()

"""FastAPI 의존성 — 인증된 사용자, 테넌트 스코프."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.clients.ai_service import AsyncAiServiceClient
from smart_e_bl.db import get_session
from smart_e_bl.models import AppUser
from smart_e_bl.security import InvalidTokenError, TokenType, decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "인증이 필요합니다")
    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"유효하지 않은 토큰: {exc}") from exc

    user_id = uuid.UUID(payload["sub"])
    user = await session.scalar(select(AppUser).where(AppUser.id == user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "사용자를 찾을 수 없거나 비활성 상태입니다")

    return CurrentUser(user_id=user.id, tenant_id=user.tenant_id, role=user.role)


def get_ai_client() -> AsyncAiServiceClient:
    """aiService 클라이언트. 의존성으로 두는 이유는 테스트가 네트워크 없이
    가짜 클라이언트로 바꿔 끼우기 위해서다(`app.dependency_overrides`)."""
    return AsyncAiServiceClient()

"""비밀번호 해시 · JWT 발급/검증.

토큰 클레임은 최소한으로 유지합니다: 사용자 식별(sub)과 테넌트 스코프(tenant_id)만.
역할(role)은 매 요청 DB에서 조회합니다 — 토큰에 넣으면 역할 변경이 즉시 반영되지
않습니다(로그아웃 전까지 예전 권한이 유효해짐).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import bcrypt
import jwt

from smart_e_bl.config import settings

# passlib(유지보수 중단)이 bcrypt>=4.1과 자체 버전감지에서 충돌해 여기서는 bcrypt를
# 직접 쓴다. bcrypt 알고리즘 자체가 72바이트를 넘는 입력을 자르므로 이를 명시한다.
_BCRYPT_MAX_BYTES = 72


def hash_password(raw_password: str) -> str:
    truncated = raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("ascii")


def verify_password(raw_password: str, hashed_password: str) -> bool:
    truncated = raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed_password.encode("ascii"))


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def _create_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID, token_type: TokenType, expires_delta: timedelta
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.jwt_access_expires_min),
    )


def create_refresh_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return _create_token(
        user_id=user_id,
        tenant_id=tenant_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(minutes=settings.jwt_refresh_expires_min),
    )


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(f"token type mismatch: expected {expected_type.value}")
    return payload

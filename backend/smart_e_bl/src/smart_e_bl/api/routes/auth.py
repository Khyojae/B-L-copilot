"""회원가입/로그인/토큰 갱신.

비밀번호는 bcrypt 해시로만 저장한다(평문·가역 암호화 금지). 역할별 세부 권한 체크
(RBAC 미들웨어)는 이번 라운드 범위 밖 — signup 시 값 검증만 한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.db import get_session
from smart_e_bl.deps import CurrentUser, get_current_user
from smart_e_bl.models import AppUser
from smart_e_bl.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from smart_e_bl.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, session: AsyncSession = Depends(get_session)) -> AppUser:
    user = AppUser(
        tenant_id=body.tenant_id,
        email=body.email,
        name=body.name,
        role=body.role.value,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "이미 등록된 이메일입니다(같은 테넌트 내)"
        ) from exc
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await session.scalar(select(AppUser).where(AppUser.email == body.email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다")

    return TokenResponse(
        access_token=create_access_token(user_id=user.id, tenant_id=user.tenant_id),
        refresh_token=create_refresh_token(user_id=user.id, tenant_id=user.tenant_id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, expected_type=TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"유효하지 않은 리프레시 토큰: {exc}") from exc

    user = await session.scalar(select(AppUser).where(AppUser.id == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "사용자를 찾을 수 없거나 비활성 상태입니다")

    return TokenResponse(
        access_token=create_access_token(user_id=user.id, tenant_id=user.tenant_id),
        refresh_token=create_refresh_token(user_id=user.id, tenant_id=user.tenant_id),
    )


@router.get("/me", response_model=UserResponse)
async def me(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    user = await session.scalar(select(AppUser).where(AppUser.id == current.user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다")
    return user

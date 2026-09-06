"""회원가입/로그인 요청·응답 스키마."""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class UserRole(StrEnum):
    """§Party(화주/포워더/선사/은행/관세사)에 대응하는 계정 역할. 세분화된 권한 체크는
    이번 라운드 범위 밖이며(계획 참고), 값 검증만 이 열거형으로 강제한다."""

    SHIPPER = "SHIPPER"
    FORWARDER = "FORWARDER"
    CARRIER = "CARRIER"
    BANK = "BANK"
    CUSTOMS_BROKER = "CUSTOMS_BROKER"
    ADMIN = "ADMIN"


class SignupRequest(BaseModel):
    tenant_id: uuid.UUID
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: UserRole = UserRole.SHIPPER


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}

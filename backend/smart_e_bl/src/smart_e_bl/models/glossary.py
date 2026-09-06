"""F2 표준 용어 교정 (migrations/sql/04)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from smart_e_bl.models.base import Base, created_at, pg_enum, updated_at, uuid_pk
from smart_e_bl.models.enums import (
    GlossaryAuthority,
    GlossaryScope,
    SuggestionRejectReason,
    SuggestionStatus,
)


class GlossaryTerm(Base):
    """기획안 5.2 계층 구조: 표준 사전 → 조직 사전 → 선적 예외."""

    __tablename__ = "glossary_term"

    id: Mapped[uuid.UUID] = uuid_pk()
    term_code: Mapped[str] = mapped_column(Text, nullable=False)
    canonical: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(Text, nullable=False, default="en")
    authority: Mapped[GlossaryAuthority] = mapped_column(
        pg_enum("glossary_authority"), nullable=False
    )

    scope: Mapped[GlossaryScope] = mapped_column(
        pg_enum("glossary_scope"), nullable=False, default=GlossaryScope.STANDARD
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE")
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE")
    )

    version: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    deprecated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("glossary_term.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class GlossaryAlias(Base):
    """비표준 표기. normalized_key 는 정확 일치·유사도 검색의 조회 키."""

    __tablename__ = "glossary_alias"

    id: Mapped[uuid.UUID] = uuid_pk()
    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("glossary_term.id", ondelete="CASCADE"), nullable=False
    )
    alias_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


class NormalizationSuggestion(Base):
    """기획안 5.2 제안 카드. 자동 치환 없이 사용자 승인으로만 반영된다."""

    __tablename__ = "normalization_suggestion"
    __table_args__ = {
        "comment": "기획안 5.2 제안 카드. 자동 치환 없이 사용자 승인으로만 반영된다"
    }

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )
    field_value_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_value.id", ondelete="CASCADE"), nullable=False
    )

    as_is: Mapped[str] = mapped_column(Text, nullable=False)
    to_be: Mapped[str] = mapped_column(Text, nullable=False)
    term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("glossary_term.id", ondelete="SET NULL")
    )
    authority: Mapped[GlossaryAuthority | None] = mapped_column(pg_enum("glossary_authority"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    # 기획안 5.2: 판별 불가 시 후보를 나열해 사용자에게 선택시킨다(임의 선택 금지).
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    chosen_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("glossary_term.id", ondelete="SET NULL")
    )

    impact_scope_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[SuggestionStatus] = mapped_column(
        pg_enum("suggestion_status"), nullable=False, default=SuggestionStatus.PROPOSED
    )
    reject_reason: Mapped[SuggestionRejectReason | None] = mapped_column(
        pg_enum("suggestion_reject_reason")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()

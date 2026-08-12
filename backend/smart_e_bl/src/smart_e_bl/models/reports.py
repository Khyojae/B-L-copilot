"""F4 선제 대응 리포트 · 감사 로그 (migrations/sql/07, 08)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from smart_e_bl.models.base import Base, created_at, uuid_pk


class Report(Base):
    """기획안 5.4 스냅샷 불변성.

    snapshot·content_hash·버전 정보는 생성 후 변경할 수 없습니다.
    DB 트리거(report_immutable)가 UPDATE 를 거부하므로, 내용이 바뀌어야 하면
    새 리포트를 생성해야 합니다. pdf_storage_uri 만 사후 갱신이 허용됩니다.
    """

    __tablename__ = "report"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )

    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)

    input_document_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    rule_catalog_version: Mapped[str] = mapped_column(
        Text, ForeignKey("rule_catalog_version.version"), nullable=False
    )
    model_version: Mapped[str | None] = mapped_column(
        Text, ForeignKey("model_version.version")
    )
    glossary_version: Mapped[str | None] = mapped_column(Text)
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("defect_prediction.id", ondelete="SET NULL")
    )

    defect_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_rule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deferred_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    language: Mapped[str] = mapped_column(Text, nullable=False, default="ko")

    pdf_storage_uri: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    generated_at: Mapped[datetime] = created_at()


class AuditLog(Base):
    """기획안 5.8: 필드 변경·승인·거절·리포트 공유는 행위자와 시각을 남긴다."""

    __tablename__ = "audit_log"
    __table_args__ = {"comment": "기획안 5.8 감사 로그. 폐쇄망 프로파일의 감사 요건 대응"}

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="SET NULL")
    )
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    client_ip: Mapped[str | None] = mapped_column(INET)
    occurred_at: Mapped[datetime] = created_at()

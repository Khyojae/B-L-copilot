"""F3 판정 — 룰엔진 판정과 하자 확률 예측 (migrations/sql/06)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from smart_e_bl.models.base import Base, created_at, pg_enum, uuid_pk
from smart_e_bl.models.enums import Severity, VerdictStatus


class Verdict(Base):
    """기획안 5.8 verdict 도메인 객체. F3 생산 → F4 소비."""

    __tablename__ = "verdict"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule.id", ondelete="RESTRICT"), nullable=False
    )

    severity: Mapped[Severity] = mapped_column(pg_enum("severity"), nullable=False)
    status: Mapped[VerdictStatus] = mapped_column(
        pg_enum("verdict_status"), nullable=False, default=VerdictStatus.OPEN
    )

    target_field_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("field_definition.code")
    )
    target_field_value_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_value.id", ondelete="SET NULL")
    )
    actual_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # 동일 근본 원인에서 파생된 위반은 대표 위반으로 병합한다(기획안 5.3).
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verdict.id", ondelete="SET NULL")
    )

    rule_catalog_version: Mapped[str] = mapped_column(
        Text, ForeignKey("rule_catalog_version.version"), nullable=False
    )
    glossary_version: Mapped[str | None] = mapped_column(Text)

    judged_at: Mapped[datetime] = created_at()


class VerdictEvidence(Base):
    """기획안 5.3 수용 기준: 모든 룰 위반 항목의 조문 근거 표시율 100%."""

    __tablename__ = "verdict_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    verdict_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verdict.id", ondelete="CASCADE"), nullable=False
    )
    evidence_side: Mapped[str] = mapped_column(Text, nullable=False)
    field_value_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_value.id", ondelete="CASCADE")
    )
    snippet: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class VerdictDisposition(Base):
    """기획안 5.8: 자동 반영하지 않고 사용자의 명시적 승인으로만 확정한다."""

    __tablename__ = "verdict_disposition"

    id: Mapped[uuid.UUID] = uuid_pk()
    verdict_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("verdict.id", ondelete="CASCADE"), nullable=False
    )
    to_status: Mapped[VerdictStatus] = mapped_column(pg_enum("verdict_status"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    decided_at: Mapped[datetime] = created_at()


class ModelVersion(Base):
    """기획안 5.3: 재학습 후 성능이 하락하면 이전 모델로 롤백한다."""

    __tablename__ = "model_version"

    version: Mapped[str] = mapped_column(Text, primary_key=True)
    trained_at: Mapped[datetime] = created_at()
    training_label_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metric_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    metric_roc_auc: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    metric_brier: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rolled_back_from: Mapped[str | None] = mapped_column(
        Text, ForeignKey("model_version.version")
    )
    note: Mapped[str | None] = mapped_column(Text)


class DefectPrediction(Base):
    """F3 계층 B. 보정 전 원점수(raw_score)는 사용자에게 표시하지 않는다."""

    __tablename__ = "defect_prediction"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )

    probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    raw_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), comment="기획안 5.3: 보정 전 원점수는 사용자에게 표시하지 않는다"
    )
    is_calibrated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    model_version: Mapped[str] = mapped_column(
        Text, ForeignKey("model_version.version"), nullable=False
    )
    rule_catalog_version: Mapped[str] = mapped_column(
        Text, ForeignKey("rule_catalog_version.version"), nullable=False
    )
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    deferred_field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_range_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = created_at()


class PredictionFactor(Base):
    """기획안 5.3: SHAP 기여도 상위 5개 요인."""

    __tablename__ = "prediction_factor"

    id: Mapped[uuid.UUID] = uuid_pk()
    prediction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("defect_prediction.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    feature_name: Mapped[str] = mapped_column(Text, nullable=False)
    feature_group: Mapped[str | None] = mapped_column(Text)
    shap_value: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)

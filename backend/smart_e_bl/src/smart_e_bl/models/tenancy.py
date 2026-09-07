"""테넌트 · 사용자 · 선적 (migrations/sql/02)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from smart_e_bl.models.base import Base, created_at, pg_enum, updated_at, uuid_pk
from smart_e_bl.models.enums import ShipmentStatus


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_onpremise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="MEMBER")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Shipment(Base):
    __tablename__ = "shipment"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        pg_enum("shipment_status"), nullable=False, default=ShipmentStatus.DRAFT
    )

    bl_no: Mapped[str | None] = mapped_column(Text)
    booking_no: Mapped[str | None] = mapped_column(Text)
    lc_no: Mapped[str | None] = mapped_column(Text)
    cargo_control_no: Mapped[str | None] = mapped_column(
        Text, comment="화물관리번호(MRN 계열). F6 도입 시 UNI-PASS 조회 키가 된다"
    )

    shipper_name: Mapped[str | None] = mapped_column(Text)
    consignee_name: Mapped[str | None] = mapped_column(Text)
    notify_party_name: Mapped[str | None] = mapped_column(Text)
    carrier_name: Mapped[str | None] = mapped_column(Text)

    lc_expiry_date: Mapped[date | None] = mapped_column(Date)
    presentation_period_days: Mapped[int | None] = mapped_column(Integer)
    latest_shipment_date: Mapped[date | None] = mapped_column(Date)
    onboard_date: Mapped[date | None] = mapped_column(Date)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    has_letter_of_credit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="shipment", cascade="all, delete-orphan", lazy="raise"
    )


class ShipmentStatusHistory(Base):
    """기획안 5.8: 강제 진행 사유는 리포트와 피드백 데이터에 남는다."""

    __tablename__ = "shipment_status_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[ShipmentStatus | None] = mapped_column(pg_enum("shipment_status"))
    to_status: Mapped[ShipmentStatus] = mapped_column(
        pg_enum("shipment_status"), nullable=False
    )
    is_forced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_reason: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    occurred_at: Mapped[datetime] = created_at()

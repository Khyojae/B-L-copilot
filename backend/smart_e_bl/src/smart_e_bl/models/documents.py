"""F1 서류 인테이크 · 필드 값 (migrations/sql/03)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from smart_e_bl.models.base import Base, created_at, pg_enum, updated_at, uuid_pk
from smart_e_bl.models.enums import (
    ConfidenceGrade,
    DocumentSource,
    DocumentType,
    ExtractorKind,
    JobStatus,
)


class IngestJob(Base):
    """기획안 5.1: 업로드 즉시 job_id 를 반환하고 진행 상태를 폴링/SSE 로 표시한다."""

    __tablename__ = "ingest_job"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE")
    )
    status: Mapped[JobStatus] = mapped_column(
        pg_enum("job_status"), nullable=False, default=JobStatus.QUEUED
    )
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "document"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )
    ingest_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_job.id", ondelete="SET NULL")
    )
    doc_type: Mapped[DocumentType] = mapped_column(pg_enum("document_type"), nullable=False)
    source: Mapped[DocumentSource] = mapped_column(
        pg_enum("document_source"), nullable=False, default=DocumentSource.UPLOAD
    )

    original_filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(Text)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )

    # 기획안 5.1: 한 파일에 여러 서류가 섞인 경우 페이지 단위로 분할·재분류한다.
    source_page_from: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_page_to: Mapped[int | None] = mapped_column(Integer)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    created_at: Mapped[datetime] = created_at()

    shipment: Mapped["Shipment"] = relationship(  # noqa: F821
        back_populates="documents", lazy="raise"
    )


class FieldDefinition(Base):
    """B/L 표준 필드 카탈로그 (기획안 5.1 출력 필드 표)."""

    __tablename__ = "field_definition"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    doc_type: Mapped[DocumentType] = mapped_column(pg_enum("document_type"), nullable=False)
    field_group: Mapped[str] = mapped_column(Text, nullable=False)
    label_ko: Mapped[str] = mapped_column(Text, nullable=False)
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    source_priority: Mapped[list[str]] = mapped_column(
        ARRAY(pg_enum("document_type")), nullable=False, default=list
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()


class FieldValue(Base):
    """기획안 5.1 필드 값 객체.

    자동 추출 값은 반드시 원문 근거 좌표를 가져야 합니다(추정 생성 금지).
    이 규칙은 DB CHECK 로 강제되며 타입 시그니처에는 나타나지 않습니다 —
    document_id/page/bbox 를 비운 채 OCR_LLM 으로 저장하면 런타임에 거부됩니다.
    """

    __tablename__ = "field_value"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipment.id", ondelete="CASCADE"), nullable=False
    )
    field_code: Mapped[str] = mapped_column(
        Text, ForeignKey("field_definition.code"), nullable=False
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE")
    )
    page: Mapped[int | None] = mapped_column(Integer)
    bbox_x1: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    bbox_y1: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    bbox_x2: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    bbox_y2: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))

    value: Mapped[str | None] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    grade: Mapped[ConfidenceGrade] = mapped_column(pg_enum("confidence_grade"), nullable=False)
    extractor: Mapped[ExtractorKind] = mapped_column(pg_enum("extractor_kind"), nullable=False)

    is_representative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    glossary_version: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

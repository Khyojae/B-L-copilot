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
    EvidenceDerivation,
    EvidenceMode,
    EvidenceStatus,
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


class DocumentToken(Base):
    """OCR 단어 토큰 계층 (migrations/sql/evidence/10).

    저장 계층이 "그 좌표 안에 무엇이 쓰여 있었는가"를 물어볼 수 있게 하는 표.
    OCR 엔진 출력만 적재한다 — 데이터셋 라벨을 넣으면 검증이 자명해진다(오라클 오염).
    norm_text 는 DB 트리거가 evidence_norm(text) 로 채우므로 넣지 않아도 된다.
    """

    __tablename__ = "document_token"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), primary_key=True
    )
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    norm_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    bbox_x1: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    bbox_y1: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    bbox_x2: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    bbox_y2: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))


class FieldValue(Base):
    """기획안 5.1 필드 값 객체.

    자동 추출 값은 원문 근거로부터 유도 가능해야 합니다(추정 생성 금지).
    이 규칙은 DB 트리거(fn_field_value_enforce_evidence, migrations/sql/evidence/10)가
    저장 시점에 검사하며 타입 시그니처에는 나타나지 않습니다 — 근거 스팬 텍스트가
    값을 뒷받침하지 못하면 거부되는 대신 UNGROUNDED 로 격리되고 grade 가
    REVIEW_REQUIRED 로 강등됩니다. evidence_status·derivation·evidence_mode·
    evidence_reason 은 트리거가 채우는 판정 컬럼이라 넣어도 덮어써집니다.
    기계 소비 경로(룰 엔진·리포트·재학습)는 이 표가 아니라 field_value_trusted
    뷰를 읽어야 합니다.
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

    # 논문 §4.2 값–근거 결속. 파서가 넘기는 것: source_layer · evidence_token_from/to
    source_layer: Mapped[str | None] = mapped_column(Text)  # REGION | ANCHOR | LLM
    evidence_token_from: Mapped[int | None] = mapped_column(Integer)
    evidence_token_to: Mapped[int | None] = mapped_column(Integer)  # half-open [from, to)
    # 트리거가 채우는 판정
    derivation: Mapped[EvidenceDerivation | None] = mapped_column(pg_enum("evidence_derivation"))
    evidence_status: Mapped[EvidenceStatus | None] = mapped_column(pg_enum("evidence_status"))
    evidence_mode: Mapped[EvidenceMode | None] = mapped_column(pg_enum("evidence_mode"))
    evidence_reason: Mapped[str | None] = mapped_column(Text)
    # 논문 §4.5 면제 조항 봉인: extractor = MANUAL 이면 반드시 있어야 한다(CHECK).
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

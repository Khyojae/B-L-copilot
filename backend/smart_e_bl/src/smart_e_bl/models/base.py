"""모델 공통 기반.

DDL 의 출처는 migrations/sql/ 이고, 이 모델들은 그 스키마를 Python 에서 다루기 위한
매핑입니다. 따라서 열거형은 create_type=False 로 두어 SQLAlchemy 가 타입을 만들려
하지 않게 합니다.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from smart_e_bl.models import enums


class Base(DeclarativeBase):
    # 명명 규칙을 두지 않습니다. 제약·인덱스 이름의 출처는 migrations/sql/ 이며,
    # 여기에 규칙을 걸면 SQLAlchemy 가 계산한 이름과 실제 이름이 어긋나
    # autogenerate 가 매번 rename 을 제안합니다.
    metadata = MetaData()


# Postgres 열거형 이름 → Python 열거형.
# 타입 생성은 migrations/sql/01 이 하고, 여기서는 값 목록만 알려줍니다.
# 값 목록이 없으면 조회 시 LookupError 가 납니다.
_ENUM_REGISTRY: dict[str, type[enum.Enum]] = {
    "shipment_status": enums.ShipmentStatus,
    "severity": enums.Severity,
    "confidence_grade": enums.ConfidenceGrade,
    "extractor_kind": enums.ExtractorKind,
    "document_type": enums.DocumentType,
    "document_source": enums.DocumentSource,
    "job_status": enums.JobStatus,
    "verdict_status": enums.VerdictStatus,
    "glossary_authority": enums.GlossaryAuthority,
    "glossary_scope": enums.GlossaryScope,
    "suggestion_status": enums.SuggestionStatus,
    "suggestion_reject_reason": enums.SuggestionRejectReason,
    "evidence_mode": enums.EvidenceMode,
    "evidence_derivation": enums.EvidenceDerivation,
    "evidence_status": enums.EvidenceStatus,
}


def pg_enum(name: str) -> ENUM:
    """migrations/sql/01 에서 이미 생성한 열거형을 참조만 합니다."""
    return ENUM(
        _ENUM_REGISTRY[name],
        name=name,
        create_type=False,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )


def uuid_pk() -> Mapped[Any]:
    """PostgreSQL 18 의 uuidv7() 기본값을 쓰는 PK."""
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def updated_at() -> Mapped[datetime]:
    """갱신은 DB 트리거(set_updated_at)가 담당합니다."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""F3 계층 A — 룰 카탈로그 (migrations/sql/05).

기획안 5.3: 룰은 코드가 아니라 데이터로 관리하여 조문 개정 시 배포 없이 갱신한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from smart_e_bl.models.base import Base, created_at, pg_enum, uuid_pk
from smart_e_bl.models.enums import Severity


class RuleCatalogVersion(Base):
    """판정 재현성의 단위. 과거 판정을 당시 기준으로 재현하기 위해 버전을 고정한다."""

    __tablename__ = "rule_catalog_version"

    version: Mapped[str] = mapped_column(Text, primary_key=True)
    released_at: Mapped[datetime] = created_at()
    note: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Rule(Base):
    __tablename__ = "rule"

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(
        Text,
        ForeignKey("rule_catalog_version.version", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    authority_ref: Mapped[str] = mapped_column(Text, nullable=False)
    # UCP600·ISBP 조문 원문. ICC 저작물이라 라이선스 확보 후 채워야 합니다.
    authority_snippet: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="기획안 5.3: 조문 원문 스니펫. UCP600·ISBP 는 ICC 저작물이므로 라이선스 확보 후 채운다",
    )
    severity: Mapped[Severity] = mapped_column(pg_enum("severity"), nullable=False)

    target_field_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )

    expression: Mapped[str] = mapped_column(Text, nullable=False)
    is_llm_assisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    message_template: Mapped[str] = mapped_column(Text, nullable=False)
    remediation_template: Mapped[str] = mapped_column(Text, nullable=False)

    requires_lc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = created_at()

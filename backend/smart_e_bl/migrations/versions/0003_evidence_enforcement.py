"""저장 계층 근거 강제 — document_token · 검증 트리거 · 격리 뷰 · 모드 스위치

Revision ID: 0003_evidence_enforcement
Revises: 0002_app_user_password_hash
Create Date: 2026-09-22

ACK 2026 논문(저장 계층의 근거 강제를 통한 문서 AI 추출값의 환각 억제)의
프로토타입. DDL 은 migrations/sql/evidence/10_evidence_enforcement.sql 이 출처다
(baseline 이 migrations/sql/*.sql 을 통째로 실행하므로 하위 디렉터리에 둔다).

기존 CHECK field_value_evidence_required_ck(좌표 존재)는 트리거의 E1 모드로
대체되고, 위반 시 거부 대신 격리(UNGROUNDED + REVIEW_REQUIRED)한다.
downgrade 는 그 CHECK 를 되살린다.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0003_evidence_enforcement"
down_revision: str | None = "0002_app_user_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "evidence" / "10_evidence_enforcement.sql"


def upgrade() -> None:
    op.execute(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS field_value_review_queue;
        DROP VIEW IF EXISTS field_value_trusted;
        DROP TRIGGER IF EXISTS field_value_enforce_evidence ON field_value;
        DROP FUNCTION IF EXISTS fn_field_value_enforce_evidence();
        DROP FUNCTION IF EXISTS evidence_quarantine(field_value, text);
        DROP FUNCTION IF EXISTS evidence_span_text(uuid, integer, integer, integer);
        DROP FUNCTION IF EXISTS evidence_glossary_match(text, text, uuid);
        DROP FUNCTION IF EXISTS evidence_numbers(text);
        DROP FUNCTION IF EXISTS evidence_parse_number(text);
        DROP FUNCTION IF EXISTS evidence_parse_date(text);
        DROP FUNCTION IF EXISTS evidence_strip_leading_zeros(text);
        DROP TABLE IF EXISTS evidence_format_rule;

        ALTER TABLE field_value
          DROP CONSTRAINT IF EXISTS field_value_manual_actor_ck,
          DROP CONSTRAINT IF EXISTS field_value_evidence_span_ck,
          DROP CONSTRAINT IF EXISTS field_value_source_layer_ck,
          DROP COLUMN IF EXISTS edited_by,
          DROP COLUMN IF EXISTS evidence_reason,
          DROP COLUMN IF EXISTS evidence_mode,
          DROP COLUMN IF EXISTS evidence_status,
          DROP COLUMN IF EXISTS derivation,
          DROP COLUMN IF EXISTS evidence_token_to,
          DROP COLUMN IF EXISTS evidence_token_from,
          DROP COLUMN IF EXISTS source_layer;

        ALTER TABLE field_value ADD CONSTRAINT field_value_evidence_required_ck CHECK (
          extractor IN ('MANUAL', 'JSON')
          OR grade = 'NOT_FOUND'
          OR (document_id IS NOT NULL AND page IS NOT NULL AND bbox_x1 IS NOT NULL)
        );
        COMMENT ON CONSTRAINT field_value_evidence_required_ck ON field_value
          IS '기획안 5.1 추정 생성 금지 규칙: 원문 근거 좌표가 없는 자동 추출 값은 저장하지 않는다';

        DROP TRIGGER IF EXISTS document_token_norm ON document_token;
        DROP FUNCTION IF EXISTS fn_document_token_norm();
        DROP TABLE IF EXISTS document_token;
        DROP FUNCTION IF EXISTS evidence_norm(text);

        DROP FUNCTION IF EXISTS set_evidence_reattach_threshold(numeric);
        DROP FUNCTION IF EXISTS set_evidence_mode(evidence_mode);
        DROP FUNCTION IF EXISTS current_evidence_mode();
        DROP TABLE IF EXISTS evidence_enforcement_config;

        DROP TYPE IF EXISTS evidence_status;
        DROP TYPE IF EXISTS evidence_derivation;
        DROP TYPE IF EXISTS evidence_mode;
        """
    )

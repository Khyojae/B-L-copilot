"""상업송장·포장명세서 필드 정의 12건 추가 — aiService 추출 필드·서류 간 룰과 맞춤

Revision ID: 0004_invoice_packing_fields
Revises: 0003_evidence_enforcement
Create Date: 2026-09-22

09_seed_catalog.sql 의 INV/PL 코드(4+4)는 aiService 가 두 서류에서 뽑는
필드(9+10)와 cross_rules.yaml 이 대조하는 필드를 다 담지 못했다. 코드가
없는 필드는 워커(worker/pipeline.py)가 버리므로 서류 간 정합성 검사가
입력 없이 돌았다. DDL 은 migrations/sql/catalog/11_invoice_packing_fields.sql.
mapping.DB_FIELD_CODE_TO_AI 에 같은 12건이 있어야 워커가 실제로 저장한다.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0004_invoice_packing_fields"
down_revision: str | None = "0003_evidence_enforcement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "catalog" / "11_invoice_packing_fields.sql"

CODES = (
    "INV.INVOICE_NO",
    "INV.INVOICE_DATE",
    "INV.SELLER",
    "INV.BUYER",
    "INV.INCOTERMS",
    "INV.LC_NO",
    "PL.INVOICE_NO",
    "PL.PACKING_DATE",
    "PL.SELLER",
    "PL.BUYER",
    "PL.DESCRIPTION_OF_GOODS",
    "PL.MARKS",
)


def upgrade() -> None:
    op.execute(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # field_value.field_code 가 field_definition 을 참조한다. 이 코드로 저장된
    # 값이 있으면 정의를 지울 수 없으므로 값부터 지운다 — 0001 의 downgrade 가
    # 스키마를 통째로 버리는 것과 같은 수준의 되돌리기다.
    codes = ", ".join(f"'{c}'" for c in CODES)
    op.execute(f"DELETE FROM field_value WHERE field_code IN ({codes})")
    op.execute(f"DELETE FROM field_definition WHERE code IN ({codes})")

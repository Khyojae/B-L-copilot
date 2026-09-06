"""baseline — 손으로 작성해 검증한 초기 스키마

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-12

이 리비전은 autogenerate 로 만들지 않았습니다.
현재 스키마에는 SQLAlchemy 모델로 표현되지 않는 객체가 다수 있고
(CHECK 제약 32 · 트리거 6 · 함수 2 · 부분 인덱스 15 · uuidv7() 기본값),
autogenerate 로 재생성하면 전부 유실됩니다.

따라서 migrations/sql/ 의 DDL 을 그대로 실행합니다. 이 파일들이 스키마의 유일한 출처이며,
기획안의 명세 규칙(추정 생성 금지·리포트 불변성 등)이 제약으로 들어 있습니다.
자세한 내용은 infra/postgres/README.md 참고.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def upgrade() -> None:
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"baseline DDL 을 찾을 수 없습니다: {SQL_DIR}")
    for path in files:
        op.execute(path.read_text(encoding="utf-8"))


def downgrade() -> None:
    # baseline 이전 상태는 "스키마 없음"입니다.
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")

"""app_user에 password_hash 추가 — 인증(회원가입/로그인) 구현에 필요

Revision ID: 0002_app_user_password_hash
Revises: 0001_baseline
Create Date: 2026-09-07

baseline 스키마는 인증을 다루지 않아 app_user에 비밀번호 저장 컬럼이 없었다.
bcrypt 해시만 저장하며 평문은 저장하지 않는다. 기존 행(있다면) 호환을 위해
빈 문자열 기본값을 두되, 애플리케이션은 signup 시 항상 실제 해시로 채운다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_app_user_password_hash"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app_user ADD COLUMN password_hash text NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app_user DROP COLUMN password_hash")

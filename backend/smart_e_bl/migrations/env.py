"""Alembic 환경 설정.

접속 정보는 .env 의 DATABASE_URL 하나에서만 읽습니다(alembic.ini 에 두지 않음).
마이그레이션은 동기 드라이버(psycopg)로 실행합니다 — 애플리케이션이 asyncpg 를 쓰더라도
DDL 실행에는 비동기가 이점이 없고, 오프라인 모드 지원이 단순해집니다.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from smart_e_bl.config import settings
from smart_e_bl.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sync_database_url)

# autogenerate 비교 대상. 모델과 실제 DB 가 어긋나면 여기서 드러납니다.
target_metadata = Base.metadata


# autogenerate 가 비교하지 않을 객체 종류.
#
# 인덱스·CHECK·UNIQUE 는 migrations/sql/ 이 소유합니다. 모델에 선언하지 않았으므로
# 비교 대상에 두면 autogenerate 가 매번 "제거"를 제안하고, 그대로 적용하면
# 부분 인덱스 15개와 명세 규칙 CHECK 32개가 사라집니다.
#
# 대신 테이블·컬럼 변경은 정상적으로 감지됩니다. 제약·인덱스를 추가할 때는
# 생성된 리비전에 op.execute() 로 직접 작성하세요.
SQL_OWNED_TYPES = {"index", "unique_constraint", "check_constraint"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name == "alembic_version":
        return False
    if type_ in SQL_OWNED_TYPES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""애플리케이션 설정.

.env 의 DATABASE_URL 하나를 접속 정보의 단일 출처로 씁니다.
드라이버는 용도에 따라 갈립니다 — API 는 asyncpg, 마이그레이션·워커는 psycopg.
"""

from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://smart_ebl:smart_ebl@localhost:5432/smart_ebl"

    # 기획안 6.1 이중 배포 프로파일. LLM 호출 경로가 갈립니다.
    deployment_profile: str = "saas"  # saas | onpremise

    # 기획안 5.1: 10페이지 문서 세트 60초(SaaS) / 120초(온프레미스)
    extraction_timeout_seconds: int = 60

    # 워커가 한 번에 집어가는 잡 수와 폴링 간격
    worker_batch_size: int = 1
    worker_poll_seconds: float = 2.0

    # 인증 (JWT)
    jwt_secret: str = "changeme"
    jwt_algorithm: str = "HS256"
    jwt_access_expires_min: int = 30
    jwt_refresh_expires_min: int = 10080

    # aiService(FastAPI, OCR·규칙엔진·XGBoost) 연동. 무상태·인증 없음 — 내부망 전제.
    ai_service_base_url: str = "http://localhost:5000"

    # 서류 원본 저장 위치. 이번 라운드는 로컬 디스크만 지원한다 —
    # S3 전환은 저장 경로 하나만 바꾸면 되도록 storage_uri에 파일시스템
    # 경로만 넣고 이 설정값으로 루트를 잡는다(별도 라운드에서 교체).
    document_storage_dir: str = "./data/documents"

    @cached_property
    def async_database_url(self) -> str:
        """FastAPI 용 asyncpg URL."""
        return self._with_driver("postgresql+asyncpg")

    @cached_property
    def sync_database_url(self) -> str:
        """Alembic·워커 용 psycopg URL."""
        return self._with_driver("postgresql+psycopg")

    def _with_driver(self, prefix: str) -> str:
        url = self.database_url
        for known in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(known):
                return prefix + "://" + url[len(known) :]
        raise ValueError(f"지원하지 않는 DATABASE_URL 형식입니다: {url[:20]}...")


settings = Settings()

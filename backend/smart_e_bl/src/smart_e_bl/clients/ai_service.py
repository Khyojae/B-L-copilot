"""aiService(FastAPI, OCR·규칙엔진·XGBoost) 호출 클라이언트.

워커(동기 프로세스)는 `SyncAiServiceClient`를, API(비동기 이벤트루프)는
`AsyncAiServiceClient`를 쓴다. 두 프로세스가 asyncpg/psycopg를 나눠 쓰는
것과 같은 이유 — OCR은 초 단위로 걸리는 CPU 작업이라 이벤트 루프에
올리면 API 전체가 멈춘다(worker/main.py 머리말 참고). 이 서비스는
무상태·인증 없음(내부망 전제)이라 별도 인증 헤더는 없다.
"""

from __future__ import annotations

from typing import Any

import httpx

from smart_e_bl.config import settings

# 기획안 5.1: 10페이지 문서 세트 60초(SaaS)/120초(온프레미스). 문서 1건
# 추출은 그보다 짧게 잡되 여유를 둔다 — settings.extraction_timeout_seconds 재사용.
_EXTRACT_TIMEOUT = httpx.Timeout(settings.extraction_timeout_seconds, connect=5.0)
# /verify는 OCR 없이 룰엔진+ML만 돌므로 훨씬 짧다.
# PERF_TARGET_MS.VERIFY(프론트 constants/domain.ts) = 10_000ms 예산 안에서
# 네트워크 왕복 여유를 남기고 8초로 잡는다.
_VERIFY_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


class AiServiceError(Exception):
    """aiService 호출 실패 — HTTP 오류·타임아웃을 도메인 예외 하나로 감싼다."""


class SyncAiServiceClient:
    """워커(F1 추출 파이프라인)용. 동기 psycopg 세션과 같은 스레드에서 쓴다."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or settings.ai_service_base_url

    def extract_image(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
        return self._post_file("/extract", file_bytes, filename)

    def extract_pdf(self, file_bytes: bytes, filename: str, *, page: int = 0) -> dict[str, Any]:
        return self._post_file("/extract/pdf", file_bytes, filename, params={"page": page})

    def _post_file(
        self, path: str, file_bytes: bytes, filename: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            with httpx.Client(base_url=self._base_url, timeout=_EXTRACT_TIMEOUT) as client:
                response = client.post(
                    path, params=params, files={"file": (filename, file_bytes)}
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise AiServiceError(f"aiService {path} 호출 실패: {exc}") from exc


class AsyncAiServiceClient:
    """API(F3 검증 실행)용. 비동기 이벤트 루프 안에서 non-blocking으로 호출한다."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or settings.ai_service_base_url

    async def verify(
        self,
        bl: dict[str, str | None],
        *,
        field_confidence: dict[str, float] | None = None,
        lc: dict[str, Any] | None = None,
        documents: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"bl": bl}
        if field_confidence is not None:
            payload["field_confidence"] = field_confidence
        if lc is not None:
            payload["lc"] = lc
        if documents is not None:
            payload["documents"] = documents

        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_VERIFY_TIMEOUT) as client:
                response = await client.post("/verify", json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise AiServiceError(f"aiService /verify 호출 실패: {exc}") from exc

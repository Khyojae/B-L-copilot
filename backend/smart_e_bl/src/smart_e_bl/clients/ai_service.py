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
# /impact 는 미리 만든 정합성 그래프의 이웃 조회라 즉시 끝난다.
# PERF_TARGET_MS.IMPACT_PANEL_REFRESH = 500ms — 편집기가 필드마다 부르므로
# 늦게 실패하는 것보다 빨리 실패하는 게 낫다.
_IMPACT_TIMEOUT = httpx.Timeout(2.0, connect=1.0)
# /report 는 검증 + 요약(LLM 이면 왕복 수 회) + 판정 설명(위반마다 1회).
# PERF_TARGET_MS.REPORT_RENDER = 15s, REPORT_PDF = 30s 예산 안에서 잡는다.
_REPORT_TIMEOUT = httpx.Timeout(25.0, connect=3.0)


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
    """API(F3 검증 · F4 리포트 · F5 영향분석)용. 비동기 이벤트 루프 안에서 non-blocking으로 호출한다."""

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

    async def impact(self, doc: str, field: str) -> list[dict[str, Any]]:
        """F5. `(서류 종류, 필드)` 를 고치면 함께 확인할 (서류, 필드) 목록.

        aiService 는 그래프에 없는 조합도 빈 목록으로 200 을 준다(룰이 아직 그
        필드를 다루지 않는다는 뜻) — 여기서도 그대로 빈 목록이다.
        """
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_IMPACT_TIMEOUT) as client:
                response = await client.post("/impact", json={"doc": doc, "field": field})
                response.raise_for_status()
                return response.json()["impacted"]
        except httpx.HTTPError as exc:
            raise AiServiceError(f"aiService /impact 호출 실패: {exc}") from exc

    async def report(self, payload: dict[str, Any]) -> dict[str, Any]:
        """F4 리포트 JSON(F7 판정 설명 포함). `payload` 는 /verify 입력 + submitted_documents."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_REPORT_TIMEOUT) as client:
                response = await client.post("/report", json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise AiServiceError(f"aiService /report 호출 실패: {exc}") from exc

    async def report_pdf(self, payload: dict[str, Any]) -> tuple[bytes, str | None]:
        """F4 리포트 PDF. (바이트, 업스트림 Content-Disposition) — 파일명은 aiService 가 정한다."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=_REPORT_TIMEOUT) as client:
                response = await client.post("/report/pdf", json=payload)
                response.raise_for_status()
                return response.content, response.headers.get("Content-Disposition")
        except httpx.HTTPError as exc:
            raise AiServiceError(f"aiService /report/pdf 호출 실패: {exc}") from exc

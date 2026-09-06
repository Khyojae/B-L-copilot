"""
LLM 프로바이더 어댑터.

`narrative.py` 가 요구하는 것은 하나뿐이다 — `(system, user) -> str` 콜러블.
그 규약만 맞추면 클라우드든 폐쇄망 로컬이든 같은 자리에 끼울 수 있다
(기획안 6.1 "동일 코드베이스에서 환경 설정으로 분기").

SDK 대신 REST 를 직접 호출한다. 이유는 두 가지다.

  1. 새 의존성이 없다. urllib 은 표준 라이브러리이고, 폐쇄망 온프레미스
     프로파일에서 패키지 설치가 막혀 있어도 동작한다.
  2. 벤더 SDK 는 버전마다 임포트 경로와 시그니처가 바뀐다. 요청 본문 형태는
     그보다 훨씬 안정적이다.

실패는 전부 예외로 던진다. 삼킬지 말지는 호출부(LLMNarrator)가 정한다 —
거기서 템플릿 요약으로 떨어뜨린다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

Completion = Callable[[str, str], str]

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"

# **버전을 고정한다.** `gemini-flash-latest` 같은 별칭도 동작하지만, 별칭은
# 밑에서 모델이 바뀐다 — 같은 서류에 다른 요약이 나와도 무엇이 달라졌는지
# 알 방법이 없다. 룰 카탈로그에 지문을 붙인 것과 같은 이유다.
#
# 이전 기본값 `gemini-2.5-flash` 는 **호출이 막혔다.** `list_models()` 목록에는
# 아직 보이는데 generateContent 가 404 와 함께 "no longer available to new
# users" 를 돌려준다. 즉 목록에 있다고 쓸 수 있는 것이 아니므로, 모델을 바꿀
# 때는 목록 조회가 아니라 실제 호출로 확인할 것.
DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"

# 요약은 짧다. 길게 열어두면 리포트 문단이 페이지를 넘겨 레이아웃이 깨진다.
DEFAULT_MAX_TOKENS = 600
DEFAULT_TIMEOUT = 20.0


class LLMError(RuntimeError):
    """프로바이더 호출 실패."""


# ── Gemini ───────────────────────────────────────────────────────

class GeminiCompletion:
    """Google Generative Language API (generateContent) 호출기."""

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY 가 비어 있습니다.")
        self.api_key = api_key
        self.model = model or DEFAULT_GEMINI_MODEL
        self.max_tokens = max_tokens
        self.timeout = timeout

    def __call__(self, system: str, user: str) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                # 리포트 요약은 매번 같은 사실에서 같은 문장이 나오는 편이 낫다.
                # 표현이 흔들리면 사용자가 내용이 바뀐 것으로 오해한다.
                "temperature": 0.2,
            },
        }
        url = f"{GEMINI_ENDPOINT}/models/{self.model}:generateContent"
        data = _post_json(url, payload, {"x-goog-api-key": self.api_key}, self.timeout)
        return _extract_gemini_text(data)

    def list_models(self) -> List[str]:
        """호출 가능한 모델 이름. 모델 ID 오타로 404 가 날 때 쓴다."""
        data = _post_json(
            f"{GEMINI_ENDPOINT}/models",
            None,
            {"x-goog-api-key": self.api_key},
            self.timeout,
        )
        return [
            m.get("name", "").removeprefix("models/")
            for m in data.get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]


def _extract_gemini_text(data: dict) -> str:
    """응답에서 본문만 꺼낸다.

    후보가 비는 경우가 실제로 있다 — 안전 필터에 걸리거나 토큰 한도에서
    잘렸을 때다. 그 상태로 빈 문자열을 돌려주면 리포트에 요약이 통째로
    비어 나가므로, 이유를 붙여 예외로 만든다.
    """
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback") or {}
        raise LLMError(f"응답에 후보가 없습니다. promptFeedback={feedback}")

    first = candidates[0]
    parts = (first.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise LLMError(f"본문이 비었습니다. finishReason={first.get('finishReason')}")
    return text


# ── HTTP ─────────────────────────────────────────────────────────

def _post_json(
    url: str, payload: Optional[dict], headers: Dict[str, str], timeout: float
) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        # 상태코드별로 원인이 다르고, 셋 다 발표 당일에 실제로 겪을 수 있다.
        hint = {
            400: "요청 형식 또는 모델 이름을 확인하십시오.",
            403: "API 키 권한을 확인하십시오.",
            404: "모델 이름이 잘못되었을 수 있습니다. list_models() 로 확인하십시오.",
            429: "호출 한도를 초과했습니다. 무료 등급이면 유료 전환이나 재시도가 필요합니다.",
        }.get(exc.code, "")
        raise LLMError(f"HTTP {exc.code}: {hint} {detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"네트워크 오류: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise LLMError(f"응답이 JSON 이 아닙니다: {exc}") from exc


# ── 팩토리 ───────────────────────────────────────────────────────

def build_completion(provider: str) -> Optional[Completion]:
    """환경 변수를 읽어 프로바이더를 만든다.

    키가 없으면 `None` 을 돌려준다. 예외를 던지지 않는 이유는, 키 없이
    개발·시연하는 경우가 정상 경로이기 때문이다 — 호출부가 템플릿 요약으로
    떨어진다.
    """
    name = (provider or "").strip().lower()

    if name in ("gemini", "google"):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or api_key == "changeme":
            return None
        return GeminiCompletion(
            api_key=api_key,
            model=os.getenv("LLM_MODEL") or None,
            max_tokens=int(os.getenv("LLM_MAX_TOKENS") or DEFAULT_MAX_TOKENS),
            timeout=float(os.getenv("LLM_TIMEOUT") or DEFAULT_TIMEOUT),
        )

    # 폐쇄망 프로파일(기획안 3.1 ③)은 여기에 로컬 LLM 어댑터를 추가한다.
    # OpenAI 호환 엔드포인트를 노출하는 런타임이 많으므로 REST 로 붙는다.
    return None


__all__ = [
    "Completion",
    "DEFAULT_GEMINI_MODEL",
    "GeminiCompletion",
    "LLMError",
    "build_completion",
]

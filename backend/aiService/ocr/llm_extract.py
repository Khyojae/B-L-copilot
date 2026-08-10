"""
LLM 구조화 추출 (기획안 5절 AI 기술 "LLM 구조화 추출").

## 대체가 아니라 보충이다

결정론적 파서(`field_parser`)를 LLM 으로 바꾸지 않는다. 파서는 **왜 그 값이
나왔는지** 좌표와 앵커로 설명되고 같은 입력에 같은 답을 낸다. LLM 은 둘 다
아니다. 잘 읽는 서식이 늘어나는 대신, 틀렸을 때 이유를 댈 수 없다.

그래서 파서가 **비운 자리만** 채운다. 파서가 값을 찾은 필드는 건드리지 않는다.
LLM 이 더 그럴듯한 값을 내놓더라도 마찬가지다 — 설명 가능한 값을 설명 불가능한
값으로 바꾸는 거래는 남는 장사가 아니다.

## 실패는 조용하지 않아야 한다

세 가지가 다르고, 셋 다 구분되어야 한다.

- **LLM 을 부르지 않았다** (설정 없음·채울 자리 없음) — 평소 상태다
- **불렀는데 실패했다** (키 오류·타임아웃·JSON 아님) — 파서 결과만 남는다
- **불렀고 값을 받았다** — 그 값은 `provenance` 에 `llm` 으로 남는다

`provenance` 를 남기지 않으면 사람이 화면에서 '추출된 값'을 보고 파서가 좌표로
찾은 값이라고 믿는다. LLM 이 지어낸 값과 좌표로 찾은 값은 신뢰 수준이 다르다.

## 신뢰도

파서의 앵커 경로보다 더 깎는다. 앵커는 "라벨 오른쪽에 값이 있다"는 레이아웃
가정에 기대지만, LLM 은 가정조차 검사할 수 없다. `LOW_CONFIDENCE_THRESHOLD`
아래로 떨어뜨려 **S3 편집기가 항상 사람 확인을 요구하도록** 만든다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from .types import BL_FIELD_NAMES, CRITICAL_FIELD_NAMES, BLFields, OCRResult

# LLM 이 채운 값의 신뢰도. LOW_CONFIDENCE_THRESHOLD(0.80) 아래라서 초안
# 편집기가 언제나 노란색으로 칠하고 확인을 요구한다. 그게 의도다.
LLM_CONFIDENCE = 0.55

# 프롬프트에 넣을 원문 길이 상한. B/L 한 장은 이 안에 들어간다. 넘치면
# 앞부분을 쓴다 — B/L 은 상단에 핵심 필드가 몰려 있다.
MAX_TEXT_CHARS = 6000

_SYSTEM = (
    "You extract fields from bills of lading. "
    "Answer with a single JSON object and nothing else. "
    "Use the exact text as it appears in the document. "
    "If a field is not present, use null. Never guess."
)

_PROMPT = """다음은 선하증권(B/L)에서 OCR 로 읽은 원문이다.

아래 필드만 JSON 으로 뽑아라. 원문에 없으면 null 로 둬라.
추측하지 마라 — 없는 값을 지어내면 서류 검증이 통째로 잘못된다.

필드: {fields}

원문:
---
{text}
---"""


class LLMFieldExtractor:
    """파서가 비운 필드를 LLM 으로 채운다."""

    def __init__(self, completion=None) -> None:
        """completion 을 주지 않으면 환경 설정(LLM_PROVIDER)에서 만든다."""
        self._completion = completion
        self._resolved = completion is not None

    # ── 공개 API ──────────────────────────────────────────────────

    def fill_gaps(
        self,
        fields: BLFields,
        ocr: OCRResult,
        targets: Optional[List[str]] = None,
    ) -> List[str]:
        """비어 있는 필드를 채우고, 실제로 채운 필드 이름을 돌려준다.

        targets 를 주지 않으면 **핵심 필드 중 비어 있는 것**만 노린다.
        전 필드를 매번 물으면 토큰이 늘고, 파서가 이미 잘 뽑는 자리까지
        LLM 답으로 덮어쓸 위험이 생긴다.
        """
        wanted = [
            name for name in (targets or CRITICAL_FIELD_NAMES)
            if name in BL_FIELD_NAMES and not getattr(fields, name, None)
        ]
        if not wanted:
            # 채울 자리가 없으면 부르지 않는다. 호출 비용이 그냥 낭비다.
            return []

        completion = self._get_completion()
        if completion is None:
            return []

        text = (ocr.raw_text or "").strip()
        if not text:
            return []

        try:
            raw = completion(_SYSTEM, _PROMPT.format(
                fields=", ".join(wanted), text=text[:MAX_TEXT_CHARS]
            ))
            parsed = _parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 파서 결과는 살린다
            # 삼키되 알린다. LLM 실패로 추출 전체가 죽으면 안 되지만,
            # 조용히 지나가면 "왜 필드가 비었나"를 추적할 수 없다.
            print(f"[경고] LLM 구조화 추출 실패 → 파서 결과만 사용: {exc}")
            return []

        return self._apply(fields, parsed, wanted)

    # ── 내부 ─────────────────────────────────────────────────────

    def _get_completion(self):
        if not self._resolved:
            from report.llm_providers import build_completion

            try:
                self._completion = build_completion(os.getenv("LLM_PROVIDER", ""))
            except Exception as exc:  # noqa: BLE001
                print(f"[경고] LLM 공급자 초기화 실패: {exc}")
                self._completion = None
            self._resolved = True
        return self._completion

    @staticmethod
    def _apply(
        fields: BLFields, parsed: Dict[str, object], wanted: List[str]
    ) -> List[str]:
        filled: List[str] = []
        for name in wanted:
            value = parsed.get(name)
            if value is None:
                continue
            text = str(value).strip()
            # 모델이 "null"·"N/A" 를 문자열로 돌려주는 일이 흔하다. 그걸 값으로
            # 넣으면 '없음'이 '있음'이 되어 하자 검증이 통과해 버린다.
            if not text or text.lower() in _NULLISH:
                continue
            # 파서가 그 사이 값을 넣었다면 건드리지 않는다.
            if getattr(fields, name, None):
                continue
            fields.set_field(name, text, LLM_CONFIDENCE, "llm")
            filled.append(name)
        return filled


_NULLISH = frozenset({
    "null", "none", "n/a", "na", "-", "없음", "미상", "unknown", "not found",
})

# 모델이 ```json 펜스로 감싸는 일이 흔하다. 프롬프트로 막아도 새므로 벗겨낸다.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _parse_json_object(raw: str) -> Dict[str, object]:
    """모델 응답에서 JSON 객체 하나를 꺼낸다."""
    text = _FENCE.sub("", raw or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 앞뒤에 설명 문장이 붙은 경우. 첫 { 부터 마지막 } 까지 잘라 재시도한다.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"JSON 객체를 찾을 수 없습니다: {text[:120]!r}")
        parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise ValueError(f"JSON 객체가 아닙니다: {type(parsed).__name__}")
    return parsed


__all__ = ["LLMFieldExtractor", "LLM_CONFIDENCE", "MAX_TEXT_CHARS"]

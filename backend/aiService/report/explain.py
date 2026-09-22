"""
AI 판정 설명 (기획안 F7).

보고서(`붙임3_...개발보고서 수정17`) 원문: "조문 인용 결합 + 인용 무결성
검증기", "조문 원문과 현재값, 기대값, 근거 이벤트를 컨텍스트로 조립해 3단
문장을 한국어 영어 동일 근거로 생성", "인용 ID 대조 검증기와 2회 재생성
실패 시 템플릿 폴백, 판정 30건 회귀 평가로 인용 무결성 통과율 확보".

## 새 검증기를 만들지 않는다

`report.integrity.check_narrative(report, *texts)` 는 이미 리포트 전체를
근거 삼아 텍스트의 수치·룰ID·조문을 검사한다. 설명문이 인용해도 되는
값은 정확히 "이 판정 결과가 가진 값"이므로, 새 검증기 대신 **완성된
`Report` 객체를 그대로** 넘긴다.

## "현재값·기대값"도 새로 계산하지 않는다

`ruleEngine.checks`/`cross_doc` 는 위반을 만들 때 이미 `observed` 에
`bl`·`lc`(또는 `left`·`right`) 쌍을 담는다 — 이것이 F7 이 말하는 "현재값과
기대값"이다. 계산이 아니라 이미 있는 값을 문장으로 옮기는 일만 남는다.

## 템플릿(영어)이 한국어보다 간결한 이유

`rules.yaml`/`cross_rules.yaml`의 `title`·`message`·`remedy`는 한국어
산문이다. LLM 없이 동작해야 하는 템플릿 경로(폐쇄망 프로파일의 필수
경로)에서 이 산문을 영어로 억지 번역하면 틀린 번역이 사실처럼 실린다.
그래서 영어판은 산문을 옮기지 않고 rule_id·source(조문은 원래 로마자
표기)·필드명·observed 값처럼 **언어중립 데이터만**으로 조립한다. 두
언어가 같은 사실을 담지만 영어판이 더 간결한 것은 의도한 트레이드오프다
— narrative.TemplateNarrator 가 "템플릿은 딱딱하지만 틀리지 않는다"고
남긴 것과 같은 이유.

LLM 경로는 이 제약이 없다 — 프롬프트가 한국어·영어 산문을 함께 요청하고,
결과를 `check_narrative` 로 검사해 지어낸 내용을 막는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from .integrity import check_narrative
from .model import Report, RiskItem

# 재생성 시도 횟수. narrative.MAX_NARRATIVE_ATTEMPTS 와 같은 값 — 기획안
# 5.7 이 "2회 실패 시 템플릿으로 대체한다"로 정한 수다.
MAX_EXPLANATION_ATTEMPTS = 2

_OBSERVED_LABELS_KO = {
    "bl": "서류값",
    "lc": "신용장 지정값",
    "left": "왼쪽 서류값",
    "right": "오른쪽 서류값",
}
_OBSERVED_LABELS_EN = {
    "bl": "document value",
    "lc": "L/C requirement",
    "left": "left document value",
    "right": "right document value",
}


@dataclass
class Explanation:
    """위반 1건에 대한 AI 판정 설명."""

    rule_id: str
    source: str
    body_ko: str
    body_en: str
    origin: str  # template | llm

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "source": self.source,
            "body_ko": self.body_ko,
            "body_en": self.body_en,
            "origin": self.origin,
        }


class Explainer(Protocol):
    """RiskItem + 전체 리포트(허용 집합) → 설명."""

    def explain(self, risk: RiskItem, report: Report) -> Explanation: ...


class TemplateExplainer:
    """LLM 없이 동작하는 기본 설명기."""

    name = "template"

    def explain(self, risk: RiskItem, report: Report) -> Explanation:
        observed_ko = ", ".join(
            f"{_OBSERVED_LABELS_KO.get(k, k)}={v}" for k, v in risk.observed.items() if v
        )
        observed_en = ", ".join(
            f"{_OBSERVED_LABELS_EN.get(k, k)}={v}" for k, v in risk.observed.items() if v
        )

        body_ko = (
            f"[{risk.rule_id}] {risk.source} — {risk.message}"
            + (f" (확인된 값: {observed_ko})" if observed_ko else "")
        )
        body_en = (
            f"[{risk.rule_id}] Under {risk.source or 'the applicable rule'}, "
            f"field(s) {', '.join(risk.fields) or risk.rule_id} were flagged as "
            f"{risk.severity_label}."
            + (f" Observed: {observed_en}." if observed_en else "")
        )
        return Explanation(
            rule_id=risk.rule_id,
            source=risk.source,
            body_ko=body_ko,
            body_en=body_en,
            origin=self.name,
        )


_SYSTEM_PROMPT = """당신은 무역 서류 심사를 돕는 조수입니다.
주어진 하자 판정 1건을 실무자에게 설명하는 문장을 한국어와 영어로 각각
작성하십시오. 두 언어는 같은 근거(조문·현재값·기대값)를 담아야 합니다.

규칙:
- 주어진 조문·필드·값 외에 어떤 사실도 새로 만들지 마십시오.
- 각 언어는 "① 근거 조문 → ② 현재값과 기대값(무엇이 어떻게 다른가) → ③ 결론"
  3단으로 구성한 한두 문장으로 쓰십시오.
- ③ 결론은 심사 결과를 단정하지 마십시오. 심사는 은행이 합니다. "하자입니다"가
  아니라 "하자로 판정될 위험이 있습니다"처럼 위험과 그 근거만 서술하십시오.
  영어도 같습니다 — "is discrepant" 같은 단정 대신 "the bank may refuse the
  document as discrepant" 처럼 가능성으로 쓰십시오.
- 첫 줄에 한국어, 둘째 줄에 영어를 쓰십시오. 다른 텍스트를 덧붙이지 마십시오.
"""


class LLMExplainer:
    """LLM 설명기. 실패하면 템플릿으로 떨어진다 (narrative.LLMNarrator 와 같은 패턴)."""

    name = "llm"

    def __init__(self, complete, fallback: Optional[Explainer] = None) -> None:
        self._complete = complete
        self._fallback = fallback or TemplateExplainer()

    def explain(self, risk: RiskItem, report: Report) -> Explanation:
        facts = _render_facts(risk)
        last: Optional[str] = None

        for attempt in range(MAX_EXPLANATION_ATTEMPTS):
            system = _SYSTEM_PROMPT if last is None else _retry_prompt(last)
            try:
                text = self._complete(system, facts)
            except Exception:  # noqa: BLE001 - 설명 실패가 리포트를 막지 않는다
                return self._fallback.explain(risk, report)

            lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
            if len(lines) < 2:
                return self._fallback.explain(risk, report)

            body_ko, body_en = lines[0], lines[1]
            result = check_narrative(report, body_ko, body_en)
            if result.ok:
                return Explanation(
                    rule_id=risk.rule_id,
                    source=risk.source,
                    body_ko=body_ko,
                    body_en=body_en,
                    origin=self.name,
                )

            last = result.describe()
            print(
                f"[aiService] 경고: 판정 설명 인용 무결성 검사 실패 "
                f"({attempt + 1}/{MAX_EXPLANATION_ATTEMPTS}) — {last}"
            )

        return self._fallback.explain(risk, report)


def _retry_prompt(problem: str) -> str:
    return (
        _SYSTEM_PROMPT
        + "\n직전 작성이 검사에 걸렸습니다: "
        + problem
        + "\n아래 사실 목록에 있는 값만 쓰십시오. 없는 값은 문장에서 빼십시오.\n"
    )


def _render_facts(risk: RiskItem) -> str:
    lines = [
        f"룰 ID: {risk.rule_id}",
        f"심각도: {risk.severity_label}",
        f"근거 조문: {risk.source}",
        f"제목: {risk.title}",
        f"판정 메시지: {risk.message}",
    ]
    if risk.fields:
        lines.append(f"관련 필드: {', '.join(risk.fields)}")
    for key, value in risk.observed.items():
        if value:
            lines.append(f"관측값[{key}]: {value}")
    return "\n".join(lines)


def default_explainer() -> Explainer:
    """narrative.default_narrator() 와 같은 분기 — 키가 없으면 템플릿."""
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not provider or provider == "template":
        return TemplateExplainer()

    try:
        from .llm_providers import build_completion  # 지연 임포트
    except ImportError:
        return TemplateExplainer()

    complete = build_completion(provider)
    if complete is None:
        return TemplateExplainer()
    return LLMExplainer(complete)


def apply_explanations(report: Report, explainer: Optional[Explainer] = None) -> Report:
    """리포트의 위반 목록에 설명을 채운다."""
    chosen = explainer or default_explainer()
    report.explanations = [chosen.explain(risk, report) for risk in report.risks]
    return report


__all__ = [
    "Explainer",
    "Explanation",
    "LLMExplainer",
    "MAX_EXPLANATION_ATTEMPTS",
    "TemplateExplainer",
    "apply_explanations",
    "default_explainer",
]

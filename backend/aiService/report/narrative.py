"""
리포트 산문 요약 (기획안 F4 "F3 결과 종합 + LLM 리포트 생성").

LLM 은 **수치를 만들지 않는다.** 이미 계산된 리포트를 사람이 읽을 문장으로
옮기기만 한다. 확률·기한·건수를 LLM 이 생성하면 리포트의 숫자와 본문이
어긋나도 아무도 못 잡는다.

LLM 이 없거나(키 미설정) 실패해도 템플릿 요약이 나온다. 발표 중 외부 API
한도에 걸려 리포트가 통째로 비는 상황을 막기 위한 것이다.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, Tuple

from .model import Report


class Narrator(Protocol):
    """리포트 → (한 줄 요약, 문단 요약)."""

    def summarize(self, report: Report) -> Tuple[str, str]: ...


class TemplateNarrator:
    """LLM 없이 동작하는 기본 요약기."""

    name = "template"

    def summarize(self, report: Report) -> Tuple[str, str]:
        critical = report.counts.get("critical", 0)
        warning = report.counts.get("warning", 0)
        info = report.counts.get("info", 0)

        if critical:
            headline = f"제출 전 정정이 필요한 치명 하자 {critical}건이 발견되었습니다."
        elif warning:
            headline = f"하자로 지적될 수 있는 항목 {warning}건이 있습니다."
        elif report.unchecked:
            headline = "검사한 항목에서는 하자가 발견되지 않았습니다."
        else:
            headline = "하자로 볼 만한 사항이 발견되지 않았습니다."

        parts = [
            f"위험도는 '{report.risk_level}'이며, 규칙 기반 위험 점수는 "
            f"{report.defect_probability:.2f} 입니다."
        ]
        found = []
        if critical:
            found.append(f"치명 {critical}건")
        if warning:
            found.append(f"경고 {warning}건")
        if info:
            found.append(f"참고 {info}건")
        if found:
            parts.append("검출 내역은 " + ", ".join(found) + " 입니다.")

        if report.deadline and report.deadline.effective_due:
            d = report.deadline
            if d.is_overdue:
                parts.append(f"제시기한({d.effective_due})이 이미 경과했습니다.")
            else:
                parts.append(
                    f"제시기한은 {d.effective_due}이며 {d.days_left}일 남았습니다."
                )

        if report.unchecked:
            parts.append(
                f"자료 부족으로 검사하지 못한 항목이 {len(report.unchecked)}건 있습니다."
            )

        return headline, " ".join(parts)


# LLM 에 넘길 지시. 숫자를 새로 만들지 말라는 제약이 핵심이다.
_SYSTEM_PROMPT = """당신은 무역 서류 심사를 돕는 조수입니다.
주어진 검증 결과를 무역 실무자가 읽을 한국어 문장으로 옮기십시오.

규칙:
- 주어진 수치(확률·건수·날짜) 외에 어떤 숫자도 만들지 마십시오.
- 새로운 하자나 조문을 추론하지 마십시오. 주어진 항목만 다루십시오.
- 첫 줄은 한 문장 요약, 이후는 3~4문장의 문단으로 작성하십시오.
- 단정적 예측을 피하고 '예상됩니다', '가능성이 있습니다'로 서술하십시오.
"""


class LLMNarrator:
    """LLM 요약기. 실패하면 템플릿으로 떨어진다.

    프로바이더 구현은 주입받는다(기획안 6.1 '동일 코드베이스에서 환경 설정
    으로 분기' — SaaS 클라우드 LLM 과 폐쇄망 로컬 LLM 을 같은 자리에 끼운다).
    """

    name = "llm"

    def __init__(self, complete, fallback: Optional[Narrator] = None) -> None:
        # complete: (system: str, user: str) -> str
        self._complete = complete
        self._fallback = fallback or TemplateNarrator()

    def summarize(self, report: Report) -> Tuple[str, str]:
        try:
            text = self._complete(_SYSTEM_PROMPT, _render_facts(report))
        except Exception:  # noqa: BLE001 - 요약 실패가 리포트를 막지 않는다
            return self._fallback.summarize(report)

        lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
        if not lines:
            return self._fallback.summarize(report)
        return lines[0], " ".join(lines[1:]) or lines[0]


def _render_facts(report: Report) -> str:
    """LLM 에 넘길 사실 목록. 리포트에 있는 것만 넣는다."""
    lines = [
        f"위험도: {report.risk_level}",
        f"위험 점수: {report.defect_probability:.2f} (산출: {report.model})",
        f"심각도 분포: {report.counts}",
    ]
    if report.deadline and report.deadline.effective_due:
        lines.append(
            f"제시기한: {report.deadline.effective_due} "
            f"(남은 일수 {report.deadline.days_left})"
        )
    for risk in report.risks:
        lines.append(f"[{risk.severity_label}] {risk.title} — {risk.message} ({risk.source})")
    if report.unchecked:
        lines.append(f"미검사 항목 {len(report.unchecked)}건")
    return "\n".join(lines)


def default_narrator() -> Narrator:
    """환경 설정에 따라 요약기를 고른다.

    키가 없으면 조용히 템플릿을 쓴다 — 개발·시연 환경에서 키 없이도
    리포트가 완성되어야 하기 때문이다.
    """
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not provider or provider == "template":
        return TemplateNarrator()

    try:
        from .llm_providers import build_completion  # 지연 임포트
    except ImportError:
        return TemplateNarrator()

    complete = build_completion(provider)
    if complete is None:
        return TemplateNarrator()
    return LLMNarrator(complete)


def apply_narrative(report: Report, narrator: Optional[Narrator] = None) -> Report:
    """리포트에 요약을 채워 넣는다."""
    narrator = narrator or default_narrator()
    report.headline, report.narrative = narrator.summarize(report)
    report.narrative_source = getattr(narrator, "name", "template")
    return report


__all__ = [
    "LLMNarrator",
    "Narrator",
    "TemplateNarrator",
    "apply_narrative",
    "default_narrator",
]

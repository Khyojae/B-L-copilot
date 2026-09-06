"""
F4 선제 대응 리포트 자료구조.

기획안 5.2 가 규정한 5개 구성을 그대로 dataclass 로 옮긴 것이다.

  ① 요약(하자 확률·심각도 분포)
  ② 항목별 리스크와 근거 조문
  ③ 누락 서류·제출 기한 체크리스트
  ④ 수정 권고(우선순위순)
  ⑤ 예상 심사 결과 시나리오

여기에 기획안에 없는 항목을 하나 더 둔다 — **미검사 항목**. 검사하지 못한
룰을 리포트에서 감추면 사용자는 '검사했고 문제없다'로 읽는다. 제출 전
예방을 표방하는 문서가 그 오해를 만들면 안 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from ruleEngine.deadline import PresentationDeadline


@dataclass
class RiskItem:
    """② 항목별 리스크 1건. Violation 을 리포트 표현으로 옮긴 것."""

    rule_id: str
    severity: str          # critical | warning | info
    severity_label: str    # 치명 | 경고 | 참고
    title: str
    message: str
    source: str            # 근거 조문
    fields: List[str] = field(default_factory=list)
    observed: Dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class ChecklistItem:
    """③ 체크리스트 1행."""

    label: str
    done: bool
    detail: str = ""


@dataclass
class Recommendation:
    """④ 수정 권고 1건. 우선순위는 목록 순서로 표현한다."""

    order: int
    severity_label: str
    action: str
    target_fields: List[str] = field(default_factory=list)
    source: str = ""
    # 정정 영향(F5) 요약. 이 권고의 대상 필드를 고치면 함께 확인해야 할
    # 다른 서류·필드를 한 줄씩 담는다. `ruleEngine.impact.ConsistencyGraph`
    # 가 없으면(그래프를 안 넘긴 호출) 빈 목록으로 남는다 — 이전처럼
    # 동작해야 하는 기존 호출부를 깨지 않기 위해서다.
    impact: List[str] = field(default_factory=list)


# 제출 기한은 **룰엔진이 계산한다.** 여기서 자체 정의를 들고 있으면 같은 조문
# (UCP 600 Art.14(c))에서 나온 같은 날짜를 두 곳이 각자 계산하게 되고, 한쪽만
# 고쳤을 때 리포트에 그럴듯한 틀린 날짜가 찍힌다. 이름만 리포트 어휘로 남긴다.
Deadline = PresentationDeadline


@dataclass
class UncheckedItem:
    """검사하지 못한 항목."""

    rule_id: str
    title: str
    reason: str


@dataclass
class Report:
    """리포트 1건."""

    # 표지
    bl_no: Optional[str] = None
    lc_no: Optional[str] = None
    generated_at: Optional[date] = None

    # ① 요약
    defect_probability: float = 0.0
    counts: Dict[str, int] = field(default_factory=dict)
    model: str = "rules-v1"
    headline: str = ""       # 한 줄 요약 (LLM 또는 템플릿)
    narrative: str = ""      # 문단 요약 (LLM 또는 템플릿)

    # ② ~ ⑤
    risks: List[RiskItem] = field(default_factory=list)
    checklist: List[ChecklistItem] = field(default_factory=list)
    deadline: Optional[Deadline] = None
    recommendations: List[Recommendation] = field(default_factory=list)
    outlook: str = ""            # 예상 심사 결과
    outlook_detail: str = ""

    # ① 요약 — 판정 보류 (기획안 v2 5.3 · 5.4)
    #
    # `defect_probability` 는 보류된 룰을 뺀 값이다. 보류가 전체 필드의 20%
    # 를 넘으면 그 점 확률을 대표값으로 쓰지 않고 `probability_range` 를
    # 쓴다 — 5.4 가 "확률 대신 범위를 제시한다"로 정했다.
    #
    # 범위를 항상 계산해 두고 표기만 가르는 이유는, 화면이 보류 여부와
    # 무관하게 같은 필드를 읽게 하기 위해서다. 보류가 없으면 두 값이 같다.
    probability_range: tuple = (0.0, 0.0)
    hold_ratio: float = 0.0
    held_field_count: int = 0
    # 비어 있지 않으면 요약 상단에 띄운다(5.4 "신뢰도 제한 경고").
    confidence_warning: str = ""

    @property
    def probability_is_ranged(self) -> bool:
        """확률 대신 범위를 써야 하는 상태인지."""
        return bool(self.confidence_warning)

    # 부록
    unchecked: List[UncheckedItem] = field(default_factory=list)
    # 판정을 보류한 룰. `unchecked`(평가불가)와 나눠 두는 이유는
    # `ruleEngine.types.HeldRule` 주석에 있다 — 사용자가 할 일이 다르다.
    held: List[UncheckedItem] = field(default_factory=list)
    narrative_source: str = "template"  # template | llm

    # 판정 근거의 신원(`Verdict.catalog`). 리포트는 조문을 인용하므로
    # **어느 카탈로그의 조문인지**가 인용의 일부다. 룰이 개정된 뒤 옛 리포트를
    # 다시 읽을 때, 이 값이 없으면 지금 카탈로그로 쓴 것처럼 읽힌다.
    rule_catalog: Optional[Dict[str, str]] = None

    # 서류 간 정합성 카탈로그의 신원. 서류 세트로 검증한 경우에만 채워진다.
    # `None` 이면 서류 간 룰을 **돌리지 않았다**는 뜻이고, 이 리포트의 위반
    # 목록에 서류 간 저촉이 없는 것은 그래서다 — 저촉이 없어서가 아니다.
    cross_rule_catalog: Optional[Dict[str, str]] = None

    # F7 AI 판정 설명. `report.explain.apply_explanations()` 가 채운다.
    # `narrative`(요약)와 나누는 이유는 대상이 다르기 때문이다 — narrative
    # 는 리포트 전체를 한 문단으로 묶고, explanations 는 위반 1건마다
    # "조문 근거 + 현재값 + 기대값"을 따로 서술한다. 하나로 합치면 위반이
    # 여러 건일 때 어느 문장이 어느 위반의 근거인지 되짚을 수 없다.
    explanations: List[Any] = field(default_factory=list)

    @property
    def risk_level(self) -> str:
        """표지에 크게 찍는 등급."""
        if self.counts.get("critical"):
            return "높음"
        if self.counts.get("warning"):
            return "보통"
        return "낮음"

    def to_dict(self) -> dict:
        return {
            "bl_no": self.bl_no,
            "lc_no": self.lc_no,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "summary": {
                "defect_probability": self.defect_probability,
                "probability_range": list(self.probability_range),
                # 화면은 이 값으로 표기를 가른다. False 면 점 확률을,
                # True 면 범위를 그리고 경고를 요약 상단에 띄운다.
                "probability_is_ranged": self.probability_is_ranged,
                "confidence_warning": self.confidence_warning,
                "hold_ratio": self.hold_ratio,
                "held_field_count": self.held_field_count,
                "risk_level": self.risk_level,
                "counts": self.counts,
                "model": self.model,
                "headline": self.headline,
                "narrative": self.narrative,
                "narrative_source": self.narrative_source,
                "rule_catalog": self.rule_catalog,
                "cross_rule_catalog": self.cross_rule_catalog,
            },
            "risks": [r.__dict__ for r in self.risks],
            "checklist": [c.__dict__ for c in self.checklist],
            "deadline": (
                self.deadline.to_dict()
                if self.deadline
                else None
            ),
            "recommendations": [r.__dict__ for r in self.recommendations],
            "outlook": {"verdict": self.outlook, "detail": self.outlook_detail},
            "unchecked": [u.__dict__ for u in self.unchecked],
            "held": [h.__dict__ for h in self.held],
            "explanations": [e.to_dict() for e in self.explanations],
        }


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


__all__ = [
    "ChecklistItem",
    "Deadline",
    "Recommendation",
    "Report",
    "RiskItem",
    "UncheckedItem",
]

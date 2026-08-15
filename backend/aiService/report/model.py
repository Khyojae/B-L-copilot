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
from typing import Dict, List, Optional


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


@dataclass
class Deadline:
    """제출 기한 계산 결과."""

    presentation_due: Optional[date] = None   # 제시기한
    expiry: Optional[date] = None             # 신용장 유효기일(31D)
    effective_due: Optional[date] = None      # 둘 중 이른 날
    days_left: Optional[int] = None
    basis: str = ""                           # 어떻게 계산했는지

    @property
    def is_overdue(self) -> bool:
        return self.days_left is not None and self.days_left < 0


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

    # 부록
    unchecked: List[UncheckedItem] = field(default_factory=list)
    narrative_source: str = "template"  # template | llm

    # 판정 근거의 신원(`Verdict.catalog`). 리포트는 조문을 인용하므로
    # **어느 카탈로그의 조문인지**가 인용의 일부다. 룰이 개정된 뒤 옛 리포트를
    # 다시 읽을 때, 이 값이 없으면 지금 카탈로그로 쓴 것처럼 읽힌다.
    rule_catalog: Optional[Dict[str, str]] = None

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
                "risk_level": self.risk_level,
                "counts": self.counts,
                "model": self.model,
                "headline": self.headline,
                "narrative": self.narrative,
                "narrative_source": self.narrative_source,
                "rule_catalog": self.rule_catalog,
            },
            "risks": [r.__dict__ for r in self.risks],
            "checklist": [c.__dict__ for c in self.checklist],
            "deadline": (
                {
                    "presentation_due": _iso(self.deadline.presentation_due),
                    "expiry": _iso(self.deadline.expiry),
                    "effective_due": _iso(self.deadline.effective_due),
                    "days_left": self.deadline.days_left,
                    "is_overdue": self.deadline.is_overdue,
                    "basis": self.deadline.basis,
                }
                if self.deadline
                else None
            ),
            "recommendations": [r.__dict__ for r in self.recommendations],
            "outlook": {"verdict": self.outlook, "detail": self.outlook_detail},
            "unchecked": [u.__dict__ for u in self.unchecked],
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

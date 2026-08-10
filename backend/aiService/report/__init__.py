"""F4 선제 대응 서류 분석 리포트.

Verdict(F3) → Report → PDF. 골격·수치는 결정론이고 LLM 은 산문 요약만 맡는다.
"""

from .builder import build_report
from .model import (
    ChecklistItem,
    Deadline,
    Recommendation,
    Report,
    RiskItem,
    UncheckedItem,
)
from .narrative import (
    LLMNarrator,
    Narrator,
    TemplateNarrator,
    apply_narrative,
    default_narrator,
)
from .pdf import render_pdf

__all__ = [
    "ChecklistItem",
    "Deadline",
    "LLMNarrator",
    "Narrator",
    "Recommendation",
    "Report",
    "RiskItem",
    "TemplateNarrator",
    "UncheckedItem",
    "apply_narrative",
    "build_report",
    "default_narrator",
    "render_pdf",
]

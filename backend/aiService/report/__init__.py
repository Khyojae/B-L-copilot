"""F4 선제 대응 서류 분석 리포트.

Verdict(F3) → Report → PDF. 골격·수치는 결정론이고 LLM 은 산문 요약만 맡는다.
"""

from .builder import build_report
from .explain import (
    Explainer,
    Explanation,
    LLMExplainer,
    TemplateExplainer,
    apply_explanations,
    default_explainer,
)
from .integrity import IntegrityReport, check_narrative
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
    Summary,
    TemplateNarrator,
    apply_narrative,
    default_narrator,
)
from .pdf import render_pdf
from .share import (
    DEFAULT_TTL_SECONDS,
    ExpiredShareToken,
    ShareTokenError,
    ShareTokenTooLarge,
)

__all__ = [
    "ChecklistItem",
    "DEFAULT_TTL_SECONDS",
    "Deadline",
    "Explainer",
    "Explanation",
    "ExpiredShareToken",
    "IntegrityReport",
    "ShareTokenError",
    "ShareTokenTooLarge",
    "LLMExplainer",
    "LLMNarrator",
    "check_narrative",
    "Narrator",
    "Recommendation",
    "Report",
    "RiskItem",
    "Summary",
    "TemplateExplainer",
    "TemplateNarrator",
    "UncheckedItem",
    "apply_explanations",
    "apply_narrative",
    "build_report",
    "default_explainer",
    "default_narrator",
    "render_pdf",
]

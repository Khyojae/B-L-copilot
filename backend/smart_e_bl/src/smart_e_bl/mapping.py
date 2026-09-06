"""aiService ↔ DB ↔ 프론트 사이의 이름표 변환.

같은 개념(신뢰도 등급·심각도)이 세 곳에서 각각 다른 대소문자/단어로
불린다 — 각자 독립적으로 발전해서 생긴 어긋남이다. 정정하지 않고 여기
한 곳에서만 변환한다(값 자체를 아무 데도 새로 짓지 않음).

| 개념 | aiService | DB(smart_e_bl) | 프론트(domain.ts) |
|---|---|---|---|
| 신뢰도 | confirmed/recommended/required/undetected | CONFIRMED/REVIEW_SUGGESTED/REVIEW_REQUIRED/NOT_FOUND | CONFIRMED/ADVISORY/REQUIRED/NOT_FOUND |
| 심각도 | critical/warning/info | CRITICAL/WARNING/INFO | Critical/Warning/Info |
"""

from __future__ import annotations

from smart_e_bl.models.enums import ConfidenceGrade, Severity

# aiService DraftField.grade (소문자) → DB ConfidenceGrade
AI_GRADE_TO_DB: dict[str, ConfidenceGrade] = {
    "confirmed": ConfidenceGrade.CONFIRMED,
    "recommended": ConfidenceGrade.REVIEW_SUGGESTED,
    "required": ConfidenceGrade.REVIEW_REQUIRED,
    "undetected": ConfidenceGrade.NOT_FOUND,
}

# DB ConfidenceGrade → 프론트 domain.ts ConfidenceGrade 리터럴
DB_GRADE_TO_FRONTEND: dict[ConfidenceGrade, str] = {
    ConfidenceGrade.CONFIRMED: "CONFIRMED",
    ConfidenceGrade.REVIEW_SUGGESTED: "ADVISORY",
    ConfidenceGrade.REVIEW_REQUIRED: "REQUIRED",
    ConfidenceGrade.NOT_FOUND: "NOT_FOUND",
}

# aiService Violation.severity(소문자) → DB Severity
AI_SEVERITY_TO_DB: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "info": Severity.INFO,
}

# DB Severity → 프론트 domain.ts Severity 리터럴
DB_SEVERITY_TO_FRONTEND: dict[Severity, str] = {
    Severity.CRITICAL: "Critical",
    Severity.WARNING: "Warning",
    Severity.INFO: "Info",
}

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

from smart_e_bl.models.enums import ConfidenceGrade, DocumentType, ExtractorKind, Severity

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

# DB ExtractorKind → 프론트 domain.ts FieldValue.extractor 리터럴.
# 프론트 타입에는 'manual'이 없다 — 이번 라운드는 자동 추출만 다루므로
# 실제로는 걸리지 않지만, 누락 시 조용히 잘못된 값을 내보내지 않도록
# 명시적으로 매핑해 둔다(모르는 값이면 KeyError로 드러나게).
DB_EXTRACTOR_TO_FRONTEND: dict[ExtractorKind, str] = {
    ExtractorKind.RULE: "rule",
    ExtractorKind.OCR_LLM: "ocr+llm",
    ExtractorKind.JSON: "json",
    ExtractorKind.MANUAL: "rule",  # 프론트에 대응 값 없음 — 임시로 rule 취급
}

# DB DocumentType(9종, 세분화) → 프론트 domain.ts DocumentKind(6종, 개략).
# 프론트가 아직 다루지 않는 세부 종류(보험증권·원산지증명·수출신고필증 등)는
# UNKNOWN으로 내린다 — 없는 탭을 만들어 보여주는 것보다 "분류 전"이 낫다.
DB_DOC_TYPE_TO_FRONTEND: dict[DocumentType, str] = {
    DocumentType.BL_DRAFT: "BL",
    DocumentType.BL_COPY: "BL",
    DocumentType.SI: "SI",
    DocumentType.COMMERCIAL_INVOICE: "INVOICE",
    DocumentType.PACKING_LIST: "PACKING",
    DocumentType.LC_MT700: "LC",
    DocumentType.INSURANCE_POLICY: "UNKNOWN",
    DocumentType.CERTIFICATE_OF_ORIGIN: "UNKNOWN",
    DocumentType.EXPORT_DECLARATION: "UNKNOWN",
    DocumentType.OTHER: "UNKNOWN",
}

# 업로드 시 프론트 DocumentKind → DB DocumentType(역방향).
# 'BL'은 DB에 BL_DRAFT/BL_COPY 두 종류가 있는데, 이 서비스는 제출 전
# 초안 검증이 목적이므로 업로드는 항상 BL_DRAFT로 받는다.
FRONTEND_DOC_KIND_TO_DB: dict[str, DocumentType] = {
    "BL": DocumentType.BL_DRAFT,
    "INVOICE": DocumentType.COMMERCIAL_INVOICE,
    "PACKING": DocumentType.PACKING_LIST,
    "LC": DocumentType.LC_MT700,
    "SI": DocumentType.SI,
    "UNKNOWN": DocumentType.OTHER,
}

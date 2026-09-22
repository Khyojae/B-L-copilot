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

from smart_e_bl.models.enums import (
    ConfidenceGrade,
    DocumentType,
    ExtractorKind,
    Severity,
)

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

# ── aiService 서류 종류(한국어 상수) ─────────────────────────────
# aiService 는 서류 종류를 한국어 문자열로 식별한다(ocr/doc_types.py ·
# ruleEngine/cross_doc.py 의 BILL_OF_LADING="선하증권" 등). /verify·/report 의
# `documents` 키와 /impact 의 `doc` 값이 이 문자열이다. 여기서만 변환한다.
AI_DOC_BILL_OF_LADING = "선하증권"
AI_DOC_COMMERCIAL_INVOICE = "상업송장"
AI_DOC_PACKING_LIST = "포장명세서"
AI_DOC_LC = "신용장"

# DB DocumentType → aiService 서류 종류. 정합성 룰이 다루지 않는 종류
# (보험증권·원산지증명 등)는 빠져 있다 — 그 서류의 필드는 /report 에 싣지 않는다.
DB_DOC_TYPE_TO_AI: dict[DocumentType, str] = {
    DocumentType.BL_DRAFT: AI_DOC_BILL_OF_LADING,
    DocumentType.BL_COPY: AI_DOC_BILL_OF_LADING,
    DocumentType.COMMERCIAL_INVOICE: AI_DOC_COMMERCIAL_INVOICE,
    DocumentType.PACKING_LIST: AI_DOC_PACKING_LIST,
    DocumentType.LC_MT700: AI_DOC_LC,
}

# 프론트 DocumentKind ↔ aiService 서류 종류. /impact 요청·응답의 서류 표기.
FRONTEND_DOC_KIND_TO_AI: dict[str, str] = {
    "BL": AI_DOC_BILL_OF_LADING,
    "INVOICE": AI_DOC_COMMERCIAL_INVOICE,
    "PACKING": AI_DOC_PACKING_LIST,
    "LC": AI_DOC_LC,
}
AI_DOC_TO_FRONTEND_KIND: dict[str, str] = {v: k for k, v in FRONTEND_DOC_KIND_TO_AI.items()}

# DB DocumentType → 신용장 46A 대조용 영문 서류명. aiService report/builder.py
# `_checklist` 가 46A 원문(예: "COMMERCIAL INVOICE IN 3 COPIES")과 영숫자만 남긴
# 부분 일치로 비교하므로 46A 가 쓰는 관용 영문명을 그대로 쓴다.
DB_DOC_TYPE_TO_SUBMITTED_NAME: dict[DocumentType, str] = {
    DocumentType.BL_DRAFT: "BILL OF LADING",
    DocumentType.BL_COPY: "BILL OF LADING",
    DocumentType.COMMERCIAL_INVOICE: "COMMERCIAL INVOICE",
    DocumentType.PACKING_LIST: "PACKING LIST",
    DocumentType.INSURANCE_POLICY: "INSURANCE POLICY",
    DocumentType.CERTIFICATE_OF_ORIGIN: "CERTIFICATE OF ORIGIN",
    DocumentType.EXPORT_DECLARATION: "EXPORT DECLARATION",
}

# ── 필드 코드 ↔ aiService 필드명 ──────────────────────────────────
# DB field_definition.code 는 "BL.BL_NO" 처럼 서류 접두어 + 대문자이고,
# aiService 는 "bl_no" 처럼 소문자 snake_case 다(ocr/types.py BLFields,
# ocr/doc_types.py DocumentSpec.fields). 이름이 1:1 로 대응하지 않는 것도
# 있어(VESSEL_VOYAGE ↔ vessel, ONBOARD_DATE ↔ on_board_date) 규칙 변환 대신
# 표로 둔다. 표에 없는 코드는 aiService 룰이 쓰지 않는 필드라 /report 에서
# 뺀다 — 모르는 키를 넘겨서 조용히 무시되게 두는 것보다 여기서 빠진 게 보인다.
DB_FIELD_CODE_TO_AI: dict[str, tuple[str, str]] = {
    # 선하증권
    "BL.BL_NO": (AI_DOC_BILL_OF_LADING, "bl_no"),
    "BL.SHIPPER": (AI_DOC_BILL_OF_LADING, "shipper"),
    "BL.CONSIGNEE": (AI_DOC_BILL_OF_LADING, "consignee"),
    "BL.NOTIFY_PARTY": (AI_DOC_BILL_OF_LADING, "notify_party"),
    "BL.VESSEL_VOYAGE": (AI_DOC_BILL_OF_LADING, "vessel"),
    "BL.PORT_OF_LOADING": (AI_DOC_BILL_OF_LADING, "port_of_loading"),
    "BL.PORT_OF_DISCHARGE": (AI_DOC_BILL_OF_LADING, "port_of_discharge"),
    "BL.DESCRIPTION_OF_GOODS": (AI_DOC_BILL_OF_LADING, "description_of_goods"),
    "BL.GROSS_WEIGHT": (AI_DOC_BILL_OF_LADING, "gross_weight"),
    "BL.MEASUREMENT": (AI_DOC_BILL_OF_LADING, "measurement"),
    "BL.DATE_OF_ISSUE": (AI_DOC_BILL_OF_LADING, "date_of_issue"),
    "BL.PLACE_OF_ISSUE": (AI_DOC_BILL_OF_LADING, "place_of_issue"),
    "BL.ONBOARD_DATE": (AI_DOC_BILL_OF_LADING, "on_board_date"),
    "BL.INCOTERMS": (AI_DOC_BILL_OF_LADING, "incoterms"),
    "BL.NO_OF_ORIGINAL_BL": (AI_DOC_BILL_OF_LADING, "no_of_original_bl"),
    # 상업송장 (INV.INVOICE_NO 이하 6건은 마이그레이션 0004 에서 추가)
    "INV.DESCRIPTION_OF_GOODS": (AI_DOC_COMMERCIAL_INVOICE, "description_of_goods"),
    "INV.QUANTITY": (AI_DOC_COMMERCIAL_INVOICE, "quantity"),
    "INV.AMOUNT": (AI_DOC_COMMERCIAL_INVOICE, "total_amount"),
    "INV.INVOICE_NO": (AI_DOC_COMMERCIAL_INVOICE, "invoice_no"),
    "INV.INVOICE_DATE": (AI_DOC_COMMERCIAL_INVOICE, "invoice_date"),
    "INV.SELLER": (AI_DOC_COMMERCIAL_INVOICE, "seller"),
    "INV.BUYER": (AI_DOC_COMMERCIAL_INVOICE, "buyer"),
    "INV.INCOTERMS": (AI_DOC_COMMERCIAL_INVOICE, "incoterms"),
    "INV.LC_NO": (AI_DOC_COMMERCIAL_INVOICE, "lc_no"),
    # 포장명세서 (PL.INVOICE_NO 이하 6건은 마이그레이션 0004 에서 추가)
    "PL.GROSS_WEIGHT": (AI_DOC_PACKING_LIST, "gross_weight"),
    "PL.MEASUREMENT": (AI_DOC_PACKING_LIST, "measurement"),
    "PL.NET_WEIGHT": (AI_DOC_PACKING_LIST, "net_weight"),
    "PL.PACKAGE_COUNT": (AI_DOC_PACKING_LIST, "package_count"),
    "PL.INVOICE_NO": (AI_DOC_PACKING_LIST, "invoice_no"),
    "PL.PACKING_DATE": (AI_DOC_PACKING_LIST, "packing_date"),
    "PL.SELLER": (AI_DOC_PACKING_LIST, "seller"),
    "PL.BUYER": (AI_DOC_PACKING_LIST, "buyer"),
    "PL.DESCRIPTION_OF_GOODS": (AI_DOC_PACKING_LIST, "description_of_goods"),
    "PL.MARKS": (AI_DOC_PACKING_LIST, "marks"),
}

# 역방향: aiService (서류 종류, 필드명) → DB 필드 코드. /impact 응답의
# 영향 필드를 프론트가 아는 이름으로 되돌릴 때 쓴다. 신용장 필드는 DB 코드가
# 없어(신용장은 MT700 태그로만 관리) 표에 없고, 그 경우 aiService 이름을
# 그대로 내보낸다.
AI_FIELD_TO_DB_CODE: dict[tuple[str, str], str] = {v: k for k, v in DB_FIELD_CODE_TO_AI.items()}


def field_code_to_ai_name(code: str) -> str | None:
    """DB 필드 코드 → aiService 필드명. 접두어 없는 코드(이미 aiService 형식)는 그대로.

    표에 없는 접두어 코드는 None — 호출부가 그 필드를 빼도록.
    """
    if code in DB_FIELD_CODE_TO_AI:
        return DB_FIELD_CODE_TO_AI[code][1]
    if "." not in code:
        return code
    return None


def ai_field_to_field_code(doc: str, name: str) -> str:
    """aiService (서류 종류, 필드명) → DB 필드 코드. 대응이 없으면 aiService 이름 그대로."""
    return AI_FIELD_TO_DB_CODE.get((doc, name), name)

"""Postgres 열거형에 대응하는 Python 열거형.

값은 migrations/sql/01_extensions_and_types.sql 과 반드시 일치해야 합니다.
한쪽만 고치면 런타임에 DataError 가 납니다.
"""

from enum import StrEnum


class ShipmentStatus(StrEnum):
    """기획안 5.8 선적 상태 전이."""

    DRAFT = "DRAFT"
    REVIEWING = "REVIEWING"
    VERIFIED = "VERIFIED"
    SUBMITTED = "SUBMITTED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class ConfidenceGrade(StrEnum):
    """기획안 5.1 신뢰도 등급과 휴먼 확인 라우팅."""

    CONFIRMED = "CONFIRMED"
    REVIEW_SUGGESTED = "REVIEW_SUGGESTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_FOUND = "NOT_FOUND"


class ExtractorKind(StrEnum):
    RULE = "RULE"
    OCR_LLM = "OCR_LLM"
    JSON = "JSON"
    MANUAL = "MANUAL"


class DocumentType(StrEnum):
    BL_DRAFT = "BL_DRAFT"
    BL_COPY = "BL_COPY"
    SI = "SI"
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    LC_MT700 = "LC_MT700"
    INSURANCE_POLICY = "INSURANCE_POLICY"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"
    EXPORT_DECLARATION = "EXPORT_DECLARATION"
    OTHER = "OTHER"


class DocumentSource(StrEnum):
    UPLOAD = "UPLOAD"
    DCSA_JSON = "DCSA_JSON"
    MANUAL = "MANUAL"
    GENERATED = "GENERATED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    DONE = "DONE"
    FAILED = "FAILED"


class VerdictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class GlossaryAuthority(StrEnum):
    UNLOCODE = "UNLOCODE"
    DCSA = "DCSA"
    ISBP = "ISBP"
    UCP600 = "UCP600"
    UNECE_REC20 = "UNECE_REC20"
    ISO6346 = "ISO6346"
    INCOTERMS_2020 = "INCOTERMS_2020"
    HS = "HS"
    ORGANIZATION = "ORGANIZATION"


class GlossaryScope(StrEnum):
    STANDARD = "STANDARD"
    ORGANIZATION = "ORGANIZATION"
    SHIPMENT = "SHIPMENT"


class SuggestionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EvidenceMode(StrEnum):
    """migrations/sql/evidence/10: 근거 강제 모드 (논문 절제 실험 4조건)."""

    P = "P"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


class EvidenceDerivation(StrEnum):
    """어느 선언된 파생 규칙으로 값이 근거 스팬에서 유도됐는지."""

    EXACT = "EXACT"
    SUBSTRING = "SUBSTRING"
    FORMAT = "FORMAT"
    GLOSSARY = "GLOSSARY"
    SIMILARITY = "SIMILARITY"
    NONE = "NONE"


class EvidenceStatus(StrEnum):
    GROUNDED = "GROUNDED"
    DERIVED = "DERIVED"
    UNGROUNDED = "UNGROUNDED"


class SuggestionRejectReason(StrEnum):
    """기획안 5.2: 거절 사유는 사전 개선과 조직별 예외 규칙 생성에 쓰입니다."""

    INTERNAL_PRACTICE = "INTERNAL_PRACTICE"
    COUNTERPARTY_REQUEST = "COUNTERPARTY_REQUEST"
    WRONG_SUGGESTION = "WRONG_SUGGESTION"

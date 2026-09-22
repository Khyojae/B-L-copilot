"""SQLAlchemy 모델.

DDL 의 출처는 migrations/sql/ 입니다. 이 모델들은 그 스키마를 Python 에서 다루기 위한
매핑이며, DB 에는 모델로 표현되지 않는 규칙이 더 있습니다 —
CHECK 제약 32개 · 트리거 6개 · 부분 인덱스 15개.
타입 검사를 통과해도 DB 가 거부할 수 있으니 infra/postgres/README.md 를 함께 보세요.
"""

from smart_e_bl.models.base import Base
from smart_e_bl.models.documents import (
    Document,
    DocumentToken,
    FieldDefinition,
    FieldValue,
    IngestJob,
)
from smart_e_bl.models.glossary import (
    GlossaryAlias,
    GlossaryTerm,
    NormalizationSuggestion,
)
from smart_e_bl.models.reports import AuditLog, Report
from smart_e_bl.models.rules import Rule, RuleCatalogVersion
from smart_e_bl.models.tenancy import (
    AppUser,
    Shipment,
    ShipmentStatusHistory,
    Tenant,
)
from smart_e_bl.models.verdicts import (
    DefectPrediction,
    ModelVersion,
    PredictionFactor,
    Verdict,
    VerdictDisposition,
    VerdictEvidence,
)

__all__ = [
    "AppUser",
    "AuditLog",
    "Base",
    "DefectPrediction",
    "Document",
    "DocumentToken",
    "FieldDefinition",
    "FieldValue",
    "GlossaryAlias",
    "GlossaryTerm",
    "IngestJob",
    "ModelVersion",
    "NormalizationSuggestion",
    "PredictionFactor",
    "Report",
    "Rule",
    "RuleCatalogVersion",
    "Shipment",
    "ShipmentStatusHistory",
    "Tenant",
    "Verdict",
    "VerdictDisposition",
    "VerdictEvidence",
]

"""프론트(`src/types/domain.ts`)와 1:1로 맞춘 응답 스키마.

DB 모델은 필드가 더 많지만(예: Shipment.booking_no), 프론트 타입에 없는
값은 여기서 내보내지 않는다 — API 계약은 프론트 domain.ts가 유일한 출처.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel


class ShipmentResponse(BaseModel):
    shipment_id: uuid.UUID
    status: str
    bl_no: str | None
    cargo_control_no: str | None
    lc_no: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    lc_expiry_date: datetime.date | None


class DocumentMetaResponse(BaseModel):
    document_id: uuid.UUID
    kind: str
    file_name: str | None
    file_hash: str
    page_count: int | None
    version: int
    uploaded_at: datetime.datetime


class FieldValueResponse(BaseModel):
    field_name: str
    value: str | None
    normalized_value: str | None
    confidence: float | None
    source_doc_id: uuid.UUID | None
    page: int | None
    bbox: tuple[float, float, float, float] | None
    extractor: Literal["rule", "ocr+llm", "json"]
    conflict_flag: bool


class CreateShipmentRequest(BaseModel):
    bl_no: str | None = None
    cargo_control_no: str | None = None
    lc_no: str | None = None
    lc_expiry_date: datetime.date | None = None


class ShipmentDraftResponse(BaseModel):
    shipment: ShipmentResponse
    documents: list[DocumentMetaResponse]
    fields: list[FieldValueResponse]
    # F2(표준 용어 교정)는 이번 라운드 범위 밖 — 워커가 제안을 만들지 않으므로
    # 항상 빈 배열이다.
    suggestions: list[dict] = []


class UploadDocumentResponse(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID


# ── F5 정정 영향분석 ──────────────────────────────────────────────


class ImpactRequest(BaseModel):
    """S3 편집기가 필드 하나를 고칠 때마다 보낸다."""

    doc_kind: Literal["BL", "INVOICE", "PACKING", "LC"]
    # DB 필드 코드("BL.CONSIGNEE"). 신용장은 DB 코드가 없어 aiService 필드명
    # ("port_of_loading")을 그대로 쓴다.
    field_name: str


class ImpactItemResponse(BaseModel):
    """프론트 domain.ts ImpactItem 과 1:1. 어디서 오는지는 impact_policy.py 머리말."""

    affected_doc: Literal["BL", "INVOICE", "PACKING", "LC"]
    affected_field: str
    rule_id: str
    source: str
    # aiService ImpactItem.reason("제목 (룰ID)") — 사용자가 할 일의 한 줄 설명.
    action: str
    # 영향받는 서류의 발행 주체(impact_policy.PARTY_BY_AI_DOC).
    party: Literal["화주", "포워더", "선사", "은행", "관세사"]
    # 간선 룰의 심각도 — 이 이웃을 안 맞추면 그 심각도의 위반이 된다.
    urgency: Literal["Critical", "Warning", "Info"]
    # EQ 이웃은 정의상 재검증 대상이다(같아야 하는 값의 한쪽이 바뀌었다).
    requires_recheck: bool = True
    # 축소 구현은 EQ 제약만 도출한다(ruleEngine/impact.py 머리말).
    constraint_type: Literal["EQ"] = "EQ"
    indirect: bool = False


class ImpactResponse(BaseModel):
    items: list[ImpactItemResponse]
    # 탐색 깊이 1 이라 간접 영향은 항상 0 — 깊이를 늘리면 여기가 채워진다.
    indirect_count: int = 0
    # 선적 상태에서 나온다(impact_policy.reissue_path_for). ENDORSEMENT ·
    # SWITCH_BL 은 이번 범위에서 내지 않는다 — 머리말에 이유가 있다.
    reissue_path: Literal["DRAFT_EDIT", "ENDORSEMENT", "REISSUE", "SWITCH_BL"]
    requires_amendment: bool

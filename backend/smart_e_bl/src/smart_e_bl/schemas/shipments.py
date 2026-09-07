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

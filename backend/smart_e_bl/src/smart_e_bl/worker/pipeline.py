"""F1 서류 인테이크 파이프라인 — aiService 호출 → field_value 저장.

이번 라운드 범위: 문서 1건·페이지 1장 추출만 다룬다(PDF는 0페이지 고정).
여러 페이지·여러 서류를 합쳐 하나의 대표값으로 병합하는 다중 출처 병합은
스키마(`field_value.is_representative`/`conflict_flag`)가 지원하지만
이번 파이프라인은 아직 만들지 않는다 — 문서 1건 = 필드마다 대표값 1개.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from smart_e_bl.clients.ai_service import AiServiceError, SyncAiServiceClient
from smart_e_bl.config import settings
from smart_e_bl.mapping import AI_GRADE_TO_DB
from smart_e_bl.models import Document, FieldDefinition, FieldValue, IngestJob
from smart_e_bl.models.enums import ConfidenceGrade, ExtractorKind


class UnsupportedDocumentError(Exception):
    """이 라운드가 아직 다루지 않는 형식(엑셀·이메일·txt 등)."""


def _read_document_bytes(document: Document) -> bytes:
    if document.storage_uri is None:
        raise UnsupportedDocumentError(f"document {document.id}: storage_uri가 없습니다")
    path = Path(document.storage_uri)
    if not path.is_absolute():
        path = Path(settings.document_storage_dir) / path
    return path.read_bytes()


def _extract_draft(
    client: SyncAiServiceClient, document: Document, file_bytes: bytes
) -> tuple[dict[str, Any], int]:
    """(draft dict, page) 를 돌려준다. page는 1부터 시작(DB CHECK page >= 1)."""
    mime = document.mime_type or mimetypes.guess_type(document.original_filename or "")[0] or ""
    filename = document.original_filename or "upload"

    if mime == "application/pdf":
        draft = client.extract_pdf(file_bytes, filename, page=0)
        return draft, 1
    if mime.startswith("image/"):
        draft = client.extract_image(file_bytes, filename)
        return draft, 1

    raise UnsupportedDocumentError(
        f"document {document.id}: 이번 라운드는 이미지·PDF만 지원합니다(mime={mime!r})"
    )


def _known_field_codes(session: Session) -> set[str]:
    return set(session.scalars(select(FieldDefinition.code)))


def _to_field_value(
    *,
    tenant_id: uuid.UUID,
    shipment_id: uuid.UUID,
    document_id: uuid.UUID,
    page: int,
    ai_field: dict[str, Any],
) -> FieldValue:
    """aiService DraftField.to_dict() 1건 → FieldValue 행 1개.

    ⚠ 근거 없는 값은 저장하지 않는다(추정 생성 금지, 규약 §5). aiService가
    bbox 없이 값을 준 경우(예: LLM이 문서 전체를 보고 답해 특정 좌표가 없는
    경우) DB CHECK(field_value_evidence_required_ck)가 애초에 이를 거부하므로,
    여기서 먼저 NOT_FOUND로 강등해 저장 자체가 그 규칙을 어기지 않게 한다.
    """
    grade = AI_GRADE_TO_DB[ai_field["grade"]]
    value = ai_field["value"]
    bbox = ai_field.get("bbox")
    source = ai_field.get("source")

    extractor = ExtractorKind.OCR_LLM if source == "llm" else ExtractorKind.RULE

    if grade != ConfidenceGrade.NOT_FOUND and bbox is None:
        grade = ConfidenceGrade.NOT_FOUND
        value = None

    kwargs: dict[str, Any] = dict(
        tenant_id=tenant_id,
        shipment_id=shipment_id,
        field_code=ai_field["name"],
        value=value,
        normalized_value=None,
        confidence=ai_field.get("confidence"),
        grade=grade,
        extractor=extractor,
        is_representative=True,
    )

    if grade != ConfidenceGrade.NOT_FOUND:
        kwargs.update(
            document_id=document_id,
            page=page,
            bbox_x1=bbox[0],
            bbox_y1=bbox[1],
            bbox_x2=bbox[2],
            bbox_y2=bbox[3],
        )

    return FieldValue(**kwargs)


def run_extraction(session: Session, job: IngestJob) -> int:
    """job에 연결된 문서를 추출해 field_value를 저장한다. 저장한 필드 수를 돌려준다."""
    document = session.scalar(select(Document).where(Document.ingest_job_id == job.id))
    if document is None:
        raise UnsupportedDocumentError(f"job {job.id}에 연결된 document가 없습니다")

    file_bytes = _read_document_bytes(document)
    client = SyncAiServiceClient()

    try:
        draft, page = _extract_draft(client, document, file_bytes)
    except AiServiceError:
        raise

    known_codes = _known_field_codes(session)
    saved = 0
    for ai_field in draft.get("fields", []):
        if ai_field["name"] not in known_codes:
            # field_definition에 없는 코드 — 스키마 밖 필드. 잡 전체를 죽이지
            # 않고 건너뛴다.
            continue
        field_value = _to_field_value(
            tenant_id=document.tenant_id,
            shipment_id=document.shipment_id,
            document_id=document.id,
            page=page,
            ai_field=ai_field,
        )
        session.add(field_value)
        saved += 1

    return saved

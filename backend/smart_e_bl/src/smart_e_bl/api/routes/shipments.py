"""선적 생성 · 서류 업로드 · 초안 조회.

업로드는 파일을 로컬 디스크에 저장하고 document+ingest_job 행을 만든 뒤
job_id를 즉시 반환한다(기획안 5.1). 실제 추출은 워커가 비동기로 한다.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from smart_e_bl.config import settings
from smart_e_bl.db import get_session
from smart_e_bl.deps import CurrentUser, get_current_user
from smart_e_bl.mapping import DB_DOC_TYPE_TO_FRONTEND, DB_EXTRACTOR_TO_FRONTEND, FRONTEND_DOC_KIND_TO_DB
from smart_e_bl.models import Document, FieldValue, IngestJob, Shipment
from smart_e_bl.models.enums import DocumentSource, JobStatus, ShipmentStatus
from smart_e_bl.schemas.shipments import (
    CreateShipmentRequest,
    DocumentMetaResponse,
    FieldValueResponse,
    ShipmentDraftResponse,
    ShipmentResponse,
    UploadDocumentResponse,
)

router = APIRouter(prefix="/api/v1/shipments", tags=["shipments"])

# 프론트 constants/domain.ts UPLOAD_LIMIT.FILE_SIZE_MB와 document_byte_size_ck에 맞춤.
_MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def _shipment_to_response(shipment: Shipment) -> ShipmentResponse:
    return ShipmentResponse(
        shipment_id=shipment.id,
        status=shipment.status.value,
        bl_no=shipment.bl_no,
        cargo_control_no=shipment.cargo_control_no,
        lc_no=shipment.lc_no,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        lc_expiry_date=shipment.lc_expiry_date,
    )


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    body: CreateShipmentRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ShipmentResponse:
    shipment = Shipment(
        tenant_id=current.tenant_id,
        status=ShipmentStatus.DRAFT,
        bl_no=body.bl_no,
        cargo_control_no=body.cargo_control_no,
        lc_no=body.lc_no,
        lc_expiry_date=body.lc_expiry_date,
        created_by=current.user_id,
    )
    session.add(shipment)
    await session.commit()
    await session.refresh(shipment)
    return _shipment_to_response(shipment)


async def _get_owned_shipment(
    shipment_id: uuid.UUID, current: CurrentUser, session: AsyncSession
) -> Shipment:
    shipment = await session.scalar(
        select(Shipment).where(Shipment.id == shipment_id, Shipment.tenant_id == current.tenant_id)
    )
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "선적을 찾을 수 없습니다")
    return shipment


@router.post(
    "/{shipment_id}/documents",
    response_model=UploadDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    shipment_id: uuid.UUID,
    doc_kind: str,
    file: UploadFile,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UploadDocumentResponse:
    shipment = await _get_owned_shipment(shipment_id, current, session)

    if doc_kind not in FRONTEND_DOC_KIND_TO_DB:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"알 수 없는 문서 종류입니다: {doc_kind!r} (허용: {sorted(FRONTEND_DOC_KIND_TO_DB)})",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "빈 파일입니다")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "파일이 30MB를 초과합니다")

    file_hash = hashlib.sha256(payload).hexdigest()

    job = IngestJob(tenant_id=current.tenant_id, shipment_id=shipment.id, status=JobStatus.QUEUED)
    session.add(job)
    await session.flush()  # job.id 확보

    document = Document(
        tenant_id=current.tenant_id,
        shipment_id=shipment.id,
        ingest_job_id=job.id,
        doc_type=FRONTEND_DOC_KIND_TO_DB[doc_kind],
        source=DocumentSource.UPLOAD,
        original_filename=file.filename,
        mime_type=file.content_type,
        byte_size=len(payload),
        page_count=1,  # 이번 라운드는 페이지 1장만 추출(worker/pipeline.py 참고)
        file_hash=file_hash,
        uploaded_by=current.user_id,
    )
    session.add(document)
    try:
        await session.flush()  # document.id 확보 — 중복 업로드면 여기서 unique 제약 위반
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "이미 업로드된 파일입니다(동일 선적·동일 파일)"
        ) from exc

    storage_root = Path(settings.document_storage_dir)
    doc_dir = storage_root / str(current.tenant_id) / str(shipment.id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix
    file_path = doc_dir / f"{document.id}{suffix}"
    file_path.write_bytes(payload)
    document.storage_uri = str(file_path)

    await session.commit()

    return UploadDocumentResponse(document_id=document.id, job_id=job.id)


@router.get("/{shipment_id}/draft", response_model=ShipmentDraftResponse)
async def get_shipment_draft(
    shipment_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ShipmentDraftResponse:
    shipment = await session.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id, Shipment.tenant_id == current.tenant_id)
        .options(selectinload(Shipment.documents))
    )
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "선적을 찾을 수 없습니다")

    fields = (
        await session.scalars(
            select(FieldValue)
            .where(FieldValue.shipment_id == shipment_id, FieldValue.is_representative.is_(True))
            .order_by(FieldValue.field_code)
        )
    ).all()

    return ShipmentDraftResponse(
        shipment=_shipment_to_response(shipment),
        documents=[
            DocumentMetaResponse(
                document_id=doc.id,
                kind=DB_DOC_TYPE_TO_FRONTEND[doc.doc_type],
                file_name=doc.original_filename,
                file_hash=doc.file_hash,
                page_count=doc.page_count,
                version=doc.version,
                uploaded_at=doc.created_at,
            )
            for doc in shipment.documents
        ],
        fields=[
            FieldValueResponse(
                field_name=f.field_code,
                value=f.value,
                normalized_value=f.normalized_value,
                confidence=float(f.confidence) if f.confidence is not None else None,
                source_doc_id=f.document_id,
                page=f.page,
                bbox=(
                    (float(f.bbox_x1), float(f.bbox_y1), float(f.bbox_x2), float(f.bbox_y2))
                    if f.bbox_x1 is not None
                    else None
                ),
                extractor=DB_EXTRACTOR_TO_FRONTEND[f.extractor],
                conflict_flag=f.conflict_flag,
            )
            for f in fields
        ],
        suggestions=[],
    )

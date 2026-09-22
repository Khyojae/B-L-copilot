"""선적 생성 · 서류 업로드 · 초안 조회 · 정정 영향분석(F5) · 리포트(F4·F7).

업로드는 파일을 로컬 디스크에 저장하고 document+ingest_job 행을 만든 뒤
job_id를 즉시 반환한다(기획안 5.1). 실제 추출은 워커가 비동기로 한다.

영향분석과 리포트는 aiService 를 동기 호출로 감싼다. 추출과 달리 잡으로
빼지 않는 이유: 둘 다 OCR 이 없어 수 초 안에 끝나고(clients/ai_service.py
의 타임아웃 주석), 편집기·리포트 화면이 결과를 바로 기다리는 요청이라
폴링을 시키면 오히려 느려진다.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from smart_e_bl.clients.ai_service import AiServiceError, AsyncAiServiceClient
from smart_e_bl.config import settings
from smart_e_bl.db import get_session
from smart_e_bl.deps import CurrentUser, get_ai_client, get_current_user
from smart_e_bl.mapping import (
    AI_DOC_TO_FRONTEND_KIND,
    DB_DOC_TYPE_TO_FRONTEND,
    DB_EXTRACTOR_TO_FRONTEND,
    FRONTEND_DOC_KIND_TO_AI,
    FRONTEND_DOC_KIND_TO_DB,
    ai_field_to_field_code,
    field_code_to_ai_name,
)
from smart_e_bl.models import Document, FieldValue, IngestJob, Shipment
from smart_e_bl.models.enums import DocumentSource, JobStatus, ShipmentStatus
from smart_e_bl.report_payload import build_report_payload
from smart_e_bl.schemas.shipments import (
    CreateShipmentRequest,
    DocumentMetaResponse,
    FieldValueResponse,
    ImpactItemResponse,
    ImpactRequest,
    ImpactResponse,
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


# ── F5 정정 영향분석 ──────────────────────────────────────────────


@router.post("/{shipment_id}/impact", response_model=ImpactResponse)
async def impact(
    shipment_id: uuid.UUID,
    body: ImpactRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ai: AsyncAiServiceClient = Depends(get_ai_client),
) -> ImpactResponse:
    """이 필드를 고치면 함께 확인해야 할 다른 서류·필드(깊이 1, EQ 제약).

    선적을 조회하는 이유는 소유권 확인뿐이다 — 그래프는 룰 카탈로그에서
    나오지 선적 데이터에서 나오지 않으므로, 어떤 값이 저장돼 있든 같은
    (서류, 필드)에는 같은 답이 온다. 값을 바꾸지 않고 결과만 보는
    시뮬레이션 조회가 곧 이 엔드포인트다.
    """
    await _get_owned_shipment(shipment_id, current, session)

    ai_doc = FRONTEND_DOC_KIND_TO_AI[body.doc_kind]
    ai_field = field_code_to_ai_name(body.field_name)
    if ai_field is None:
        # 표에 없는 코드 = 정합성 룰이 다루지 않는 필드. aiService 가 모르는
        # (서류, 필드)에 빈 목록을 주는 것과 같은 의미라 여기서도 빈 목록이다.
        return ImpactResponse(items=[])

    try:
        impacted = await ai.impact(ai_doc, ai_field)
    except AiServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return ImpactResponse(
        items=[
            ImpactItemResponse(
                affected_doc=AI_DOC_TO_FRONTEND_KIND[item["doc"]],
                affected_field=ai_field_to_field_code(item["doc"], item["field"]),
                rule_id=item["rule_id"],
                source=item["source"],
                action=item["reason"],
            )
            for item in impacted
            if item["doc"] in AI_DOC_TO_FRONTEND_KIND
        ]
    )


# ── F4 리포트 (F7 판정 설명 포함) ──────────────────────────────────


async def _report_payload(
    shipment_id: uuid.UUID, current: CurrentUser, session: AsyncSession
) -> dict:
    """선적 + 저장된 필드값 → aiService /report 본문.

    `is_representative` 로 거르지 않고 서류에 매인 행을 전부 읽는다. 대표
    유일성(field_value_representative_uk)은 (선적, 필드코드) 단위라 서류
    종류가 달라도 같은 코드는 하나만 대표가 될 수 있는데, 서류별 검증
    입력에는 각 서류의 값이 따로 필요하다. 대표/후보 우선순위는
    build_report_payload 가 서류별로 다시 정한다.
    """
    shipment = await _get_owned_shipment(shipment_id, current, session)

    rows = (
        await session.execute(
            select(Document.doc_type, FieldValue)
            .join(Document, FieldValue.document_id == Document.id)
            .where(FieldValue.shipment_id == shipment_id)
            .order_by(FieldValue.field_code)
        )
    ).all()
    doc_types = (
        await session.scalars(select(Document.doc_type).where(Document.shipment_id == shipment_id))
    ).all()

    payload = build_report_payload(
        shipment, [(doc_type, fv) for doc_type, fv in rows], submitted_types=list(doc_types)
    )
    if not payload["bl"]:
        # aiService 는 bl 이 비면 400 을 낸다. 여기서는 "요청이 잘못됐다"가
        # 아니라 "아직 추출이 안 끝났다"는 상태 문제라 409 로 구분한다.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "선하증권 필드가 아직 없습니다 — 추출 작업(job)이 끝났는지 확인하세요",
        )
    return payload


@router.get("/{shipment_id}/report")
async def get_report(
    shipment_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ai: AsyncAiServiceClient = Depends(get_ai_client),
) -> dict:
    """리포트 JSON. aiService Report.to_dict() 를 그대로 전달한다.

    변환하지 않는 이유: 프론트 S7 이 지금 aiService 응답 형태를 직접 그리고
    있어서, 여기서 모양을 바꾸면 화면이 깨진다. domain.ts 의 Report 타입으로
    옮기는 일은 프론트 연결 작업과 함께 한다.
    """
    payload = await _report_payload(shipment_id, current, session)
    try:
        return await ai.report(payload)
    except AiServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/{shipment_id}/report/pdf")
async def get_report_pdf(
    shipment_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    ai: AsyncAiServiceClient = Depends(get_ai_client),
) -> Response:
    """리포트 PDF 다운로드. 파일명은 aiService 가 정한 Content-Disposition 을 그대로 쓴다."""
    payload = await _report_payload(shipment_id, current, session)
    try:
        content, disposition = await ai.report_pdf(payload)
    except AiServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    headers = {"Content-Disposition": disposition or 'attachment; filename="BL_Copilot_Report.pdf"'}
    return Response(content=content, media_type="application/pdf", headers=headers)

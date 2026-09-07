"""api/routes/shipments.py 테스트: 선적 생성 · 서류 업로드 · 초안 조회.

conftest.py의 client 픽스처는 이미 인증된 사용자(user/tenant) 컨텍스트를 쓴다.
테넌트 격리를 확인하는 테스트만 make_client로 두 번째 테넌트 클라이언트를 따로 만든다.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser, Document, FieldValue, IngestJob, Shipment, Tenant
from smart_e_bl.models.enums import (
    ConfidenceGrade,
    DocumentSource,
    DocumentType,
    ExtractorKind,
    JobStatus,
)
from smart_e_bl.deps import CurrentUser


async def _create_shipment(client: AsyncClient, **body) -> dict:
    resp = await client.post("/api/v1/shipments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateShipment:
    async def test_생성하면_초안_상태로_시작한다(self, client: AsyncClient):
        body = await _create_shipment(client, bl_no="HLCUBEN2100123456")

        assert body["status"] == "DRAFT"
        assert body["bl_no"] == "HLCUBEN2100123456"
        assert body["cargo_control_no"] is None

    async def test_인증없이_호출하면_401(self, anonymous_client: AsyncClient):
        resp = await anonymous_client.post("/api/v1/shipments", json={})
        assert resp.status_code == 401

    async def test_생성한_선적은_호출자의_테넌트에_귀속된다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser
    ):
        body = await _create_shipment(client)

        shipment = await session.get(Shipment, uuid.UUID(body["shipment_id"]))
        assert shipment is not None
        assert shipment.tenant_id == user.tenant_id
        assert shipment.created_by == user.id


class TestUploadDocument:
    async def test_업로드하면_작업과_서류가_생성된다(
        self, client: AsyncClient, session: AsyncSession
    ):
        shipment = await _create_shipment(client)
        shipment_id = shipment["shipment_id"]

        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("bl_draft.pdf", b"%PDF-1.4 dummy content", "application/pdf")},
        )

        assert resp.status_code == 202, resp.text
        body = resp.json()

        job = await session.get(IngestJob, uuid.UUID(body["job_id"]))
        assert job is not None
        assert job.status == JobStatus.QUEUED

        document = await session.get(Document, uuid.UUID(body["document_id"]))
        assert document is not None
        assert document.doc_type == DocumentType.BL_DRAFT
        assert document.byte_size == len(b"%PDF-1.4 dummy content")
        assert document.ingest_job_id == job.id
        assert document.storage_uri is not None
        assert Path(document.storage_uri).read_bytes() == b"%PDF-1.4 dummy content"

    async def test_알수없는_doc_kind는_400(self, client: AsyncClient):
        shipment = await _create_shipment(client)

        resp = await client.post(
            f"/api/v1/shipments/{shipment['shipment_id']}/documents",
            params={"doc_kind": "NOT_A_KIND"},
            files={"file": ("x.pdf", b"data", "application/pdf")},
        )

        assert resp.status_code == 400

    async def test_빈_파일은_400(self, client: AsyncClient):
        shipment = await _create_shipment(client)

        resp = await client.post(
            f"/api/v1/shipments/{shipment['shipment_id']}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )

        assert resp.status_code == 400

    async def test_30MB_초과_파일은_413(self, client: AsyncClient):
        shipment = await _create_shipment(client)
        oversized = b"0" * (30 * 1024 * 1024 + 1)

        resp = await client.post(
            f"/api/v1/shipments/{shipment['shipment_id']}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("big.pdf", oversized, "application/pdf")},
        )

        assert resp.status_code == 413

    async def test_같은_선적에_같은_파일_재업로드는_409(self, client: AsyncClient):
        shipment = await _create_shipment(client)
        payload = b"identical bytes"

        first = await client.post(
            f"/api/v1/shipments/{shipment['shipment_id']}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("a.pdf", payload, "application/pdf")},
        )
        assert first.status_code == 202

        second = await client.post(
            f"/api/v1/shipments/{shipment['shipment_id']}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("b.pdf", payload, "application/pdf")},
        )
        assert second.status_code == 409

    async def test_존재하지_않는_선적은_404(self, client: AsyncClient):
        resp = await client.post(
            f"/api/v1/shipments/{uuid.uuid4()}/documents",
            params={"doc_kind": "BL"},
            files={"file": ("x.pdf", b"data", "application/pdf")},
        )
        assert resp.status_code == 404

    async def test_다른_테넌트의_선적은_404(
        self, client: AsyncClient, make_client, session: AsyncSession
    ):
        shipment = await _create_shipment(client)

        other_tenant = Tenant(code=f"T-{uuid.uuid4().hex[:8]}", name="다른 테넌트")
        session.add(other_tenant)
        await session.flush()
        other_user = AppUser(
            tenant_id=other_tenant.id,
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            name="다른 사용자",
            role="MEMBER",
            password_hash="x",
        )
        session.add(other_user)
        await session.flush()
        other_current = CurrentUser(
            user_id=other_user.id, tenant_id=other_user.tenant_id, role=other_user.role
        )

        async with make_client(other_current) as other_client:
            resp = await other_client.post(
                f"/api/v1/shipments/{shipment['shipment_id']}/documents",
                params={"doc_kind": "BL"},
                files={"file": ("x.pdf", b"data", "application/pdf")},
            )

        assert resp.status_code == 404


class TestGetDraft:
    async def test_서류_없는_선적은_빈_초안을_반환한다(self, client: AsyncClient):
        shipment = await _create_shipment(client)

        resp = await client.get(f"/api/v1/shipments/{shipment['shipment_id']}/draft")

        assert resp.status_code == 200
        body = resp.json()
        assert body["documents"] == []
        assert body["fields"] == []
        assert body["suggestions"] == []
        assert body["shipment"]["shipment_id"] == shipment["shipment_id"]

    async def test_문서_종류가_프론트_표기로_매핑된다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser
    ):
        shipment = await _create_shipment(client)
        document = Document(
            tenant_id=user.tenant_id,
            shipment_id=uuid.UUID(shipment["shipment_id"]),
            doc_type=DocumentType.COMMERCIAL_INVOICE,
            source=DocumentSource.UPLOAD,
            original_filename="invoice.pdf",
            file_hash="hash-1",
            uploaded_by=user.id,
        )
        session.add(document)
        await session.flush()

        resp = await client.get(f"/api/v1/shipments/{shipment['shipment_id']}/draft")

        assert resp.status_code == 200
        [doc_meta] = resp.json()["documents"]
        assert doc_meta["kind"] == "INVOICE"
        assert doc_meta["file_name"] == "invoice.pdf"

    async def test_대표값만_반환하고_후보값은_제외한다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser
    ):
        shipment_id = uuid.UUID((await _create_shipment(client))["shipment_id"])
        document = Document(
            tenant_id=user.tenant_id,
            shipment_id=shipment_id,
            doc_type=DocumentType.BL_DRAFT,
            source=DocumentSource.UPLOAD,
            file_hash="hash-2",
            uploaded_by=user.id,
        )
        session.add(document)
        await session.flush()

        representative = FieldValue(
            tenant_id=user.tenant_id,
            shipment_id=shipment_id,
            field_code="BL.BL_NO",
            document_id=document.id,
            page=1,
            bbox_x1=Decimal("0.10"),
            bbox_y1=Decimal("0.20"),
            bbox_x2=Decimal("0.50"),
            bbox_y2=Decimal("0.30"),
            value="HLCUBEN2100123456",
            confidence=Decimal("0.950"),
            grade=ConfidenceGrade.CONFIRMED,
            extractor=ExtractorKind.RULE,
            is_representative=True,
        )
        candidate = FieldValue(
            tenant_id=user.tenant_id,
            shipment_id=shipment_id,
            field_code="BL.BL_NO",
            document_id=document.id,
            page=1,
            bbox_x1=Decimal("0.10"),
            bbox_y1=Decimal("0.40"),
            bbox_x2=Decimal("0.50"),
            bbox_y2=Decimal("0.50"),
            value="HLCUBEN2100999999",
            confidence=Decimal("0.400"),
            grade=ConfidenceGrade.REVIEW_REQUIRED,
            extractor=ExtractorKind.OCR_LLM,
            is_representative=False,
        )
        session.add_all([representative, candidate])
        await session.flush()

        resp = await client.get(f"/api/v1/shipments/{shipment_id}/draft")

        assert resp.status_code == 200
        [field] = resp.json()["fields"]
        assert field["field_name"] == "BL.BL_NO"
        assert field["value"] == "HLCUBEN2100123456"
        assert field["extractor"] == "rule"
        assert field["bbox"] == pytest.approx([0.10, 0.20, 0.50, 0.30])
        assert field["source_doc_id"] == str(document.id)

    async def test_존재하지_않는_선적은_404(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/shipments/{uuid.uuid4()}/draft")
        assert resp.status_code == 404

    async def test_다른_테넌트의_선적은_404(
        self, client: AsyncClient, make_client, session: AsyncSession
    ):
        shipment = await _create_shipment(client)

        other_tenant = Tenant(code=f"T-{uuid.uuid4().hex[:8]}", name="다른 테넌트")
        session.add(other_tenant)
        await session.flush()
        other_user = AppUser(
            tenant_id=other_tenant.id,
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            name="다른 사용자",
            role="MEMBER",
            password_hash="x",
        )
        session.add(other_user)
        await session.flush()
        other_current = CurrentUser(
            user_id=other_user.id, tenant_id=other_user.tenant_id, role=other_user.role
        )

        async with make_client(other_current) as other_client:
            resp = await other_client.get(f"/api/v1/shipments/{shipment['shipment_id']}/draft")

        assert resp.status_code == 404

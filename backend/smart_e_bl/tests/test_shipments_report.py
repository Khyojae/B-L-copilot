"""api/routes/shipments.py — F5 정정 영향분석 · F4/F7 리포트 라우트.

aiService 는 `get_ai_client` 오버라이드로 가짜를 끼운다. 여기서 보는 것은
(1) 소유권·상태 검사, (2) DB 필드 → aiService 요청 변환, (3) aiService 응답 →
프론트 이름 변환이다. aiService 자체의 판정 내용은 그쪽 스위트가 본다.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.api.main import app
from smart_e_bl.clients.ai_service import AiServiceError
from smart_e_bl.deps import CurrentUser, get_ai_client
from smart_e_bl.models import AppUser, Document, FieldValue, Tenant
from smart_e_bl.models.enums import (
    ConfidenceGrade,
    DocumentSource,
    DocumentType,
    ExtractorKind,
)


class FakeAiClient:
    """호출 인자를 기록하고 정해진 응답을 돌려준다."""

    def __init__(self) -> None:
        self.impact_calls: list[tuple[str, str]] = []
        self.report_payloads: list[dict[str, Any]] = []
        self.impact_result: list[dict[str, Any]] = []
        self.report_result: dict[str, Any] = {"bl_no": "X", "risks": [], "explanations": []}
        self.error: AiServiceError | None = None

    async def impact(self, doc: str, field: str) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        self.impact_calls.append((doc, field))
        return self.impact_result

    async def report(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.error:
            raise self.error
        self.report_payloads.append(payload)
        return self.report_result

    async def report_pdf(self, payload: dict[str, Any]) -> tuple[bytes, str | None]:
        if self.error:
            raise self.error
        self.report_payloads.append(payload)
        return b"%PDF-1.4 fake", 'attachment; filename="BL_Copilot_Report_X.pdf"'


@pytest.fixture
def fake_ai() -> FakeAiClient:
    fake = FakeAiClient()
    app.dependency_overrides[get_ai_client] = lambda: fake
    return fake


async def _create_shipment(client: AsyncClient, **body) -> str:
    resp = await client.post("/api/v1/shipments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["shipment_id"]


async def _add_document(
    session: AsyncSession, user: AppUser, shipment_id: str, doc_type: DocumentType
) -> Document:
    document = Document(
        tenant_id=user.tenant_id,
        shipment_id=uuid.UUID(shipment_id),
        doc_type=doc_type,
        source=DocumentSource.UPLOAD,
        file_hash=uuid.uuid4().hex,
        uploaded_by=user.id,
    )
    session.add(document)
    await session.flush()
    return document


async def _add_field(
    session: AsyncSession,
    user: AppUser,
    shipment_id: str,
    document: Document,
    code: str,
    value: str,
    *,
    confidence: str = "0.950",
    representative: bool = True,
) -> None:
    session.add(
        FieldValue(
            tenant_id=user.tenant_id,
            shipment_id=uuid.UUID(shipment_id),
            field_code=code,
            document_id=document.id,
            page=1,
            bbox_x1=Decimal("0.1"),
            bbox_y1=Decimal("0.1"),
            bbox_x2=Decimal("0.5"),
            bbox_y2=Decimal("0.2"),
            value=value,
            confidence=Decimal(confidence),
            grade=ConfidenceGrade.CONFIRMED,
            extractor=ExtractorKind.RULE,
            is_representative=representative,
        )
    )
    await session.flush()


class TestImpact:
    async def test_프론트_이름을_aiService_이름으로_바꿔_부르고_결과를_되돌린다(
        self, client: AsyncClient, fake_ai: FakeAiClient
    ):
        shipment_id = await _create_shipment(client)
        fake_ai.impact_result = [
            {
                "doc": "신용장",
                "field": "consignee",
                "rule_id": "LC-CONSIGNEE",
                "source": "UCP600 14(d)",
                "reason": "수하인 일치 (LC-CONSIGNEE)",
            },
            {
                "doc": "상업송장",
                "field": "buyer",
                "rule_id": "X-CONSIGNEE-BUYER",
                "source": "ISBP 821 A.1",
                "reason": "수하인=매수인 (X-CONSIGNEE-BUYER)",
            },
        ]

        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/impact",
            json={"doc_kind": "BL", "field_name": "BL.CONSIGNEE"},
        )

        assert resp.status_code == 200, resp.text
        assert fake_ai.impact_calls == [("선하증권", "consignee")]
        body = resp.json()
        assert body["indirect_count"] == 0
        assert body["items"] == [
            {
                "affected_doc": "LC",
                "affected_field": "consignee",
                "rule_id": "LC-CONSIGNEE",
                "source": "UCP600 14(d)",
                "action": "수하인 일치 (LC-CONSIGNEE)",
                "constraint_type": "EQ",
                "indirect": False,
            },
            {
                "affected_doc": "INVOICE",
                "affected_field": "INV.BUYER",
                "rule_id": "X-CONSIGNEE-BUYER",
                "source": "ISBP 821 A.1",
                "action": "수하인=매수인 (X-CONSIGNEE-BUYER)",
                "constraint_type": "EQ",
                "indirect": False,
            },
        ]

    async def test_영향_필드가_DB_코드를_가지면_그_코드로_돌려준다(
        self, client: AsyncClient, fake_ai: FakeAiClient
    ):
        shipment_id = await _create_shipment(client)
        fake_ai.impact_result = [
            {
                "doc": "포장명세서",
                "field": "gross_weight",
                "rule_id": "X-GW",
                "source": "",
                "reason": "총중량 일치 (X-GW)",
            },
        ]

        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/impact",
            json={"doc_kind": "BL", "field_name": "BL.GROSS_WEIGHT"},
        )

        [item] = resp.json()["items"]
        assert item["affected_doc"] == "PACKING"
        assert item["affected_field"] == "PL.GROSS_WEIGHT"

    async def test_룰이_안_다루는_필드는_aiService를_부르지_않고_빈_목록(
        self, client: AsyncClient, fake_ai: FakeAiClient
    ):
        shipment_id = await _create_shipment(client)

        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/impact",
            json={"doc_kind": "BL", "field_name": "BL.SEAL_NO"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"items": [], "indirect_count": 0}
        assert fake_ai.impact_calls == []

    async def test_모르는_doc_kind는_422(self, client: AsyncClient, fake_ai: FakeAiClient):
        shipment_id = await _create_shipment(client)
        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/impact",
            json={"doc_kind": "NOPE", "field_name": "BL.BL_NO"},
        )
        assert resp.status_code == 422

    async def test_다른_테넌트의_선적은_404(
        self,
        client: AsyncClient,
        make_client: Callable[[CurrentUser], AsyncClient],
        session: AsyncSession,
        fake_ai: FakeAiClient,
    ):
        shipment_id = await _create_shipment(client)

        other_tenant = Tenant(code=f"T-{uuid.uuid4().hex[:8]}", name="다른 테넌트")
        session.add(other_tenant)
        await session.flush()
        other = CurrentUser(user_id=uuid.uuid4(), tenant_id=other_tenant.id, role="MEMBER")

        async with make_client(other) as other_client:
            resp = await other_client.post(
                f"/api/v1/shipments/{shipment_id}/impact",
                json={"doc_kind": "BL", "field_name": "BL.BL_NO"},
            )
        assert resp.status_code == 404

    async def test_aiService_장애는_502(self, client: AsyncClient, fake_ai: FakeAiClient):
        shipment_id = await _create_shipment(client)
        fake_ai.error = AiServiceError("aiService /impact 호출 실패: connection refused")

        resp = await client.post(
            f"/api/v1/shipments/{shipment_id}/impact",
            json={"doc_kind": "BL", "field_name": "BL.BL_NO"},
        )
        assert resp.status_code == 502


class TestReport:
    async def test_저장된_필드를_aiService_요청으로_조립한다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser, fake_ai: FakeAiClient
    ):
        shipment_id = await _create_shipment(client, lc_no="LC-001", lc_expiry_date="2026-12-31")
        bl = await _add_document(session, user, shipment_id, DocumentType.BL_DRAFT)
        inv = await _add_document(session, user, shipment_id, DocumentType.COMMERCIAL_INVOICE)
        await _add_field(session, user, shipment_id, bl, "BL.BL_NO", "HLCU123")
        await _add_field(session, user, shipment_id, bl, "BL.CONSIGNEE", "ACME", confidence="0.600")
        await _add_field(session, user, shipment_id, inv, "INV.AMOUNT", "USD 10,000")

        resp = await client.get(f"/api/v1/shipments/{shipment_id}/report")

        assert resp.status_code == 200, resp.text
        assert resp.json() == fake_ai.report_result
        [payload] = fake_ai.report_payloads
        assert payload["bl"] == {"bl_no": "HLCU123", "consignee": "ACME"}
        assert payload["field_confidence"] == {"bl_no": 0.95, "consignee": 0.6}
        assert payload["lc"] == {"lc_no": "LC-001", "expiry_date": "2026-12-31"}
        assert payload["documents"] == {"상업송장": {"total_amount": "USD 10,000"}}
        assert payload["submitted_documents"] == ["BILL OF LADING", "COMMERCIAL INVOICE"]

    async def test_서류마다_같은_필드코드가_있어도_서류별로_나뉜다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser, fake_ai: FakeAiClient
    ):
        """대표 유일성은 (선적, 코드) 단위라 두 번째 서류의 값은 후보로만 저장된다 —
        그래도 검증 입력에는 각 서류의 값이 따로 들어가야 한다."""
        shipment_id = await _create_shipment(client)
        bl = await _add_document(session, user, shipment_id, DocumentType.BL_DRAFT)
        pl = await _add_document(session, user, shipment_id, DocumentType.PACKING_LIST)
        await _add_field(session, user, shipment_id, bl, "BL.GROSS_WEIGHT", "1000 KGS")
        await _add_field(
            session, user, shipment_id, pl, "PL.GROSS_WEIGHT", "990 KGS", representative=False
        )

        await client.get(f"/api/v1/shipments/{shipment_id}/report")

        [payload] = fake_ai.report_payloads
        assert payload["bl"]["gross_weight"] == "1000 KGS"
        assert payload["documents"]["포장명세서"]["gross_weight"] == "990 KGS"

    async def test_선하증권_필드가_없으면_409(self, client: AsyncClient, fake_ai: FakeAiClient):
        shipment_id = await _create_shipment(client)

        resp = await client.get(f"/api/v1/shipments/{shipment_id}/report")

        assert resp.status_code == 409
        assert fake_ai.report_payloads == []

    async def test_pdf는_aiService_파일명을_그대로_쓴다(
        self, client: AsyncClient, session: AsyncSession, user: AppUser, fake_ai: FakeAiClient
    ):
        shipment_id = await _create_shipment(client)
        bl = await _add_document(session, user, shipment_id, DocumentType.BL_DRAFT)
        await _add_field(session, user, shipment_id, bl, "BL.BL_NO", "X")

        resp = await client.get(f"/api/v1/shipments/{shipment_id}/report/pdf")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert (
            resp.headers["content-disposition"]
            == 'attachment; filename="BL_Copilot_Report_X.pdf"'
        )
        assert resp.content == b"%PDF-1.4 fake"

    async def test_존재하지_않는_선적은_404(self, client: AsyncClient, fake_ai: FakeAiClient):
        resp = await client.get(f"/api/v1/shipments/{uuid.uuid4()}/report")
        assert resp.status_code == 404

    async def test_인증없이_호출하면_401(self, anonymous_client: AsyncClient):
        resp = await anonymous_client.get(f"/api/v1/shipments/{uuid.uuid4()}/report")
        assert resp.status_code == 401

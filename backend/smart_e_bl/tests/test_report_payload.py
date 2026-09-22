"""report_payload.build_report_payload — DB 없이 도는 조립 규칙 테스트.

라우트 테스트(test_shipments_report.py)는 Postgres 가 필요하지만, 필드 코드
변환·서류 분류·대표값 우선·신용장 헤더 병합은 여기서 먼저 잡는다.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from smart_e_bl.models import FieldValue, Shipment
from smart_e_bl.models.enums import ConfidenceGrade, DocumentType, ExtractorKind
from smart_e_bl.report_payload import build_report_payload


def _fv(code: str, value: str | None, *, confidence: str | None = None, rep: bool = True,
        normalized: str | None = None) -> FieldValue:
    return FieldValue(
        tenant_id=uuid.uuid4(),
        shipment_id=uuid.uuid4(),
        field_code=code,
        value=value,
        normalized_value=normalized,
        confidence=Decimal(confidence) if confidence is not None else None,
        grade=ConfidenceGrade.CONFIRMED,
        extractor=ExtractorKind.RULE,
        is_representative=rep,
    )


def _shipment(**kw) -> Shipment:
    return Shipment(tenant_id=uuid.uuid4(), **kw)


class TestBuildReportPayload:
    def test_선하증권_필드는_aiService_이름으로_bl에_들어간다(self):
        rows = [
            (DocumentType.BL_DRAFT, _fv("BL.BL_NO", "HLCU123")),
            (DocumentType.BL_DRAFT, _fv("BL.ONBOARD_DATE", "2026-09-01")),
            (DocumentType.BL_DRAFT, _fv("BL.VESSEL_VOYAGE", "EVER GIVEN 001E")),
        ]
        payload = build_report_payload(_shipment(), rows, submitted_types=[DocumentType.BL_DRAFT])

        assert payload["bl"] == {
            "bl_no": "HLCU123",
            "on_board_date": "2026-09-01",
            "vessel": "EVER GIVEN 001E",
        }
        assert payload["submitted_documents"] == ["BILL OF LADING"]

    def test_다른_서류는_documents에_한국어_서류명으로_들어간다(self):
        rows = [
            (DocumentType.BL_DRAFT, _fv("BL.GROSS_WEIGHT", "1000 KGS")),
            (DocumentType.COMMERCIAL_INVOICE, _fv("INV.AMOUNT", "USD 10,000")),
            (DocumentType.PACKING_LIST, _fv("PL.GROSS_WEIGHT", "1000 KGS")),
        ]
        payload = build_report_payload(
            _shipment(), rows,
            submitted_types=[DocumentType.BL_DRAFT, DocumentType.COMMERCIAL_INVOICE, DocumentType.PACKING_LIST],
        )

        assert payload["documents"] == {
            "상업송장": {"total_amount": "USD 10,000"},
            "포장명세서": {"gross_weight": "1000 KGS"},
        }
        assert payload["submitted_documents"] == ["BILL OF LADING", "COMMERCIAL INVOICE", "PACKING LIST"]

    def test_룰이_안_쓰는_필드코드는_뺀다(self):
        rows = [
            (DocumentType.BL_DRAFT, _fv("BL.BL_NO", "X")),
            (DocumentType.BL_DRAFT, _fv("BL.SEAL_NO", "S1")),        # 표에 없음
            (DocumentType.INSURANCE_POLICY, _fv("INS.POLICY_NO", "P1")),  # 서류 자체가 범위 밖
        ]
        payload = build_report_payload(_shipment(), rows, submitted_types=[DocumentType.BL_DRAFT])

        assert payload["bl"] == {"bl_no": "X"}
        assert "documents" not in payload

    def test_접두어_없는_코드는_aiService_이름으로_본다(self):
        rows = [(DocumentType.BL_DRAFT, _fv("consignee", "ACME"))]
        payload = build_report_payload(_shipment(), rows, submitted_types=[])
        assert payload["bl"] == {"consignee": "ACME"}

    def test_대표값이_후보를_이긴다(self):
        rows = [
            (DocumentType.BL_DRAFT, _fv("BL.BL_NO", "CANDIDATE", rep=False)),
            (DocumentType.BL_DRAFT, _fv("BL.BL_NO", "REPRESENTATIVE", rep=True)),
        ]
        payload = build_report_payload(_shipment(), rows, submitted_types=[])
        assert payload["bl"]["bl_no"] == "REPRESENTATIVE"

    def test_교정값이_있으면_교정값을_보낸다(self):
        rows = [(DocumentType.BL_DRAFT, _fv("BL.PORT_OF_LOADING", "Busan, Korea", normalized="KRPUS"))]
        payload = build_report_payload(_shipment(), rows, submitted_types=[])
        assert payload["bl"]["port_of_loading"] == "KRPUS"

    def test_신뢰도는_선하증권_필드만_보낸다(self):
        rows = [
            (DocumentType.BL_DRAFT, _fv("BL.CONSIGNEE", "ACME", confidence="0.650")),
            (DocumentType.BL_DRAFT, _fv("BL.BL_NO", "X")),  # confidence None → 생략
            (DocumentType.COMMERCIAL_INVOICE, _fv("INV.AMOUNT", "1", confidence="0.9")),
        ]
        payload = build_report_payload(_shipment(), rows, submitted_types=[])
        assert payload["field_confidence"] == {"consignee": 0.65}

    def test_신용장은_선적_헤더의_번호와_만기일을_합친다(self):
        shipment = _shipment(lc_no="LC-001", lc_expiry_date=datetime.date(2026, 12, 31))
        payload = build_report_payload(
            shipment, [(DocumentType.BL_DRAFT, _fv("BL.BL_NO", "X"))], submitted_types=[]
        )
        assert payload["lc"] == {"lc_no": "LC-001", "expiry_date": "2026-12-31"}

    def test_신용장_서류값이_헤더보다_우선한다(self):
        shipment = _shipment(lc_no="HEADER")
        rows = [(DocumentType.LC_MT700, _fv("lc_no", "FROM-DOC"))]
        payload = build_report_payload(shipment, rows, submitted_types=[])
        assert payload["lc"]["lc_no"] == "FROM-DOC"

    def test_신용장_정보가_전혀_없으면_lc_키를_만들지_않는다(self):
        payload = build_report_payload(
            _shipment(), [(DocumentType.BL_DRAFT, _fv("BL.BL_NO", "X"))], submitted_types=[]
        )
        assert "lc" not in payload

    def test_선하증권_필드가_없으면_bl은_빈_dict(self):
        payload = build_report_payload(
            _shipment(), [(DocumentType.COMMERCIAL_INVOICE, _fv("INV.AMOUNT", "1"))], submitted_types=[]
        )
        assert payload["bl"] == {}

"""worker/pipeline.py — aiService 필드명 → field_definition.code 변환.

DB 없이 돈다. 이 변환이 틀리면 추출된 값이 전부 "모르는 코드"로 버려져
초안이 비고, /report 는 409 만 낸다 — 그래서 저장 경로와 분리해 잡는다.
"""

from __future__ import annotations

import uuid

from smart_e_bl.models import Document
from smart_e_bl.models.enums import DocumentSource, DocumentType
from smart_e_bl.worker.pipeline import _field_code_for, _to_field_value


def _doc(doc_type: DocumentType) -> Document:
    return Document(
        tenant_id=uuid.uuid4(),
        shipment_id=uuid.uuid4(),
        doc_type=doc_type,
        source=DocumentSource.UPLOAD,
        file_hash="x",
    )


class TestFieldCodeFor:
    def test_선하증권_필드는_BL_접두어_코드가_된다(self):
        doc = _doc(DocumentType.BL_DRAFT)
        assert _field_code_for(doc, "bl_no") == "BL.BL_NO"
        assert _field_code_for(doc, "on_board_date") == "BL.ONBOARD_DATE"
        assert _field_code_for(doc, "vessel") == "BL.VESSEL_VOYAGE"

    def test_같은_이름이라도_서류에_따라_코드가_다르다(self):
        assert _field_code_for(_doc(DocumentType.BL_DRAFT), "gross_weight") == "BL.GROSS_WEIGHT"
        assert _field_code_for(_doc(DocumentType.PACKING_LIST), "gross_weight") == "PL.GROSS_WEIGHT"
        assert _field_code_for(_doc(DocumentType.BL_COPY), "gross_weight") == "BL.GROSS_WEIGHT"

    def test_상업송장_금액은_INV_AMOUNT(self):
        assert _field_code_for(_doc(DocumentType.COMMERCIAL_INVOICE), "total_amount") == "INV.AMOUNT"

    def test_서류_간_룰이_쓰는_송장_포장명세서_필드가_저장된다(self):
        inv = _doc(DocumentType.COMMERCIAL_INVOICE)
        assert _field_code_for(inv, "buyer") == "INV.BUYER"
        assert _field_code_for(inv, "seller") == "INV.SELLER"
        assert _field_code_for(inv, "invoice_no") == "INV.INVOICE_NO"
        assert _field_code_for(inv, "lc_no") == "INV.LC_NO"
        assert _field_code_for(inv, "incoterms") == "INV.INCOTERMS"
        pl = _doc(DocumentType.PACKING_LIST)
        assert _field_code_for(pl, "invoice_no") == "PL.INVOICE_NO"
        assert _field_code_for(pl, "description_of_goods") == "PL.DESCRIPTION_OF_GOODS"

    def test_카탈로그에_없는_필드는_None(self):
        doc = _doc(DocumentType.BL_DRAFT)
        assert _field_code_for(doc, "bl_clauses") is None
        assert _field_code_for(doc, "voyage_no") is None

    def test_범위_밖_서류는_None(self):
        assert _field_code_for(_doc(DocumentType.INSURANCE_POLICY), "bl_no") is None


class TestToFieldValue:
    def test_변환된_코드가_field_code에_들어간다(self):
        fv = _to_field_value(
            tenant_id=uuid.uuid4(),
            shipment_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page=1,
            field_code="BL.BL_NO",
            ai_field={
                "name": "bl_no",
                "value": "HLCU1",
                "grade": "confirmed",
                "confidence": 0.95,
                "bbox": [0.1, 0.1, 0.5, 0.2],
                "source": "region",
            },
        )
        assert fv.field_code == "BL.BL_NO"
        assert fv.value == "HLCU1"
        assert fv.is_representative is True

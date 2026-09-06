"""서류 간 정합성 테스트 (기획안 5절 7번).

`test_rule_engine.py` 는 서류 1건을 L/C 에 대조하고, 여기는 서류끼리 대조한다.
"""

from __future__ import annotations

import pytest

from ocr import doc_types
from ocr.doc_parser import DocumentFields
from ocr.types import BLFields
from ruleEngine import CrossDocumentEngine, DocumentSet, LCTerms
from ruleEngine.cross_doc import LC_DOC


@pytest.fixture(scope="module")
def engine() -> CrossDocumentEngine:
    return CrossDocumentEngine()


def make_bl(**overrides) -> BLFields:
    values = {
        "bl_no": "HMMU1234567",
        "shipper": "HANWOO TRADING CO., LTD.",
        "consignee": "PACIFIC IMPORT GMBH",
        "description_of_goods": "27 PKG CELL ASSEMBLY",
        "gross_weight": "884 KG",
        "measurement": "349.64 CBM",
    }
    values.update(overrides)
    f = BLFields()
    for name, value in values.items():
        f.set_field(name, value, 1.0, "region")
    return f


def make_doc(form_type: str, **values) -> DocumentFields:
    fields = DocumentFields(doc_types.spec_for(form_type))
    for name, value in values.items():
        fields.set_field(name, value, 1.0, "anchor")
    return fields


def make_invoice(**overrides) -> DocumentFields:
    values = {
        "invoice_no": "INV-2026-0801",
        "seller": "HANWOO TRADING CO., LTD.",
        "buyer": "PACIFIC IMPORT GMBH",
        "description_of_goods": "27 PKG CELL ASSEMBLY MACHINE",
        "total_amount": "$12,000.00",
        "incoterms": "FOB",
        "lc_no": "LC-2026-101",
    }
    values.update(overrides)
    return make_doc(doc_types.COMMERCIAL_INVOICE, **values)


def make_packing(**overrides) -> DocumentFields:
    values = {
        "invoice_no": "INV-2026-0801",
        "buyer": "PACIFIC IMPORT GMBH",
        "description_of_goods": "27 PKG CELL ASSEMBLY",
        "gross_weight": "884 KG",
        "measurement": "349.64 CBM",
    }
    values.update(overrides)
    return make_doc(doc_types.PACKING_LIST, **values)


def full_set(**overrides) -> DocumentSet:
    lc = LCTerms(lc_no="LC-2026-101", currency_amount="USD 15,000.00", incoterms="FOB")
    docs = DocumentSet(lc=lc)
    docs.add(overrides.get("bl", make_bl()))
    docs.add(overrides.get("invoice", make_invoice()))
    docs.add(overrides.get("packing", make_packing()))
    return docs


def ids(verdict) -> set:
    return {v.rule_id for v in verdict.violations}


def skipped_reason(verdict, rule_id: str) -> str:
    return next(s.reason for s in verdict.skipped if s.rule_id == rule_id)


class TestCleanSet:
    def test_정합한_서류_묶음은_위반이_없다(self, engine):
        verdict = engine.verify(full_set())

        assert verdict.violations == []
        assert verdict.evaluated_count > 0

    def test_더_자세한_명세는_저촉이_아니다(self, engine):
        """Art.14(e) — 송장이 더 자세히 적는 것은 정상이다."""
        # B/L 'CELL ASSEMBLY' ⊂ 송장 'CELL ASSEMBLY MACHINE'
        assert "X003" not in ids(engine.verify(full_set()))

    def test_법인격_표기_차이를_흡수한다(self, engine):
        docs = full_set(invoice=make_invoice(buyer="PACIFIC IMPORT GMBH CO LTD"))

        assert "X001" not in ids(engine.verify(docs))

    def test_참조번호_구분자_차이를_흡수한다(self, engine):
        docs = full_set(packing=make_packing(invoice_no="INV20260801"))

        assert "X007" not in ids(engine.verify(docs))


class TestGenericGoods:
    """일반적 용어는 판정하지 않는다 — 위반도 통과도 아니다."""

    def test_일반적_용어만이면_판정하지_않는다(self, engine):
        # "MACHINERY PARTS" 가 "CELL ASSEMBLY MACHINE" 과 저촉하는지는
        # 무역 실무 판단이다. 토큰 겹침으로는 답이 안 나온다.
        docs = full_set(bl=make_bl(description_of_goods="27 PKG MACHINERY PARTS"))
        verdict = engine.verify(docs)

        assert "X003" not in ids(verdict)
        assert "일반적 용어" in skipped_reason(verdict, "X003")

    def test_판정하지_못한_것을_침묵하지_않는다(self, engine):
        # 검사하지 못한 항목을 침묵으로 넘기면 '검사했고 문제없다'로 읽힌다.
        docs = full_set(bl=make_bl(description_of_goods="SAID TO CONTAIN GOODS"))
        verdict = engine.verify(docs)

        assert any(s.rule_id == "X003" for s in verdict.skipped)

    def test_구체적_품명이면_판정한다(self, engine):
        docs = full_set(bl=make_bl(description_of_goods="27 PKG RAW COTTON"))

        # COTTON 은 일반적 용어가 아니므로 저촉으로 판정된다.
        assert "X003" in ids(engine.verify(docs))


class TestConflicts:
    def test_수하인과_매수인이_다르면_치명(self, engine):
        docs = full_set(invoice=make_invoice(buyer="SHANGHAI EAST TRADING"))
        verdict = engine.verify(docs)

        assert "X001" in ids(verdict)
        violation = next(v for v in verdict.violations if v.rule_id == "X001")
        assert violation.severity.value == "critical"
        # 화면이 어느 서류의 어느 필드인지 알아야 편집기로 점프할 수 있다.
        assert "선하증권.consignee" in violation.fields
        assert "상업송장.buyer" in violation.fields

    def test_물품_명세가_전혀_다르면_저촉(self, engine):
        docs = full_set(invoice=make_invoice(description_of_goods="500 KG RAW COTTON"))

        assert "X003" in ids(engine.verify(docs))

    def test_수량만_같은_것은_근거가_아니다(self, engine):
        # 숫자 토큰을 세면 "27 PKG STEEL" 과 "27 PKG COTTON" 이 통과한다.
        docs = DocumentSet()
        docs.add(make_bl(description_of_goods="27 PKG STEEL COIL"))
        docs.add(make_invoice(description_of_goods="27 PKG COTTON YARN"))

        assert "X003" in ids(engine.verify(docs))

    def test_총_중량이_다르면_치명(self, engine):
        docs = full_set(packing=make_packing(gross_weight="1,240 KG"))
        verdict = engine.verify(docs)

        assert "X005" in ids(verdict)
        violation = next(v for v in verdict.violations if v.rule_id == "X005")
        assert violation.observed["left"] == "884 KG"
        assert violation.observed["right"] == "1,240 KG"

    def test_단위가_달라도_환산해_비교한다(self, engine):
        # 0.884 MT = 884 KG. 표기만 다르고 같은 중량이다.
        docs = full_set(packing=make_packing(gross_weight="0.884 MT"))

        assert "X005" not in ids(engine.verify(docs))

    def test_송장_금액이_신용장을_넘으면_치명(self, engine):
        docs = full_set(invoice=make_invoice(total_amount="$18,000.00"))

        assert "X009" in ids(engine.verify(docs))

    def test_신용장_번호_인용이_틀리면_잡는다(self, engine):
        docs = full_set(invoice=make_invoice(lc_no="LC-2026-999"))

        assert "X008" in ids(engine.verify(docs))

    def test_가격조건_저촉을_잡는다(self, engine):
        docs = full_set(invoice=make_invoice(incoterms="CIF"))

        assert "X010" in ids(engine.verify(docs))

    def test_하자_확률에_가중치가_반영된다(self, engine):
        docs = full_set(invoice=make_invoice(buyer="SHANGHAI EAST TRADING"))
        verdict = engine.verify(docs)

        assert verdict.defect_probability > 0
        assert verdict.model == "cross-rules-v1"


class TestMissingDocuments:
    def test_없는_서류는_위반이_아니다(self, engine):
        """B/L 만 올린 사용자에게 저촉 하자가 뜨면 안 된다.

        그 하자들은 서류를 더 올리는 것 말고는 고칠 방법이 없다. 사용자가
        고칠 수 없는 것을 하자로 표시하면 화면 전체의 신뢰가 떨어진다.
        """
        docs = DocumentSet()
        docs.add(make_bl())

        assert engine.verify(docs).violations == []

    def test_없는_서류는_평가불가로_남는다(self, engine):
        # 침묵으로 넘기면 사용자는 '검사했고 문제없다'로 읽는다.
        docs = DocumentSet()
        docs.add(make_bl())

        verdict = engine.verify(docs)
        assert len(verdict.skipped) == len(engine)
        assert any("상업송장" in s.reason for s in verdict.skipped)

    def test_신용장이_없으면_L_C_대조만_건너뛴다(self, engine):
        docs = DocumentSet()
        docs.add(make_bl())
        docs.add(make_invoice())
        docs.add(make_packing())

        verdict = engine.verify(docs)
        skipped_ids = {s.rule_id for s in verdict.skipped}

        assert "X008" in skipped_ids      # 송장 ↔ L/C
        assert "X001" not in skipped_ids  # B/L ↔ 송장은 여전히 검사된다

    def test_값이_비면_저촉으로_세지_않는다(self, engine):
        # 누락은 서류별 룰이 잡는다. 여기서 또 세면 이중 계상이다.
        docs = full_set(packing=make_packing(gross_weight=None))
        verdict = engine.verify(docs)

        assert "X005" not in ids(verdict)
        assert "값이 서류에 없습니다" in skipped_reason(verdict, "X005")


class TestCatalog:
    def _rule(self, **overrides) -> dict:
        rule = {
            "id": "Z001", "title": "x", "severity": "warning",
            "check": "same_reference", "message": "m",
            "left": {"doc": "선하증권", "field": "bl_no"},
            "right": {"doc": "상업송장", "field": "invoice_no"},
        }
        rule.update(overrides)
        return rule

    def test_알_수_없는_check_를_거부한다(self):
        from ruleEngine.cross_doc import _validate_cross_catalog
        from ruleEngine.engine import RuleCatalogError

        with pytest.raises(RuleCatalogError, match="알 수 없는 check"):
            _validate_cross_catalog([self._rule(check="nope")])

    def test_중복_id_를_거부한다(self):
        from ruleEngine.cross_doc import _validate_cross_catalog
        from ruleEngine.engine import RuleCatalogError

        with pytest.raises(RuleCatalogError, match="중복"):
            _validate_cross_catalog([self._rule(), self._rule()])

    def test_doc_field_가_없으면_거부한다(self):
        from ruleEngine.cross_doc import _validate_cross_catalog
        from ruleEngine.engine import RuleCatalogError

        with pytest.raises(RuleCatalogError, match="doc/field"):
            _validate_cross_catalog([self._rule(left={"doc": "선하증권"})])

    def test_조문_미검증_건수를_센다(self, engine):
        # 화면이 이 값을 숨기면 미검증 조문이 검증된 것처럼 인용된다.
        assert len(engine.unverified_rules()) == len(engine)

    def test_LC_예약어로_신용장을_가리킨다(self, engine):
        docs = full_set()

        assert docs.has(LC_DOC)
        assert docs.value(LC_DOC, "lc_no") == "LC-2026-101"

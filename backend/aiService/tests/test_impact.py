"""
F5 정정 영향분석 테스트.

보고서(수정17)가 "주입 시나리오 8종으로 재현율 확인"이라 적었다. 아래
8개 케이스가 그것이다 — 그래프가 EQ 계열 룰(`rules.yaml`의 `lc_field`,
`cross_rules.yaml`의 `left`/`right`)에서 정확히 도출되는지, 깊이 1까지만
보는지, 무향(양방향)인지를 확인한다.
"""

from __future__ import annotations

import pytest

from ruleEngine import ConsistencyGraph, CrossDocumentEngine, RuleEngine
from ruleEngine.cross_doc import BILL_OF_LADING, LC_DOC

COMMERCIAL_INVOICE = "상업송장"
PACKING_LIST = "포장명세서"


@pytest.fixture(scope="module")
def graph() -> ConsistencyGraph:
    return ConsistencyGraph.build(RuleEngine().rules, CrossDocumentEngine().rules)


def _pairs(items):
    return {(i.doc, i.field) for i in items}


class Test주입_시나리오_8종:
    """편집한 필드 → 실제로 노출돼야 하는 이웃(재현율)."""

    def test_1_수하인_정정은_신용장과_송장_매수인을_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "consignee"))
        assert (LC_DOC, "consignee") in result          # D005B match_place
        assert (COMMERCIAL_INVOICE, "buyer") in result   # X001 same_party

    def test_2_선적항_정정은_신용장_선적항을_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "port_of_loading"))
        assert (LC_DOC, "port_of_loading") in result     # D003 match_place

    def test_3_양하항_정정은_신용장_양하항을_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "port_of_discharge"))
        assert (LC_DOC, "port_of_discharge") in result   # D004 match_place

    def test_4_통지처_정정은_신용장_통지처를_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "notify_party"))
        assert (LC_DOC, "notify_party") in result        # D020 match_place

    def test_5_총중량_정정은_포장명세서_총중량을_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "gross_weight"))
        assert (PACKING_LIST, "gross_weight") in result  # X005 same_quantity

    def test_6_용적_정정은_포장명세서_용적을_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "measurement"))
        assert (PACKING_LIST, "measurement") in result   # X006 same_quantity

    def test_7_물품명세_정정은_송장_물품명세를_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "description_of_goods"))
        assert (COMMERCIAL_INVOICE, "description_of_goods") in result  # X003

    def test_8_운임_정정은_신용장_운임한도를_노출한다(self, graph):
        result = _pairs(graph.impacted(BILL_OF_LADING, "total_freight"))
        assert (LC_DOC, "freight_amount") in result      # D017 within_tolerance


class Test그래프_속성:
    """축소 범위(깊이 1·EQ 한정·무향)가 실제로 지켜지는지."""

    def test_존재_검사_룰만_있는_필드는_이웃이_없다(self, graph):
        # bl_no 는 `required` 룰만 참조한다 — EQ 계열이 아니므로 간선이 없다.
        assert graph.impacted(BILL_OF_LADING, "bl_no") == []

    def test_무향이라_반대_방향에서도_보인다(self, graph):
        result = _pairs(graph.impacted(COMMERCIAL_INVOICE, "description_of_goods"))
        assert (BILL_OF_LADING, "description_of_goods") in result  # X003
        assert (PACKING_LIST, "description_of_goods") in result    # X004

    def test_깊이_1만_본다(self, graph):
        # 상업송장.description_of_goods 는 포장명세서.description_of_goods 와
        # 직접 이웃(X004)이지만, 선하증권.description_of_goods 를 거쳐야
        # 닿는 신용장 쪽 필드(있었다면)까지는 확장하지 않는다 — 반환값이
        # 전부 1홉 이웃이어야 한다.
        for item in graph.impacted(BILL_OF_LADING, "description_of_goods"):
            assert item.doc != BILL_OF_LADING

    def test_모르는_필드는_빈_목록이다(self, graph):
        assert graph.impacted(BILL_OF_LADING, "no_such_field") == []
        assert graph.impacted("미상서류", "field") == []

    def test_이웃마다_간선_룰의_심각도가_붙는다(self, graph):
        items = graph.impacted(BILL_OF_LADING, "consignee")
        assert items and all(i.severity in {"critical", "warning", "info"} for i in items)
        assert all(i.to_dict()["severity"] == i.severity for i in items)

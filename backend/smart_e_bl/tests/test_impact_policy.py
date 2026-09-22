"""impact_policy — 담당 당사자·재발행 경로·조건 변경 규칙. DB 없이 돈다."""

from __future__ import annotations

import pytest

from smart_e_bl.impact_policy import (
    AI_SEVERITY_TO_FRONTEND,
    PARTY_BY_AI_DOC,
    party_for,
    reissue_path_for,
    requires_amendment_for,
)
from smart_e_bl.mapping import (
    AI_DOC_BILL_OF_LADING,
    AI_DOC_COMMERCIAL_INVOICE,
    AI_DOC_LC,
    AI_DOC_PACKING_LIST,
    AI_DOC_TO_FRONTEND_KIND,
)
from smart_e_bl.models.enums import ShipmentStatus

PRE_ISSUE = (ShipmentStatus.DRAFT, ShipmentStatus.REVIEWING, ShipmentStatus.VERIFIED)
POST_ISSUE = (ShipmentStatus.SUBMITTED, ShipmentStatus.MONITORING, ShipmentStatus.CLOSED)


class TestParty:
    def test_서류_발행_주체가_담당이다(self):
        assert party_for(AI_DOC_LC) == "은행"
        assert party_for(AI_DOC_BILL_OF_LADING) == "선사"
        assert party_for(AI_DOC_COMMERCIAL_INVOICE) == "화주"
        assert party_for(AI_DOC_PACKING_LIST) == "화주"

    def test_impact_응답이_될_수_있는_서류는_전부_담당이_정해져_있다(self):
        assert set(AI_DOC_TO_FRONTEND_KIND) == set(PARTY_BY_AI_DOC)


class TestReissuePath:
    @pytest.mark.parametrize("status", PRE_ISSUE)
    def test_발행_전에는_어느_서류를_고쳐도_초안_수정(self, status):
        assert reissue_path_for(status, AI_DOC_BILL_OF_LADING) == "DRAFT_EDIT"
        assert reissue_path_for(status, AI_DOC_COMMERCIAL_INVOICE) == "DRAFT_EDIT"

    @pytest.mark.parametrize("status", POST_ISSUE)
    def test_발행_후_선하증권_정정은_재발행(self, status):
        assert reissue_path_for(status, AI_DOC_BILL_OF_LADING) == "REISSUE"

    @pytest.mark.parametrize("status", POST_ISSUE)
    def test_발행_후라도_송장_정정은_재발행_경로가_아니다(self, status):
        assert reissue_path_for(status, AI_DOC_COMMERCIAL_INVOICE) == "DRAFT_EDIT"
        assert reissue_path_for(status, AI_DOC_PACKING_LIST) == "DRAFT_EDIT"

    def test_모든_상태에_답이_있다(self):
        for status in ShipmentStatus:
            assert reissue_path_for(status, AI_DOC_BILL_OF_LADING) in ("DRAFT_EDIT", "REISSUE")


class TestRequiresAmendment:
    @pytest.mark.parametrize("status", POST_ISSUE)
    def test_제출_후_신용장과_묶인_필드면_조건_변경(self, status):
        assert requires_amendment_for(status, [AI_DOC_LC, AI_DOC_COMMERCIAL_INVOICE]) is True

    @pytest.mark.parametrize("status", POST_ISSUE)
    def test_제출_후라도_신용장과_무관하면_조건_변경_아님(self, status):
        assert requires_amendment_for(status, [AI_DOC_PACKING_LIST]) is False
        assert requires_amendment_for(status, []) is False

    @pytest.mark.parametrize("status", PRE_ISSUE)
    def test_제출_전에는_신용장_필드라도_조건_변경_아님(self, status):
        assert requires_amendment_for(status, [AI_DOC_LC]) is False


def test_심각도_변환은_aiService_세_값을_다_다룬다():
    assert AI_SEVERITY_TO_FRONTEND == {
        "critical": "Critical",
        "warning": "Warning",
        "info": "Info",
    }

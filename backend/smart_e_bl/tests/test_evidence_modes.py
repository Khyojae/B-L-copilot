"""모드 스위치 — 같은 DB·같은 입력에 P·E1·E2·E3 를 돌려 가며 판정만 달라지는가 (작업분배 B5).

실험기(A6)의 계약: set_evidence_mode() 한 번 → INSERT → SELECT. 각 모드가
표 1 의 "무엇을 막는가 / 무엇이 새는가"대로 동작해야 한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser

from evidence_fixtures import EvidenceDoc, insert_value, make_evidence_doc, set_mode


@pytest.fixture
async def doc(session: AsyncSession, user: AppUser) -> EvidenceDoc:
    return await make_evidence_doc(session, user)


async def _status(session: AsyncSession, doc: EvidenceDoc, mode: str, **kw) -> dict:
    await set_mode(session, mode)
    return await insert_value(session, doc, **kw)


async def test_기본_모드는_E3다(session: AsyncSession):
    row = (await session.execute(text("SELECT current_evidence_mode()"))).scalar_one()
    assert row == "E3"


async def test_판정에_쓴_모드가_행에_남는다(session: AsyncSession, doc: EvidenceDoc):
    for i, mode in enumerate(("P", "E1", "E2", "E3")):
        fv = await _status(
            session, doc, mode, field_code="BL.BL_NO", value="HLCUBEN2100123456", span=(2, 3),
            is_representative=(i == 0),
        )
        assert fv["evidence_mode"] == mode


class TestHallucinationWithFabricatedCoords:
    """간극 A: 값도 좌표도 지어낸 경우. 좌표는 실재하는 스팬(토큰 2)을 가리킨다."""

    KW = dict(field_code="BL.BL_NO", value="HLCUBEN2100999999", span=(2, 3), grade="CONFIRMED")

    async def test_P는_아무것도_막지_않는다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(session, doc, "P", **self.KW)
        assert fv["evidence_status"] is None
        assert fv["grade"] == "CONFIRMED"
        assert fv["in_trusted"] == 1

    async def test_E1은_좌표가_있으므로_통과시킨다(self, session: AsyncSession, doc: EvidenceDoc):
        # 좌표 존재만 검사 → 환각이 새어 나간다 (E1 의 FCR > 0 의 실증)
        fv = await _status(session, doc, "E1", **self.KW)
        assert (fv["evidence_status"], fv["derivation"]) == ("GROUNDED", "NONE")
        assert fv["in_trusted"] == 1

    async def test_E2는_내용_불일치로_격리한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(session, doc, "E2", **self.KW)
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["in_trusted"] == 0

    async def test_E3도_격리한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(session, doc, "E3", **self.KW)
        assert fv["evidence_status"] == "UNGROUNDED"


class TestNotationVariant:
    """옳은 값의 표기 변형 (12 AUG 2026 vs 2026-08-12). E2 의 오격리(FQR) 와 E3 의 회복."""

    KW = dict(field_code="BL.DATE_OF_ISSUE", value="2026-08-12", span=(11, 14))

    async def test_E2는_표기_변형을_격리한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(session, doc, "E2", **self.KW)
        assert fv["evidence_status"] == "UNGROUNDED"

    async def test_E3는_FORMAT_파생으로_인정한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(session, doc, "E3", **self.KW)
        assert (fv["derivation"], fv["evidence_status"]) == ("FORMAT", "DERIVED")
        assert fv["in_trusted"] == 1


class TestNoCoordinates:
    """좌표 없는 LLM 갭필 값."""

    async def test_E1은_좌표가_없으면_격리한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(
            session, doc, "E1", field_code="BL.CONTAINER_NO", value="MSKU1234567", page=None, source_layer="LLM",
        )
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["evidence_reason"] == "NO_COORDS"

    async def test_E2는_역추적으로_되찾아_통과시킨다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(
            session, doc, "E2", field_code="BL.CONTAINER_NO", value="MSKU1234567", page=None, source_layer="LLM",
        )
        assert fv["evidence_status"] == "GROUNDED"
        assert (fv["evidence_token_from"], fv["evidence_token_to"]) == (23, 24)

    async def test_P는_좌표_없는_값도_그대로_신뢰한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await _status(
            session, doc, "P", field_code="BL.CONTAINER_NO", value="GHOST9999999", page=None, source_layer="LLM",
        )
        assert fv["in_trusted"] == 1

"""면제 조항 봉인 — 자동 경로가 수동 입력을 참칭할 수 없는가 (계획서 §4.5 요건 3).

근거 제약의 면제 조항(MANUAL·JSON)은 없앨 수 없다. 문제는 면제 조건을 쓰기 경로가
스스로 고를 수 있느냐다. MANUAL 은 실제 행위자(app_user) 식별자를 요구하므로,
좌표가 없다는 이유만으로 자동 추출값을 "수동 입력"으로 기록하는 경로가 막힌다.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser

from evidence_fixtures import EvidenceDoc, insert_value, make_evidence_doc, set_mode


@pytest.fixture
async def doc(session: AsyncSession, user: AppUser) -> EvidenceDoc:
    await set_mode(session, "E3")
    return await make_evidence_doc(session, user)


async def test_행위자_없는_MANUAL은_거부된다(session: AsyncSession, doc: EvidenceDoc):
    with pytest.raises(IntegrityError, match="field_value_manual_actor_ck"):
        await insert_value(
            session, doc, field_code="BL.BL_NO", value="MADE-UP", extractor="MANUAL", page=None,
        )


async def test_행위자가_있는_MANUAL은_면제된다(session: AsyncSession, doc: EvidenceDoc):
    fv = await insert_value(
        session, doc, field_code="BL.BL_NO", value="TYPED-BY-HUMAN",
        extractor="MANUAL", page=None, edited_by=doc.user_id,
    )
    assert fv["evidence_status"] is None
    assert fv["evidence_reason"] == "EXEMPT_MANUAL"
    assert fv["grade"] == "CONFIRMED"
    assert fv["in_trusted"] == 1


async def test_좌표_없는_자동값은_MANUAL로_위장하지_못하고_정직하게_격리된다(
    session: AsyncSession, doc: EvidenceDoc
):
    # 자동 경로가 할 수 있는 최선: OCR_LLM 그대로, 좌표 없이 저장 → 역추적 실패 → UNGROUNDED
    fv = await insert_value(
        session, doc, field_code="BL.BL_NO", value="MADE-UP", extractor="OCR_LLM", page=None,
    )
    assert fv["evidence_status"] == "UNGROUNDED"
    assert fv["in_trusted"] == 0


async def test_P_모드에서도_행위자_제약은_유지된다(session: AsyncSession, doc: EvidenceDoc):
    # 면제 봉인은 모드와 무관한 무결성 제약이다
    await set_mode(session, "P")
    with pytest.raises(IntegrityError, match="field_value_manual_actor_ck"):
        await insert_value(
            session, doc, field_code="BL.BL_NO", value="MADE-UP", extractor="MANUAL", page=None,
        )

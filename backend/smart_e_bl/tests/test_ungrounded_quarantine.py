"""핵심 회귀 — 근거 없는 값이 실제로 격리되는가 (계획서 §11 최소 회귀 테스트).

추출기가 문서에 없는 값을 반환했을 때 그 값이 UNGROUNDED + 사람 검토 등급으로
저장되고, 신뢰 뷰에는 나오지 않되 검토 큐에는 나오는 것. 이 하나가 깨지면
논문의 주장이 거짓이 된다. (작업분배 B4 "없는 값이 자동 확정되면 실패")
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser

from evidence_fixtures import EvidenceDoc, insert_value, make_evidence_doc, set_mode


@pytest.fixture
async def doc(session: AsyncSession, user: AppUser) -> EvidenceDoc:
    await set_mode(session, "E3")
    return await make_evidence_doc(session, user)


async def test_문서에_없는_값은_자동_확정되지_않는다(session: AsyncSession, doc: EvidenceDoc):
    # 추출기가 CONFIRMED 등급으로 환각값을 넘긴다 — 좌표까지 그럴듯하게 붙여서
    fv = await insert_value(
        session, doc,
        field_code="BL.CONSIGNEE",
        value="Samsung Electronics Co., Ltd.",
        span=(18, 22),   # 실재하는 스팬(SHIPPER HAPAG LLOYD AG)이지만 값과 무관
        grade="CONFIRMED",
        source_layer="LLM",
    )

    # 1. 거부되지 않고 저장됐다 (정보 손실 없음)
    assert fv["value"] == "Samsung Electronics Co., Ltd."
    # 2. UNGROUNDED 로 표시되고 사람 검토 등급으로 강등됐다
    assert fv["evidence_status"] == "UNGROUNDED"
    assert fv["grade"] == "REVIEW_REQUIRED"
    assert fv["evidence_reason"] == "CONTENT_MISMATCH"
    # 3. 대표값 자격은 유지된다 — 박탈하면 검토 큐에서도 사라진다
    assert fv["is_representative"] is True
    # 4. 기계 경로(신뢰 뷰)에는 보이지 않는다
    assert fv["in_trusted"] == 0
    # 5. 사람 경로(검토 큐)에는 보인다
    assert fv["in_review_queue"] == 1


async def test_문서에_있는_값은_자동_확정된다(session: AsyncSession, doc: EvidenceDoc):
    fv = await insert_value(session, doc, field_code="BL.SHIPPER", value="HAPAG LLOYD AG", span=(19, 22))
    assert fv["evidence_status"] == "GROUNDED"
    assert fv["grade"] == "CONFIRMED"
    assert fv["in_trusted"] == 1
    assert fv["in_review_queue"] == 0


async def test_쓰기_경로가_GROUNDED를_주장해도_트리거가_덮어쓴다(session: AsyncSession, doc: EvidenceDoc):
    fv = await insert_value(
        session, doc, field_code="BL.BL_NO", value="NOT-IN-DOCUMENT", span=(2, 3),
        evidence_status="GROUNDED",
    )
    assert fv["evidence_status"] == "UNGROUNDED"


async def test_격리값을_등급만_올려_확정할_수_없다(session: AsyncSession, doc: EvidenceDoc):
    """면제 조항 봉인의 귀결: 자동 추출값은 grade 를 CONFIRMED 로 고쳐도 다시 격리된다."""
    fv = await insert_value(session, doc, field_code="BL.BL_NO", value="NOT-IN-DOCUMENT", span=(2, 3))
    await session.execute(
        text("UPDATE field_value SET grade = 'CONFIRMED' WHERE id = :id"), {"id": fv["id"]}
    )
    row = (await session.execute(
        text("SELECT grade, evidence_status FROM field_value WHERE id = :id"), {"id": fv["id"]}
    )).one()
    assert tuple(row) == ("REVIEW_REQUIRED", "UNGROUNDED")


async def test_사람이_행위자를_남기고_수동_입력으로_바꾸면_확정된다(session: AsyncSession, doc: EvidenceDoc):
    fv = await insert_value(session, doc, field_code="BL.BL_NO", value="NOT-IN-DOCUMENT", span=(2, 3))
    await session.execute(
        text(
            "UPDATE field_value SET grade = 'CONFIRMED', extractor = 'MANUAL', edited_by = :u WHERE id = :id"
        ),
        {"id": fv["id"], "u": doc.user_id},
    )
    row = (await session.execute(
        text(
            """
            SELECT grade, evidence_status, evidence_reason,
                   (SELECT count(*) FROM field_value_trusted t WHERE t.id = fv.id)
            FROM field_value fv WHERE id = :id
            """
        ),
        {"id": fv["id"]},
    )).one()
    assert tuple(row) == ("CONFIRMED", None, "EXEMPT_MANUAL", 1)


async def test_신뢰_뷰는_격리값을_제외한_나머지를_모두_보여준다(session: AsyncSession, doc: EvidenceDoc):
    ok = await insert_value(session, doc, field_code="BL.SHIPPER", value="HAPAG LLOYD AG", span=(19, 22))
    bad = await insert_value(session, doc, field_code="BL.CONSIGNEE", value="NOBODY", span=(19, 22))
    nf = await insert_value(session, doc, field_code="BL.LC_NO", value=None, grade="NOT_FOUND", page=None)

    rows = await session.execute(
        text("SELECT id FROM field_value_trusted WHERE shipment_id = :s"), {"s": doc.shipment_id}
    )
    ids = {r[0] for r in rows}
    assert ok["id"] in ids
    assert nf["id"] in ids
    assert bad["id"] not in ids

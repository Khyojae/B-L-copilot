"""트리거 단위 테스트 — 파생 종류 분류가 정확한가 (계획서 §11 검증 방법 1).

기본 모드 E3 에서 Algorithm 1 의 각 분기를 하나씩 통과/실패로 확인한다.
규칙마다 하나씩 테스트를 붙인다(작업분배 B3).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser

from evidence_fixtures import (
    SAMPLE_TOKENS,
    EvidenceDoc,
    insert_value,
    make_evidence_doc,
    seed_glossary,
    set_mode,
    set_threshold,
)


@pytest.fixture
async def doc(session: AsyncSession, user: AppUser) -> EvidenceDoc:
    await set_mode(session, "E3")
    return await make_evidence_doc(session, user)


class TestNormalization:
    async def test_evidence_norm은_대소문자_공백_구두점을_버린다(self, session: AsyncSession):
        rows = await session.execute(
            text("SELECT evidence_norm('Busan, Korea'), evidence_norm(' 1,234.50 '), evidence_norm('k.g.s')")
        )
        assert tuple(rows.one()) == ("BUSANKOREA", "123450", "KGS")

    async def test_토큰_norm_text는_적재기가_준_값을_무시하고_DB가_채운다(
        self, session: AsyncSession, doc: EvidenceDoc
    ):
        row = await session.execute(
            text("SELECT text, norm_text FROM document_token WHERE document_id = :d AND idx = 6"),
            {"d": doc.document_id},
        )
        assert tuple(row.one()) == ("BUSAN,", "BUSAN")


class TestDerivationKinds:
    async def test_EXACT_정규화_후_완전_일치(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456", span=(2, 3))
        assert (fv["derivation"], fv["evidence_status"]) == ("EXACT", "GROUNDED")
        assert fv["grade"] == "CONFIRMED"
        assert fv["in_trusted"] == 1

    async def test_EXACT는_여러_토큰으로_갈라진_값도_잡는다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.SHIPPER", value="Hapag Lloyd AG", span=(19, 22))
        assert (fv["derivation"], fv["evidence_status"]) == ("EXACT", "GROUNDED")

    async def test_SUBSTRING_스팬에_포함(self, session: AsyncSession, doc: EvidenceDoc):
        # 파서가 이름표까지 스팬에 넣은 경우: "PORT OF LOADING BUSAN, KOREA" ⊃ "BUSAN"
        fv = await insert_value(session, doc, field_code="BL.PORT_OF_LOADING", value="BUSAN", span=(3, 8))
        assert (fv["derivation"], fv["evidence_status"]) == ("SUBSTRING", "GROUNDED")

    async def test_FORMAT_날짜_표기_변형(self, session: AsyncSession, doc: EvidenceDoc):
        # 원문 "12 AUG 2026", 추출값 ISO 표기
        fv = await insert_value(session, doc, field_code="BL.DATE_OF_ISSUE", value="2026-08-12", span=(8, 14))
        assert (fv["derivation"], fv["evidence_status"]) == ("FORMAT", "DERIVED")

    async def test_FORMAT_날짜가_다르면_격리(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.DATE_OF_ISSUE", value="2026-08-21", span=(11, 14))
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["evidence_reason"] == "CONTENT_MISMATCH"

    async def test_FORMAT_수량_천단위_구분자(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.GROSS_WEIGHT", value="1234.5", span=(16, 18))
        assert (fv["derivation"], fv["evidence_status"]) == ("FORMAT", "DERIVED")

    async def test_FORMAT_수량이_다르면_격리(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.GROSS_WEIGHT", value="1234.6", span=(16, 18))
        assert fv["evidence_status"] == "UNGROUNDED"

    async def test_GLOSSARY_용어사전_별칭_경유(self, session: AsyncSession, doc: EvidenceDoc):
        await seed_glossary(session)
        # LLM 이 UN/LOCODE 로 정규화해 돌려준 값. 원문에는 "BUSAN, KOREA" 만 있다.
        fv = await insert_value(session, doc, field_code="BL.PORT_OF_LOADING", value="KRPUS", span=(6, 8))
        assert (fv["derivation"], fv["evidence_status"]) == ("GLOSSARY", "DERIVED")

    async def test_GLOSSARY_사전_미적재면_같은_입력이_격리된다(self, session: AsyncSession, doc: EvidenceDoc):
        # 정직성 규약: 용어사전이 적재되지 않으면 E3 = E2.
        # 개발 DB 에는 scripts/load_evidence_glossary.py 가 올린 표준 사전이 있을 수 있으므로
        # 이 트랜잭션 안에서만 전부 비활성화한다(테스트 종료 시 롤백).
        await session.execute(text("UPDATE glossary_term SET is_active = false"))
        fv = await insert_value(session, doc, field_code="BL.PORT_OF_LOADING", value="KRPUS", span=(6, 8))
        assert fv["evidence_status"] == "UNGROUNDED"

    async def test_NONE_내용_불일치는_격리(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.BL_NO", value="HLCUBEN2100999999", span=(2, 3))
        assert (fv["derivation"], fv["evidence_status"]) == ("NONE", "UNGROUNDED")
        assert fv["evidence_reason"] == "CONTENT_MISMATCH"
        assert fv["grade"] == "REVIEW_REQUIRED"

    async def test_파생_순서는_EXACT가_먼저다(self, session: AsyncSession, doc: EvidenceDoc):
        await seed_glossary(session)
        # 'KGS' 는 사전 별칭이기도 하지만 스팬에 그대로 있으므로 EXACT 로 기록돼야 한다
        fv = await insert_value(session, doc, field_code="BL.GROSS_WEIGHT", value="KGS", span=(17, 18))
        assert fv["derivation"] == "EXACT"


class TestSpanResolution:
    async def test_좌표_날조_스팬이_가리키는_토큰이_없으면_격리(self, session: AsyncSession, doc: EvidenceDoc):
        # 간극 A: 존재하지 않는 스팬 [900, 901) — E1 이라면 "좌표 있음"으로 통과했을 값
        fv = await insert_value(session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456", span=(900, 901))
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["evidence_reason"] == "SPAN_NOT_FOUND"

    async def test_스팬_없이_bbox만_있으면_기하로_스팬을_도출한다(self, session: AsyncSession, doc: EvidenceDoc):
        # 기존 파이프라인 경로: bbox 가 토큰 2 를 덮는다
        fv = await insert_value(
            session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456",
            bbox=(0.12, 0.04, 0.31, 0.08),
        )
        assert (fv["evidence_token_from"], fv["evidence_token_to"]) == (2, 3)
        assert fv["evidence_status"] == "GROUNDED"
        assert fv["evidence_reason"] == "SPAN_FROM_BBOX"

    async def test_bbox가_다른_곳을_가리키면_격리(self, session: AsyncSession, doc: EvidenceDoc):
        # 좌표는 실재하지만(토큰 23 컨테이너 번호) 값과 무관 — fabricated citation
        fv = await insert_value(
            session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456",
            bbox=(0.54, 0.22, 0.67, 0.26),
        )
        assert fv["evidence_status"] == "UNGROUNDED"

    async def test_통과한_값의_bbox는_스팬_토큰의_합집합으로_채워진다(
        self, session: AsyncSession, doc: EvidenceDoc
    ):
        fv = await insert_value(session, doc, field_code="BL.SHIPPER", value="HAPAG LLOYD AG", span=(19, 22))
        assert fv["bbox_x1"] == pytest.approx(0.55)
        assert fv["bbox_x2"] == pytest.approx(0.69)


class TestReattachment:
    """§4.6 근거 역추적 — 좌표 없는 LLM 값을 토큰 계층에서 되찾는다."""

    async def test_좌표_없는_LLM값이_원문에_있으면_되찾아_GROUNDED(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(
            session, doc, field_code="BL.CONTAINER_NO", value="MSKU1234567",
            page=None, source_layer="LLM",
        )
        assert (fv["evidence_token_from"], fv["evidence_token_to"]) == (23, 24)
        assert fv["page"] == 1
        assert (fv["derivation"], fv["evidence_status"]) == ("EXACT", "GROUNDED")
        assert fv["evidence_reason"].startswith("REATTACHED sim=")

    async def test_여러_토큰짜리_값도_창을_넓혀_되찾는다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(
            session, doc, field_code="BL.SHIPPER", value="Hapag Lloyd AG", page=None, source_layer="LLM",
        )
        assert (fv["evidence_token_from"], fv["evidence_token_to"]) == (19, 22)
        assert fv["evidence_status"] == "GROUNDED"

    async def test_원문에_없는_LLM값은_환각_후보로_격리(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(
            session, doc, field_code="BL.CONSIGNEE", value="Samsung Electronics Co., Ltd.",
            page=None, source_layer="LLM",
        )
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["evidence_reason"].startswith("NO_EVIDENCE_SPAN")
        assert fv["evidence_token_from"] is None

    async def test_임계값_θ는_설정으로_바뀐다(self, session: AsyncSession, doc: EvidenceDoc):
        # 'MSKU1234561' (한 글자 오독) 은 θ=0.8 에서 못 찾고, θ 를 낮추면 SIMILARITY 로 되찾는다
        fv = await insert_value(
            session, doc, field_code="BL.CONTAINER_NO", value="MSKU1234561", page=None, source_layer="LLM",
        )
        assert fv["evidence_status"] == "UNGROUNDED"

        await set_threshold(session, 0.5)
        fv = await insert_value(
            session, doc, field_code="BL.CONTAINER_NO", value="MSKU1234561", page=None, source_layer="LLM",
            is_representative=False,  # 한 선적·한 필드에 대표값은 하나뿐(field_value_representative_uk)
        )
        assert (fv["derivation"], fv["evidence_status"]) == ("SIMILARITY", "DERIVED")


class TestExemptions:
    async def test_NOT_FOUND는_값이_없으므로_검사하지_않는다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.LC_NO", value=None, grade="NOT_FOUND", page=None)
        assert fv["evidence_status"] is None
        assert fv["evidence_reason"] == "NOT_FOUND"
        assert fv["grade"] == "NOT_FOUND"

    async def test_JSON_구조화_입력은_면제(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(
            session, doc, field_code="BL.BL_NO", value="ANYTHING", extractor="JSON", page=None,
        )
        assert fv["evidence_status"] is None
        assert fv["evidence_reason"] == "EXEMPT_JSON"
        assert fv["in_trusted"] == 1

    async def test_토큰_계층이_없는_서류의_자동값은_격리(self, session: AsyncSession, user: AppUser):
        await set_mode(session, "E3")
        bare = await make_evidence_doc(session, user, tokens=False)
        fv = await insert_value(session, bare, field_code="BL.BL_NO", value="X", bbox=(0.1, 0.1, 0.2, 0.2))
        assert fv["evidence_status"] == "UNGROUNDED"
        assert fv["evidence_reason"] == "NO_TOKEN_LAYER"


class TestUpdatePath:
    async def test_근거와_무관한_갱신은_판정을_바꾸지_않는다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456", span=(2, 3))
        await session.execute(
            text("UPDATE field_value SET is_representative = false, evidence_status = 'UNGROUNDED' WHERE id = :id"),
            {"id": fv["id"]},
        )
        row = (await session.execute(
            text("SELECT evidence_status, is_representative FROM field_value WHERE id = :id"), {"id": fv["id"]}
        )).one()
        # 쓰기 경로가 판정 컬럼을 직접 바꾸려 해도 트리거가 이전 판정으로 되돌린다
        assert tuple(row) == ("GROUNDED", False)

    async def test_값을_바꾸면_다시_검사한다(self, session: AsyncSession, doc: EvidenceDoc):
        fv = await insert_value(session, doc, field_code="BL.BL_NO", value="HLCUBEN2100123456", span=(2, 3))
        await session.execute(
            text("UPDATE field_value SET value = 'HLCUBEN2100999999' WHERE id = :id"), {"id": fv["id"]}
        )
        row = (await session.execute(
            text("SELECT evidence_status, grade FROM field_value WHERE id = :id"), {"id": fv["id"]}
        )).one()
        assert tuple(row) == ("UNGROUNDED", "REVIEW_REQUIRED")


async def test_샘플_토큰은_idx가_연속이다():
    # 픽스처 자체의 불변식 — 역추적 창 계산이 idx 연속성을 전제한다
    assert len(SAMPLE_TOKENS) == 24

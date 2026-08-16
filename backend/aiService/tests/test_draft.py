"""B/L 초안 생성 테스트 — 확인 필요 판정과 검증 준비 상태."""

from __future__ import annotations

import pytest
from conftest import complete_bl_bboxes, region_bbox

from ocr.draft import FIELD_LABELS, ReviewReason, build_draft
from ocr.extractor import OCRExtractor
from ocr.field_parser import FieldParser
from ocr.pipeline import IntakePipeline
from ocr.types import (
    BL_FIELD_NAMES,
    BBox,
    BLFields,
    ConfidenceGrade,
    OCRResult,
    grade_for,
)


def draft_of(path: str):
    ocr = OCRExtractor().from_json(path)
    return build_draft(FieldParser().parse(ocr), ocr)


class TestDraftShape:
    def test_모든_필드가_초안에_들어간다(self, complete_label):
        draft = draft_of(complete_label)

        assert [f.name for f in draft.fields] == list(BL_FIELD_NAMES)

    def test_한국어_라벨이_붙는다(self, complete_label):
        draft = draft_of(complete_label)

        assert draft.get("bl_no").label == "B/L 번호"
        assert draft.get("port_of_loading").label == "선적항"
        # 화면에서 쓰는 값이라 빠진 필드가 있으면 안 된다
        assert set(FIELD_LABELS) == set(BL_FIELD_NAMES)

    def test_OCR_메타를_함께_싣는다(self, complete_label):
        draft = draft_of(complete_label)

        assert draft.image_id == "TEST_BL_0001"
        assert draft.source == "json"
        assert draft.ocr_mean_confidence == 1.0


class TestReviewFlags:
    def test_누락된_핵심필드는_확인_대상이다(self, label_factory):
        path = label_factory([region_bbox("BILL OF LADING", "header")])
        draft = draft_of(path)

        bl_no = draft.get("bl_no")
        assert bl_no.needs_review
        assert bl_no.review_reason is ReviewReason.MISSING_CRITICAL
        assert bl_no.is_critical

    def test_누락된_비핵심필드는_사유가_다르다(self, complete_label):
        # complete 라벨에 notify 는 있으므로 별도로 없는 경우를 만든다
        draft = draft_of(complete_label)
        # voyage_no 는 비핵심. 값이 있으니 확인 대상이 아니다.
        assert not draft.get("voyage_no").is_critical

    def test_저신뢰_필드는_확인_대상이다(self):
        bboxes = [BBox("GAE WOON CO., LTD.", 200, 220, 700, 250, confidence=0.55)]
        ocr = OCRResult("T", 1654, 2340, "선하증권", bboxes, "json")

        draft = build_draft(FieldParser().parse(ocr), ocr)

        shipper = draft.get("shipper")
        assert shipper.needs_review
        assert shipper.review_reason is ReviewReason.LOW_CONFIDENCE
        assert "정확도가 낮" in shipper.review_message

    def test_신뢰도가_높으면_확인이_필요없다(self, complete_label):
        draft = draft_of(complete_label)

        assert not draft.get("shipper").needs_review
        assert draft.get("shipper").review_reason is None

    def test_핵심필드의_앵커추출은_확인_대상이다(self):
        bboxes = [
            BBox("B/L NO", 100, 1900, 260, 1930, confidence=1.0),
            BBox("SEAU1234567", 280, 1900, 560, 1930, confidence=1.0),
        ]
        ocr = OCRResult("T", 1654, 2340, "선하증권", bboxes, "json")

        draft = build_draft(FieldParser().parse(ocr), ocr)

        bl_no = draft.get("bl_no")
        assert bl_no.value == "SEAU1234567"
        # 앵커 감점(0.85)은 확정 경계(0.90) 아래지만, 의심스러운 것은 OCR 이
        # 아니라 매핑이다. 저신뢰로 설명하면 원본의 엉뚱한 곳을 보게 된다.
        assert bl_no.review_reason is ReviewReason.ANCHOR_DERIVED

    def test_비핵심필드의_앵커추출은_확인_대상이_아니다(self):
        # 전 필드에 걸면 확인 큐가 불어나 F1 의 시간 단축 효과가 사라진다.
        fields = BLFields()
        fields.set_field("vessel", "MSC BIANCA", 0.99, "anchor")

        draft = build_draft(fields)

        assert not draft.get("vessel").needs_review

    def test_확인목록은_핵심필드를_앞에_둔다(self, label_factory):
        path = label_factory([region_bbox("BILL OF LADING", "header")])
        draft = draft_of(path)

        criticals = [f.is_critical for f in draft.review_fields]
        # True 가 모두 앞에 몰려 있어야 한다
        assert criticals == sorted(criticals, reverse=True)

    def test_임계값을_낮추면_확인_대상이_준다(self):
        bboxes = [BBox("GAE WOON CO., LTD.", 200, 220, 700, 250, confidence=0.55)]
        ocr = OCRResult("T", 1654, 2340, "선하증권", bboxes, "json")
        fields = FieldParser().parse(ocr)

        strict = build_draft(fields, ocr, threshold=0.80)
        lenient = build_draft(fields, ocr, threshold=0.50)

        assert strict.get("shipper").needs_review
        assert not lenient.get("shipper").needs_review


class TestVerificationReadiness:
    def test_핵심필드가_모두_있으면_검증_가능하다(self, complete_label):
        assert draft_of(complete_label).is_ready_for_verification

    def test_핵심필드가_비면_검증_불가다(self, label_factory):
        # 값이 없는 채로 F3 를 돌리면 결과가 '값 없음 하자'로 도배된다.
        bboxes = [b for b in complete_bl_bboxes() if "B/L NO" not in b["data"]]
        draft = draft_of(label_factory(bboxes))

        assert not draft.is_ready_for_verification

    def test_비핵심필드_누락은_검증을_막지_않는다(self, label_factory):
        bboxes = [b for b in complete_bl_bboxes() if "FREIGHT" not in b["data"]]
        draft = draft_of(label_factory(bboxes))

        assert draft.get("total_freight").value is None
        assert draft.is_ready_for_verification


class TestCompleteness:
    def test_채워진_비율을_센다(self, complete_label):
        draft = draft_of(complete_label)

        assert 0.0 < draft.completeness() <= 1.0

    def test_아무것도_없으면_0이다(self, label_factory):
        draft = draft_of(label_factory([]))

        assert draft.completeness() == 0.0
        assert not draft.is_ready_for_verification


class TestSerialization:
    def test_dict로_직렬화된다(self, complete_label):
        payload = draft_of(complete_label).to_dict()

        assert payload["image_id"] == "TEST_BL_0001"
        assert len(payload["fields"]) == len(BL_FIELD_NAMES)
        assert payload["is_ready_for_verification"] is True
        first = payload["fields"][0]
        assert set(first) == {
            "name", "label", "value", "confidence", "source", "grade",
            "grade_label", "is_critical", "needs_review", "review_reason",
            "review_message",
        }

    def test_review_reason은_문자열로_나간다(self, label_factory):
        # JSON 직렬화 대상이므로 Enum 이 그대로 나가면 안 된다.
        payload = draft_of(label_factory([])).to_dict()

        reasons = {f["review_reason"] for f in payload["fields"]}
        assert reasons <= {"missing", "missing_critical"}
        assert all(isinstance(r, str) for r in reasons)


class TestPipeline:
    def test_라벨_한건을_초안까지_처리한다(self, complete_label):
        draft = IntakePipeline().run_from_json(complete_label)

        assert draft.get("bl_no").value == "HG290309"
        assert draft.is_ready_for_verification

    def test_배치_처리에서_실패건은_건너뛴다(self, tmp_path, label_factory, capsys):
        label_factory(complete_bl_bboxes(), identifier="BL_001")
        (tmp_path / "broken.json").write_text("깨진 파일", encoding="utf-8")

        drafts = IntakePipeline().run_batch(str(tmp_path))

        assert [d.image_id for d in drafts] == ["BL_001"]
        assert "broken.json" in capsys.readouterr().out

    def test_max_files로_개수를_제한한다(self, tmp_path, label_factory):
        for i in range(5):
            label_factory(complete_bl_bboxes(), identifier=f"BL_{i:03d}")

        drafts = IntakePipeline().run_batch(str(tmp_path), max_files=2)

        assert len(drafts) == 2


class TestFieldValueContract:
    def test_알_수_없는_필드는_거부한다(self):
        fields = BLFields()

        with pytest.raises(ValueError, match="알 수 없는 필드"):
            fields.set_field("존재하지_않음", "값", 1.0, "region")

    def test_신뢰도는_0과_1_사이로_자른다(self):
        fields = BLFields()
        fields.set_field("bl_no", "ABC1234", 1.5, "region")

        assert fields.confidence["bl_no"] == 1.0

    def test_값을_None으로_덮으면_신뢰도도_지운다(self):
        fields = BLFields()
        fields.set_field("bl_no", "ABC1234", 0.9, "region")
        fields.set_field("bl_no", None, 0.9, "region")

        assert "bl_no" not in fields.confidence
        assert "bl_no" not in fields.provenance


class TestLabelEcho:
    """값에 서식 항목명이 섞인 경우 — remaining-work.md 3.3 절."""

    def _draft(self, **values):
        fields = BLFields()
        for name, value in values.items():
            fields.set_field(name, value, 1.0, "region")
        return build_draft(fields)

    def test_항목명을_품은_값은_확인_대상이다(self):
        draft = self._draft(
            description_of_goods="DESCRIPTION OF GOODS GROSS WEIGHT / SAW MACHINE"
        )

        assert draft.get("description_of_goods").review_reason is ReviewReason.LABEL_ECHOED

    def test_항목명의_조각인_값도_확인_대상이다(self):
        # "OCEAN VESSEL" 라벨에서 잘려 나온 값. 실제로 관측된 오추출이다.
        draft = self._draft(vessel="OCEAN")

        assert draft.get("vessel").review_reason is ReviewReason.LABEL_ECHOED

    def test_신뢰도가_1이어도_잡는다(self):
        # 텍스트 레이어 PDF 는 전 필드가 1.0 이라 저신뢰 판정이 영원히
        # 안 걸린다. 그 경로에서 확인 대기열이 비는 것이 3.3 절의 결함이다.
        draft = self._draft(place_of_issue="PLACE OF ISSUE PUSAN DATE OF ISSUE")
        field = draft.get("place_of_issue")

        assert field.confidence == 1.0
        assert field.needs_review

    def test_정상_값은_오탐하지_않는다(self):
        draft = self._draft(
            shipper="GAE WOON CO., LTD.",
            consignee="DHHJ FRANCHISING CO., LTD.",
            vessel="MSC BIANCA",
            port_of_loading="BUSAN, KOREA",
            gross_weight="884.00 KG",
            measurement="349.64 CBM",
            total_freight="$1,741.56",
        )

        flagged = [
            f.name for f in draft.fields
            if f.review_reason is ReviewReason.LABEL_ECHOED
        ]
        assert not flagged

    def test_운임_값의_관용구는_항목명이_아니다(self):
        # FREIGHT PREPAID 는 항목명처럼 보이지만 운임란의 값이다.
        draft = self._draft(total_freight="FREIGHT PREPAID $1,741.56")

        assert draft.get("total_freight").review_reason is not ReviewReason.LABEL_ECHOED

    def test_항목명이_딸려온_PDF는_확인을_요구한다(self, tmp_path):
        """3.3 절이 기록한 실패를 그대로 재현한다.

        텍스트 레이어는 신뢰도가 전부 1.0 이라 저신뢰 판정이 걸리지 않는다.
        그 상태에서 구역이 밀려 항목명이 값에 딸려오면, 예전에는 확인
        대기열이 비어 사람이 아무것도 보지 않았다.
        """
        from conftest import write_bl_pdf

        bboxes = [
            b for b in complete_bl_bboxes()
            if "CELL ASSEMBLY" not in (b.get("data") or "")
        ]
        bboxes.append(
            region_bbox("DESCRIPTION OF GOODS 27 PKG CELL ASSEMBLY", "cargo",
                        width_ratio=0.40)
        )
        path = write_bl_pdf(tmp_path, bboxes, name="misaligned.pdf")

        draft = IntakePipeline().run_from_pdf(path)
        goods = draft.get("description_of_goods")

        assert draft.source == "pdf-text"
        assert goods.confidence == 1.0
        assert goods.review_reason is ReviewReason.LABEL_ECHOED, (
            "신뢰도 1.0 인 오추출을 아무도 확인하지 않게 됩니다"
        )


class TestConfidenceGrade:
    """신뢰도 4단계 (기획안 v2 5.1 등급표)."""

    def test_등급_경계는_명세대로_090과_070이다(self):
        # 이 셋이 어긋나면 화면 색과 검증 차단이 명세와 갈라진다.
        assert grade_for("X", 0.90) is ConfidenceGrade.CONFIRMED
        assert grade_for("X", 0.89) is ConfidenceGrade.RECOMMENDED
        assert grade_for("X", 0.70) is ConfidenceGrade.RECOMMENDED
        assert grade_for("X", 0.69) is ConfidenceGrade.REQUIRED

    def test_값이_없으면_미검출이다(self):
        assert grade_for(None, 0.99) is ConfidenceGrade.UNDETECTED
        assert grade_for("", None) is ConfidenceGrade.UNDETECTED

    def test_신뢰도가_없으면_확정이다(self):
        # S3 편집기에서 사람이 고쳐 넣은 값. OCR 불확실성이 없다.
        assert grade_for("MSC BIANCA", None) is ConfidenceGrade.CONFIRMED

    def test_강등은_나쁜_쪽을_택한다(self):
        # 신뢰도가 만점이어도 스키마 위반이면 필수 확인이다.
        assert grade_for("X", 1.0, ConfidenceGrade.REQUIRED) is ConfidenceGrade.REQUIRED
        # 반대로 강등이 더 가벼우면 신뢰도 판정이 남는다.
        assert grade_for("X", 0.5, ConfidenceGrade.RECOMMENDED) is ConfidenceGrade.REQUIRED

    def test_항목명_혼입은_신뢰도와_무관하게_필수_확인이다(self):
        # 값이 틀린 것이지 흐릿한 것이 아니다 — 5.1 의 '스키마 위반'에 해당한다.
        fields = BLFields()
        fields.set_field("consignee", "DESCRIPTION OF GOODS SAW MACHINE", 1.0, "region")

        field = build_draft(fields).get("consignee")

        assert field.review_reason is ReviewReason.LABEL_ECHOED
        assert field.grade is ConfidenceGrade.REQUIRED

    def test_앵커_감점은_확인_권고에_머문다(self):
        # 필수 확인으로 올리면 검증이 차단되는데, 앵커 추출은 흔하다.
        fields = BLFields()
        fields.set_field("bl_no", "SEAU1234567", 0.85, "anchor")

        field = build_draft(fields).get("bl_no")

        assert field.review_reason is ReviewReason.ANCHOR_DERIVED
        assert field.grade is ConfidenceGrade.RECOMMENDED


class TestVerificationGate:
    """필수 확인 필드는 검증 실행을 막는다 (기획안 v2 5.1)."""

    def test_필수_확인_필드가_있으면_검증이_차단된다(self, complete_label):
        draft = draft_of(complete_label)
        assert draft.is_ready_for_verification

        draft.get("consignee").grade = ConfidenceGrade.REQUIRED

        assert not draft.is_ready_for_verification
        assert draft.review_required_fields == ["consignee"]

    def test_확인_권고는_검증을_막지_않는다(self, complete_label):
        # 5.1: "검증 실행은 가능하되 리포트에 미확인 항목으로 기재"
        draft = draft_of(complete_label)
        draft.get("consignee").grade = ConfidenceGrade.RECOMMENDED

        assert draft.is_ready_for_verification

    def test_미검출은_검증을_막지_않는다(self, label_factory):
        # 값 없음은 룰엔진이 missing_field 로 이미 잡는다. 차단까지 걸면
        # 같은 사실로 두 번 멈춰 세운다.
        bboxes = [b for b in complete_bl_bboxes() if "FREIGHT" not in b["data"]]
        draft = draft_of(label_factory(bboxes))

        assert draft.get("total_freight").grade is ConfidenceGrade.UNDETECTED
        assert draft.is_ready_for_verification

    def test_보류율은_필수_확인만_센다(self, complete_label):
        draft = draft_of(complete_label)
        draft.get("consignee").grade = ConfidenceGrade.REQUIRED
        draft.get("vessel").grade = ConfidenceGrade.UNDETECTED

        # 15 필드 중 필수 확인 1건. 미검출은 분자에 들어가지 않는다.
        assert draft.hold_ratio() == round(1 / len(draft.fields), 4)

    def test_임계값을_낮추면_두_경계가_함께_내려간다(self):
        # 한쪽만 내리면 필수 확인 구간이 남아 검증 차단이 풀리지 않는다.
        fields = BLFields()
        fields.set_field("shipper", "GAE WOON CO., LTD.", 0.55, "region")

        assert build_draft(fields).get("shipper").grade is ConfidenceGrade.REQUIRED
        assert (
            build_draft(fields, threshold=0.50).get("shipper").grade
            is ConfidenceGrade.CONFIRMED
        )

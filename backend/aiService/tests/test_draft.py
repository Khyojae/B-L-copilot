"""B/L 초안 생성 테스트 — 확인 필요 판정과 검증 준비 상태."""

from __future__ import annotations

import pytest
from conftest import complete_bl_bboxes, region_bbox

from ocr.draft import FIELD_LABELS, ReviewReason, build_draft
from ocr.extractor import OCRExtractor
from ocr.field_parser import FieldParser
from ocr.pipeline import IntakePipeline
from ocr.types import BL_FIELD_NAMES, BBox, BLFields, OCRResult


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
        # 앵커 감점(0.85)이 기본 임계값(0.80)을 넘으므로 저신뢰가 아니라
        # 앵커 사유로 잡혀야 한다.
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
            "name", "label", "value", "confidence", "is_critical",
            "needs_review", "review_reason", "review_message",
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

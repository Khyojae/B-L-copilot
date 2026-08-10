"""FieldParser 테스트 — 구역 추출, 앵커 fallback, 신뢰도 전파, 필드 정제."""

from __future__ import annotations

import pytest
from conftest import complete_bl_bboxes, make_bbox, region_bbox

from ocr.extractor import OCRExtractor
from ocr.field_parser import FieldParser, _is_valid_date_str
from ocr.types import ANCHOR_CONFIDENCE_PENALTY, BBox, OCRResult


def parse(path: str):
    return FieldParser().parse(OCRExtractor().from_json(path))


def ocr_of(bboxes: list[BBox]) -> OCRResult:
    return OCRResult(
        image_id="T",
        image_width=1654,
        image_height=2340,
        form_type="선하증권",
        bboxes=bboxes,
        source="json",
    )


class TestRegionExtraction:
    def test_정상_문서에서_핵심_필드를_모두_뽑는다(self, complete_label):
        fields = parse(complete_label)

        assert fields.bl_no == "HG290309"
        assert fields.shipper == "GAE WOON CO., LTD."
        assert fields.consignee == "DHHJ FRANCHISING CO., LTD."
        assert fields.port_of_loading == "OMA, JAPAN"
        assert fields.port_of_discharge == "SHINJIMA, JAPAN"
        assert fields.missing_critical_fields() == []

    def test_선적항과_양하항이_섞이지_않는다(self, label_factory):
        # 두 항구는 같은 y 대의 좌우 컬럼이다. 라인 단위로 묶으면
        # 한 줄이 되어 서로의 값을 오염시킨다.
        path = label_factory(
            [
                region_bbox("BUSAN, KOREA", "port_left", width_ratio=0.12),
                region_bbox("TOKYO, JAPAN", "port_right", width_ratio=0.12),
            ]
        )
        fields = parse(path)

        assert fields.port_of_loading == "BUSAN, KOREA"
        assert fields.port_of_discharge == "TOKYO, JAPAN"

    def test_선박명과_항차를_분리한다(self, label_factory):
        path = label_factory(
            [region_bbox("MSC BIANCA V.112", "vessel_info", width_ratio=0.22)]
        )
        fields = parse(path)

        assert fields.vessel == "MSC BIANCA"
        assert fields.voyage_no == "V.112"

    def test_발행일과_선적일을_위치로_구분한다(self, label_factory):
        # 발행일은 footer 최하단, 선적일은 그보다 위(freight).
        path = label_factory(
            [
                region_bbox("ON BOARD JUN 11, 2013", "freight", width_ratio=0.30),
                region_bbox("SEP 06, 2006", "footer", width_ratio=0.20),
            ]
        )
        fields = parse(path)

        assert fields.date_of_issue == "SEP 06, 2006"
        assert fields.on_board_date == "JUN 11, 2013"


class TestConfidencePropagation:
    def test_구역_bbox_신뢰도의_평균이_필드_신뢰도가_된다(self):
        bboxes = [
            BBox("GAE WOON CO., LTD.", 200, 220, 700, 250, confidence=0.90),
            BBox("SEOUL KOREA", 200, 260, 700, 290, confidence=0.70),
        ]
        fields = FieldParser().parse(ocr_of(bboxes))

        assert fields.shipper == "GAE WOON CO., LTD."
        assert fields.confidence["shipper"] == pytest.approx(0.80)

    def test_값이_없으면_신뢰도를_남기지_않는다(self, label_factory):
        # '값 없음'과 '신뢰도 0'은 의미가 다르다. 후자를 남기면
        # 저신뢰 목록에 누락 필드가 섞여 들어온다.
        path = label_factory([region_bbox("BILL OF LADING", "header")])
        fields = parse(path)

        assert fields.bl_no is None
        assert "bl_no" not in fields.confidence
        assert "bl_no" not in fields.provenance

    def test_저신뢰_필드를_골라낸다(self):
        bboxes = [
            BBox("GAE WOON CO., LTD.", 200, 220, 700, 250, confidence=0.55),
            BBox("DHHJ FRANCHISING CO., LTD.", 200, 480, 700, 510, confidence=0.99),
        ]
        fields = FieldParser().parse(ocr_of(bboxes))

        low = fields.low_confidence_fields(threshold=0.80)

        assert "shipper" in low
        assert "consignee" not in low

    def test_누락_필드는_저신뢰_목록에_없다(self, label_factory):
        path = label_factory([region_bbox("BILL OF LADING", "header")])
        fields = parse(path)

        assert fields.low_confidence_fields() == []
        assert "bl_no" in fields.missing_critical_fields()

    def test_구역_추출은_provenance가_region이다(self, complete_label):
        fields = parse(complete_label)

        assert fields.provenance["shipper"] == "region"


class TestAnchorFallback:
    def test_구역_밖의_값을_라벨로_찾는다(self):
        # 비표준 서식이라 B/L 번호가 구역 밖(좌측 하단)에 있는 경우.
        bboxes = [
            BBox("B/L NO", 100, 1900, 260, 1930, confidence=0.95),
            BBox("SEAU1234567", 280, 1900, 560, 1930, confidence=0.95),
        ]
        fields = FieldParser().parse(ocr_of(bboxes))

        assert fields.bl_no == "SEAU1234567"
        assert fields.provenance["bl_no"] == "anchor"

    def test_앵커_추출은_신뢰도에_감점을_준다(self):
        # OCR 이 확신해도 '라벨 오른쪽에 값이 있다'는 레이아웃 가정이
        # 틀릴 수 있어 구역 방식보다 불확실하다.
        bboxes = [
            BBox("PORT OF LOADING", 100, 1900, 400, 1930, confidence=1.0),
            BBox("BUSAN, KOREA", 420, 1900, 700, 1930, confidence=1.0),
        ]
        fields = FieldParser().parse(ocr_of(bboxes))

        assert fields.port_of_loading == "BUSAN, KOREA"
        assert fields.confidence["port_of_loading"] == pytest.approx(
            ANCHOR_CONFIDENCE_PENALTY
        )

    def test_앵커가_없으면_None을_돌려준다(self):
        bboxes = [BBox("아무 관련 없는 텍스트", 100, 1900, 400, 1930)]

        assert FieldParser()._find_by_anchor("bl_no", bboxes) is None


class TestFieldCleaning:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # 법인격 표기가 있는 줄을 고른다
            ("BILL OF LADING\nGAE WOON CO., LTD.", "GAE WOON CO., LTD."),
            # 앞의 ID 코드 제거
            ("HG290309 DHHJ FRANCHISING CO., LTD.", "DHHJ FRANCHISING CO., LTD."),
            # 연락처 라인 제거
            ("GAE WOON CO., LTD.\nTEL) 02-1234-5678", "GAE WOON CO., LTD."),
            # 서식 헤더만 있으면 값이 없다
            ("BILL OF LADING\nNEGOTIABLE", None),
            ("", None),
        ],
    )
    def test_당사자명_정제(self, raw, expected):
        assert FieldParser()._clean_party_name(raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # 운송 유형 코드 제거
            ("CY/CFS BUSAN, KOREA", "BUSAN, KOREA"),
            # 콤마 있는 후보를 우선 (CITY, COUNTRY)
            ("KOREA\nBUSAN, KOREA", "BUSAN, KOREA"),
            # 원본 매수 표기 스킵
            ("THREE (3)\nBUSAN, KOREA", "BUSAN, KOREA"),
            # 합계 라인 스킵
            ("TOTAL 884 KG\nBUSAN, KOREA", "BUSAN, KOREA"),
            ("", None),
        ],
    )
    def test_항구명_정제(self, raw, expected):
        assert FieldParser()._clean_port_name(raw) == expected

    def test_화물명세는_수량_접두어와_추적코드를_뗀다(self):
        raw = "DLSU8179031\nDLSU8179031 27 PKG CELL ASSEMBLY, 259KG\nTOTAL 884 KG"

        assert FieldParser()._extract_description(raw) == "CELL ASSEMBLY"

    def test_화물명세는_중복을_합친다(self):
        raw = "27 PKG CELL ASSEMBLY\n13 PKG CELL ASSEMBLY\n5 PKG SAW MACHINE"

        assert FieldParser()._extract_description(raw) == "CELL ASSEMBLY / SAW MACHINE"

    def test_중량은_TOTAL_라인을_우선한다(self):
        raw = "27 PKG CELL ASSEMBLY, 259 KG\nTOTAL 884 KG"

        assert FieldParser()._extract_total_weight(raw) == "884 KG"

    def test_TOTAL이_없으면_마지막_중량을_쓴다(self):
        raw = "27 PKG, 259 KG\n13 PKG, 625 KG"

        assert FieldParser()._extract_total_weight(raw) == "625 KG"

    def test_용적은_TOTAL_라인을_우선한다(self):
        raw = "27 PKG 100.5 CBM\nTOTAL 349.64 CBM"

        assert FieldParser()._extract_total_cbm(raw) == "349.64 CBM"

    def test_BL번호는_화물추적코드를_거른다(self):
        # DLSU 로 시작하는 건 컨테이너 코드지 B/L 번호가 아니다.
        assert FieldParser()._pick_bl_no("DLSU8179031 HG290309") == "HG290309"

    def test_BL번호는_지나치게_긴_후보를_거른다(self):
        assert FieldParser()._pick_bl_no("ABCDEF123456789012") is None


class TestDateValidation:
    @pytest.mark.parametrize(
        "value, valid",
        [
            ("2014-09-15", True),
            ("09-11-2015", True),
            ("SEP 06, 2006", True),
            ("05-AUG-2016", True),
            ("60-55-2708", False),   # OCR 노이즈: 일·월 모두 범위 밖
            ("2014-13-45", False),   # 월 13, 일 45
            ("09-11-1800", False),   # 연도 범위 밖
        ],
    )
    def test_현실적인_날짜만_통과시킨다(self, value, valid):
        assert _is_valid_date_str(value) is valid


class TestEmptyInput:
    def test_bbox가_없어도_죽지_않는다(self, label_factory):
        fields = parse(label_factory([]))

        assert fields.to_dict() == {k: None for k in fields.to_dict()}
        assert fields.confidence == {}
        assert len(fields.missing_critical_fields()) == 5

    def test_이미지_크기가_달라도_비율로_환산한다(self, tmp_path):
        # 구역 좌표는 비율이므로 해상도가 절반이어도 같은 필드가 나와야 한다.
        from conftest import write_label

        half = [
            {
                "data": b["data"],
                "x": [v // 2 for v in b["x"]],
                "y": [v // 2 for v in b["y"]],
            }
            for b in complete_bl_bboxes()
        ]
        path = write_label(tmp_path, half, identifier="HALF", width=827, height=1170)

        fields = parse(path)

        assert fields.bl_no == "HG290309"
        assert fields.port_of_loading == "OMA, JAPAN"

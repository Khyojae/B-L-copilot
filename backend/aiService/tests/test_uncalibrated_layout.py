"""보정되지 않은 레이아웃의 확인 유도 (14번).

문서 3.3절이 "실패 방향이 나쁜 결함"으로 분류한 자리다. 텍스트 레이어 PDF·
엑셀·이메일 본문은 **글자를 정확히 읽으므로 신뢰도가 전 필드 1.0** 이고,
그래서 저신뢰 판정이 원리적으로 발동하지 않는다. 가장 밀리기 쉬운 입력에서
신뢰도 신호가 죽어 있다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import complete_bl_bboxes, write_bl_pdf, write_label
from ocr import IntakePipeline
from ocr.draft import ReviewReason, build_draft
from ocr.types import BLFields, OCRResult

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF 미설치")

# 항목명이 왼쪽, 값이 오른쪽인 흔한 서식. 라벨 데이터셋 레이아웃과 다르므로
# 구역 좌표가 맞지 않는다 — 실무에서 받는 PDF 대부분이 이렇다.
ROWS = [
    ("B/L NO", "SMBL26080001"),
    ("SHIPPER", "HANWOO TRADING CO., LTD."),
    ("CONSIGNEE", "PACIFIC IMPORT GMBH"),
    ("OCEAN VESSEL", "MSC BIANCA"),
    ("PORT OF LOADING", "BUSAN, KOREA"),
    ("PORT OF DISCHARGE", "HAMBURG, GERMANY"),
    ("PLACE OF ISSUE", "PUSAN"),
    ("DATE OF ISSUE", "2026-07-30"),
]


@pytest.fixture
def uncalibrated_pdf(tmp_path) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((200, 60), "BILL OF LADING", fontsize=18, fontname="helv")

    y = 110
    for label, value in ROWS:
        page.insert_text((60, y), label, fontsize=9, fontname="helv")
        page.insert_text((250, y), value, fontsize=10, fontname="helv")
        y += 30

    path = tmp_path / "uncalibrated.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _by_name(draft) -> dict:
    return {f["name"]: f for f in draft.to_dict()["fields"]}


class TestUncalibratedLayout:
    def test_핵심_필드가_확인_대기열에_들어간다(self, uncalibrated_pdf):
        draft = IntakePipeline().run_from_pdf(uncalibrated_pdf)
        fields = _by_name(draft)

        # 신뢰도 1.0 이고 항목명도 안 섞였지만 값이 밀린 경우.
        # 이런 값은 겉보기에 정상이라 사람이 보지 않으면 걸러지지 않는다.
        assert fields["port_of_discharge"]["needs_review"] is True

    def test_신뢰도가_1_0_이어도_확인을_요구한다(self, uncalibrated_pdf):
        draft = IntakePipeline().run_from_pdf(uncalibrated_pdf)

        flagged = [
            f for f in draft.to_dict()["fields"]
            if f["review_reason"] == ReviewReason.UNCALIBRATED_LAYOUT.value
        ]
        assert flagged, "보정되지 않은 레이아웃인데 확인 유도가 없다"
        # 저신뢰로 잡힌 것이 아니다 — 신뢰도는 만점이다.
        assert all(f["confidence"] == 1.0 for f in flagged)

    def test_핵심_필드만_대상이다(self, uncalibrated_pdf):
        # 전 필드에 걸면 확인 큐가 불어나 F1 의 시간 단축 효과가 사라진다.
        draft = IntakePipeline().run_from_pdf(uncalibrated_pdf)

        flagged = [
            f for f in draft.to_dict()["fields"]
            if f["review_reason"] == ReviewReason.UNCALIBRATED_LAYOUT.value
        ]
        assert all(f["is_critical"] for f in flagged)

    def test_확인_사유가_사람이_읽을_수_있다(self, uncalibrated_pdf):
        draft = IntakePipeline().run_from_pdf(uncalibrated_pdf)
        flagged = next(
            f for f in draft.to_dict()["fields"]
            if f["review_reason"] == ReviewReason.UNCALIBRATED_LAYOUT.value
        )

        assert "원본과 대조" in flagged["review_message"]


class TestCalibratedSourcesUnaffected:
    def test_라벨_JSON_은_영향받지_않는다(self, tmp_path):
        """구역 좌표는 이 데이터셋 레이아웃에 맞춰 교정된 값이다."""
        path = write_label(tmp_path, complete_bl_bboxes(), identifier="CAL")
        draft = IntakePipeline().run_from_json(path)

        reasons = {f["review_reason"] for f in draft.to_dict()["fields"]}
        assert ReviewReason.UNCALIBRATED_LAYOUT.value not in reasons

    def test_교정된_레이아웃_PDF_는_영향받지_않는다(self, tmp_path):
        # 같은 bbox 배치로 그린 PDF. 구역이 맞으므로 밀리지 않는다.
        path = write_bl_pdf(tmp_path, complete_bl_bboxes())
        draft = IntakePipeline().run_from_pdf(path)
        fields = _by_name(draft)

        # 값이 제대로 꽂혔는지 먼저 확인한다 — 이게 깨지면 이 테스트의 전제가
        # 무너지고, 아래 단언은 의미가 없어진다.
        assert fields["bl_no"]["value"] == "HG290309"


class TestSourceScope:
    @pytest.mark.parametrize("source,expected", [
        ("pdf-text", True),
        ("excel", True),
        ("email-body", True),
        ("json", False),
        ("paddleocr", False),   # OCR 신뢰도가 흔들리므로 저신뢰 판정이 돈다
        ("pdf-ocr", False),     # 〃
    ])
    def test_형식별로_적용_여부가_갈린다(self, source, expected):
        fields = BLFields()
        fields.set_field("port_of_discharge", "PUSAN", 1.0, "region")
        ocr = OCRResult(
            image_id="x", image_width=100, image_height=100,
            form_type="선하증권", bboxes=[], source=source,
        )

        draft = build_draft(fields, ocr)
        flagged = draft.get("port_of_discharge").review_reason

        assert (flagged == ReviewReason.UNCALIBRATED_LAYOUT) is expected

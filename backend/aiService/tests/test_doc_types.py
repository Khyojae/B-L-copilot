"""서류 종류 확장 테스트 — 판별, 앵커 추출, 초안 형태."""

from __future__ import annotations

import pytest
from conftest import (
    INVOICE_LINES,
    PACKING_LINES,
    complete_bl_bboxes,
    lines_to_bboxes,
    write_document_pdf,
)

from ocr import doc_types
from ocr.doc_parser import DocumentParser
from ocr.extractor import OCRExtractor
from ocr.pipeline import IntakePipeline


class TestDetection:
    def test_서식_제목으로_판별한다(self):
        assert doc_types.detect("COMMERCIAL INVOICE\nINVOICE NO 1") == "상업송장"
        assert doc_types.detect("PACKING LIST\nINVOICE NO 1") == "포장명세서"
        assert doc_types.detect("BILL OF LADING\nB/L NO 1") == "선하증권"

    def test_모르면_넘겨짚지_않는다(self):
        # 기본값을 선하증권으로 두면 송장이 B/L 좌표로 파싱되어
        # 그럴듯한 오값이 나온다. 오류가 아니라 값이라 조용하다.
        assert doc_types.detect("무엇인지 알 수 없는 문서") == "미상"
        assert doc_types.detect("") == "미상"

    def test_본문의_서류명에_속지_않는다(self):
        # 선하증권 본문의 "COMMERCIAL INVOICE" 는 요구 서류 목록의 한 줄이지
        # 이 서류의 제목이 아니다.
        text = "BILL OF LADING\n" + "\n" * 20 + "DOCUMENTS: COMMERCIAL INVOICE"

        assert doc_types.detect(text) == "선하증권"

    def test_구체적인_제목이_이긴다(self):
        # "COMMERCIAL INVOICE" 가 "INVOICE" 보다 구체적이다.
        assert doc_types.detect("COMMERCIAL INVOICE") == "상업송장"

    def test_선하증권은_전용_파서를_쓴다(self):
        # 좌표 교정본이 있으므로 앵커 전용 경로로 보내면 안 된다.
        assert doc_types.spec_for("선하증권") is None
        assert doc_types.spec_for("미상") is None
        assert doc_types.spec_for("상업송장") is not None


class TestInvoice:
    def test_모든_필드를_뽑는다(self, invoice_pdf):
        draft = IntakePipeline().run_from_pdf(invoice_pdf)

        assert draft.form_type == "상업송장"
        values = {f.name: f.value for f in draft.fields}
        assert values["invoice_no"] == "INV-2026-0417"
        assert values["buyer"] == "DHHJ FRANCHISING CO., LTD."
        assert values["total_amount"] == "USD 41,250.00"
        assert values["lc_no"] == "LC-2026-001"

    def test_다음_항목명이_값에_딸려오지_않는다(self, invoice_pdf):
        # INVOICE NO 아래에 INVOICE DATE 가 있어 "INV-2026-0417 INVOICE DATE"
        # 로 나왔던 자리다.
        draft = IntakePipeline().run_from_pdf(invoice_pdf)

        assert "INVOICE DATE" not in (draft.get("invoice_no").value or "")

    def test_상호의_마침표를_지우지_않는다(self, invoice_pdf):
        # "CO., LTD." 의 끝점은 구분 기호가 아니라 상호의 일부다.
        # 지우면 서류 간 상호 대조에서 표기가 갈린다.
        draft = IntakePipeline().run_from_pdf(invoice_pdf)

        assert draft.get("seller").value == "GAE WOON CO., LTD."


class TestPackingList:
    def test_모든_필드를_뽑는다(self, packing_list_pdf):
        draft = IntakePipeline().run_from_pdf(packing_list_pdf)

        assert draft.form_type == "포장명세서"
        values = {f.name: f.value for f in draft.fields}
        assert values["package_count"] == "27 CTNS"
        assert values["gross_weight"] == "884.00 KGS"
        assert values["net_weight"] == "812.00 KGS"
        assert values["measurement"] == "349.64 CBM"

    def test_짧은_항목명도_경계로_본다(self, packing_list_pdf):
        # 포장명세서의 `DATE` 는 4자라 부분 일치 차단선(6자)에 안 걸린다.
        # 칸 전체가 그 항목명일 때는 잡아야 한다.
        draft = IntakePipeline().run_from_pdf(packing_list_pdf)

        assert draft.get("invoice_no").value == "INV-2026-0417"


class TestDraftShape:
    """서류 종류가 달라도 초안 형태는 같아야 한다."""

    def test_같은_키를_낸다(self, invoice_pdf, bl_pdf):
        invoice = IntakePipeline().run_from_pdf(invoice_pdf).to_dict()
        bl = IntakePipeline().run_from_pdf(bl_pdf).to_dict()

        assert set(invoice) == set(bl)
        assert set(invoice["fields"][0]) == set(bl["fields"][0])

    def test_핵심_필드_판정이_명세를_따른다(self, invoice_pdf):
        draft = IntakePipeline().run_from_pdf(invoice_pdf)
        critical = {f.name for f in draft.fields if f.is_critical}

        assert critical == set(doc_types.spec_for("상업송장").critical)

    def test_라벨이_한국어로_나온다(self, packing_list_pdf):
        draft = IntakePipeline().run_from_pdf(packing_list_pdf)

        assert draft.get("package_count").label == "포장 수량"


class TestAnchorOnly:
    def test_앵커_추출은_신뢰도가_감점된다(self, invoice_pdf):
        # 좌표로 찾은 값과 같은 신뢰도를 주면 편집기가 확인을 유도하지 않는다.
        draft = IntakePipeline().run_from_pdf(invoice_pdf)
        filled = [f for f in draft.fields if f.value]

        assert filled
        assert all(f.confidence < 1.0 for f in filled)
        assert all(f.source == "anchor" for f in filled)

    def test_항목명이_없으면_비운다(self, tmp_path):
        # 놓치는 쪽이 지어내는 쪽보다 낫다 — 빈칸은 사람에게 묻지만,
        # 엉뚱한 값은 그럴듯해서 검증까지 흘러간다.
        lines = [(0.35, 0.06, "COMMERCIAL INVOICE")] + [
            (0.05, 0.20 + i * 0.05, f"관련 없는 줄 {i}") for i in range(12)
        ]
        path = write_document_pdf(tmp_path, lines, "sparse.pdf")

        draft = IntakePipeline().run_from_pdf(path)

        assert draft.form_type == "상업송장"
        assert not draft.is_ready_for_verification
        assert all(f.needs_review for f in draft.fields if not f.value)


class TestNoRegression:
    def test_선하증권은_그대로_구역_파서를_탄다(self, complete_label):
        draft = IntakePipeline().run_from_json(complete_label)

        assert draft.form_type == "선하증권"
        assert draft.get("bl_no").value == "HG290309"

    def test_라벨_JSON_과_PDF_가_같은_종류로_판별된다(self, tmp_path):
        boxes = lines_to_bboxes(INVOICE_LINES)
        from conftest import write_bl_pdf, write_label

        pdf = write_bl_pdf(tmp_path, boxes, name="inv.pdf")
        label = write_label(tmp_path, boxes, identifier="INV")

        pipeline = IntakePipeline()
        assert pipeline.run_from_pdf(pdf).form_type == "상업송장"
        # 라벨 JSON 의 form_type 은 "선하증권"이지만 본문 판별이 이긴다.
        assert pipeline.run_from_json(label).form_type == "상업송장"

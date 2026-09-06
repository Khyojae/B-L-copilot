"""LLM 구조화 추출 테스트 (기획안 5절 5번).

실제 API 는 부르지 않는다. `LLMFieldExtractor` 가 completion 을 주입받도록
만든 이유가 이것이다 — 외부 호출에 묶인 테스트는 네트워크가 죽으면 같이
죽고, 그때 코드가 멀쩡한지 알 수 없다.
"""

from __future__ import annotations

import json

import pytest

from conftest import complete_bl_bboxes, lines_to_bboxes, make_bbox, write_label
from ocr import IntakePipeline
from ocr.extractor import OCRExtractor
from ocr.field_parser import FieldParser
from ocr.llm_extract import LLM_CONFIDENCE, LLMFieldExtractor
from ocr.types import LOW_CONFIDENCE_THRESHOLD, BLFields


class FakeCompletion:
    """호출 내용을 기록하는 가짜 LLM."""

    def __init__(self, reply: str = "{}", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
def sparse_ocr(tmp_path):
    """핵심 필드 대부분이 비는 라벨. LLM 이 채울 자리를 만든다."""
    bboxes = [
        make_bbox("BILL OF LADING", 0.50, 0.06),
        make_bbox("OCEAN TRANSPORT DOCUMENT", 0.50, 0.09),
    ]
    path = write_label(tmp_path, bboxes, identifier="SPARSE")
    return OCRExtractor().from_json(path)


@pytest.fixture
def full_ocr(tmp_path):
    """핵심 필드가 다 채워지는 정상 라벨."""
    path = write_label(tmp_path, complete_bl_bboxes(), identifier="FULL")
    return OCRExtractor().from_json(path)


class TestFillGaps:
    def test_비어_있는_핵심_필드를_채운다(self, sparse_ocr):
        fake = FakeCompletion(json.dumps({
            "bl_no": "HMMU1234567",
            "consignee": "PACIFIC IMPORT GMBH",
            "port_of_loading": "BUSAN, KOREA",
        }))
        fields = FieldParser().parse(sparse_ocr)

        filled = LLMFieldExtractor(fake).fill_gaps(fields, sparse_ocr)

        assert "bl_no" in filled
        assert fields.bl_no == "HMMU1234567"
        assert fields.consignee == "PACIFIC IMPORT GMBH"

    def test_파서가_찾은_값은_덮지_않는다(self, full_ocr):
        # 파서가 이미 뽑은 값을 LLM 답으로 바꾸면, 설명 가능한 값을
        # 설명 불가능한 값으로 교환하게 된다.
        fake = FakeCompletion(json.dumps({"bl_no": "WRONG999999"}))
        fields = FieldParser().parse(full_ocr)
        original = fields.bl_no
        assert original  # 전제

        filled = LLMFieldExtractor(fake).fill_gaps(fields, full_ocr)

        assert filled == []
        assert fields.bl_no == original

    def test_채울_자리가_없으면_부르지_않는다(self, full_ocr):
        fake = FakeCompletion("{}")
        fields = BLFields(
            bl_no="X", consignee="Y", port_of_loading="Z",
            port_of_discharge="W", date_of_issue="2026-01-01",
        )

        LLMFieldExtractor(fake).fill_gaps(fields, full_ocr)

        assert fake.calls == []

    def test_출처를_llm_으로_남긴다(self, sparse_ocr):
        fake = FakeCompletion(json.dumps({"bl_no": "HMMU1234567"}))
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(fake).fill_gaps(fields, sparse_ocr)

        # 좌표로 찾은 값과 LLM 이 낸 값은 신뢰 수준이 다르다.
        assert fields.provenance["bl_no"] == "llm"

    def test_신뢰도가_확인_임계값_아래다(self, sparse_ocr):
        fake = FakeCompletion(json.dumps({"bl_no": "HMMU1234567"}))
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(fake).fill_gaps(fields, sparse_ocr)

        # S3 편집기가 반드시 사람 확인을 요구해야 한다.
        assert fields.confidence["bl_no"] == LLM_CONFIDENCE
        assert LLM_CONFIDENCE < LOW_CONFIDENCE_THRESHOLD

    def test_원문을_프롬프트에_넣는다(self, sparse_ocr):
        fake = FakeCompletion("{}")
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(fake).fill_gaps(fields, sparse_ocr)

        _system, user = fake.calls[0]
        assert "BILL OF LADING" in user
        assert "bl_no" in user


class TestBadResponses:
    @pytest.mark.parametrize("reply", [
        '{"bl_no": null}',
        '{"bl_no": "N/A"}',
        '{"bl_no": "없음"}',
        '{"bl_no": "  "}',
    ])
    def test_없음을_뜻하는_답은_값으로_넣지_않는다(self, sparse_ocr, reply):
        # 'N/A' 를 값으로 넣으면 '없음'이 '있음'이 되어 하자 검증이 통과한다.
        fields = FieldParser().parse(sparse_ocr)

        filled = LLMFieldExtractor(FakeCompletion(reply)).fill_gaps(fields, sparse_ocr)

        assert filled == []
        assert fields.bl_no is None

    def test_코드펜스를_벗겨낸다(self, sparse_ocr):
        reply = '```json\n{"bl_no": "HMMU1234567"}\n```'
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(FakeCompletion(reply)).fill_gaps(fields, sparse_ocr)

        assert fields.bl_no == "HMMU1234567"

    def test_설명_문장이_붙어도_객체를_찾는다(self, sparse_ocr):
        reply = '다음과 같습니다: {"bl_no": "HMMU1234567"} 확인하세요.'
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(FakeCompletion(reply)).fill_gaps(fields, sparse_ocr)

        assert fields.bl_no == "HMMU1234567"

    def test_JSON_이_아니면_파서_결과를_지킨다(self, sparse_ocr):
        fields = FieldParser().parse(sparse_ocr)

        filled = LLMFieldExtractor(FakeCompletion("죄송합니다")).fill_gaps(
            fields, sparse_ocr
        )

        assert filled == []

    def test_호출이_실패해도_추출은_계속된다(self, sparse_ocr):
        fake = FakeCompletion(error=RuntimeError("timeout"))
        fields = FieldParser().parse(sparse_ocr)

        # LLM 실패로 추출 전체가 죽으면 안 된다.
        filled = LLMFieldExtractor(fake).fill_gaps(fields, sparse_ocr)

        assert filled == []

    def test_모르는_필드는_무시한다(self, sparse_ocr):
        reply = json.dumps({"bl_no": "HMMU1234567", "captain_name": "AHAB"})
        fields = FieldParser().parse(sparse_ocr)

        LLMFieldExtractor(FakeCompletion(reply)).fill_gaps(fields, sparse_ocr)

        assert fields.bl_no == "HMMU1234567"
        assert not hasattr(fields, "captain_name")


class TestPipelineWiring:
    def test_기본은_꺼져_있다(self, monkeypatch):
        # 외부 API 호출이 기본으로 켜져 있으면 테스트·시연이 네트워크에 묶인다.
        monkeypatch.delenv("LLM_STRUCTURED_EXTRACT", raising=False)

        assert IntakePipeline().use_llm is False

    def test_환경변수로_켠다(self, monkeypatch):
        monkeypatch.setenv("LLM_STRUCTURED_EXTRACT", "true")

        assert IntakePipeline().use_llm is True

    def test_인자가_환경변수를_이긴다(self, monkeypatch):
        monkeypatch.setenv("LLM_STRUCTURED_EXTRACT", "true")

        assert IntakePipeline(use_llm=False).use_llm is False

    def test_초안이_값의_출처를_드러낸다(self, tmp_path):
        """출처가 응답에 없으면 화면이 LLM 값과 좌표 값을 구분할 수 없다."""
        path = write_label(tmp_path, complete_bl_bboxes(), identifier="OFF")
        fields = IntakePipeline(use_llm=False).run_from_json(path).to_dict()["fields"]

        by_name = {f["name"]: f for f in fields}
        # 값이 있는 필드는 출처가 있어야 한다.
        assert by_name["bl_no"]["source"] in {"region", "anchor"}
        # LLM 을 껐으므로 llm 출처는 없다.
        assert "llm" not in {f["source"] for f in fields}
        # 값이 없으면 출처도 없다.
        for f in fields:
            if f["value"] is None:
                assert f["source"] is None

    def test_LLM_이_채운_값은_초안에서_구분된다(self, sparse_ocr, monkeypatch):
        pipeline = IntakePipeline(use_llm=True)
        pipeline._llm = LLMFieldExtractor(
            FakeCompletion(json.dumps({"bl_no": "HMMU1234567"}))
        )

        draft = pipeline._run(sparse_ocr)
        by_name = {f["name"]: f for f in draft.to_dict()["fields"]}

        assert by_name["bl_no"]["value"] == "HMMU1234567"
        assert by_name["bl_no"]["source"] == "llm"
        # 임계값 아래이므로 사람 확인 대상이어야 한다.
        assert by_name["bl_no"]["needs_review"] is True


class Test서류별_LLM_보충:
    """선하증권 외 서류(상업송장·포장명세서)의 LLM 보충.

    이 경로가 LLM 을 가장 필요로 한다 — 좌표 교정본이 없어 파서가 앵커만
    쓰는데, 실물 말뭉치에서 값 채움률이 13% 였다(선하증권 91.5%).
    """

    def _pipeline(self, reply: str):
        fake = FakeCompletion(reply)
        pipeline = IntakePipeline(use_llm=True)
        pipeline._llm = LLMFieldExtractor(fake)
        return pipeline, fake

    def test_상업송장_빈칸을_LLM_이_채운다(self, tmp_path):
        # 항목명 없이 값만 있는 서식. 앵커가 걸 곳이 없다 — AI Hub 라벨
        # 데이터가 정확히 이 형태다(값만 라벨링되고 항목명은 없다).
        bboxes = lines_to_bboxes([
            (0.35, 0.06, "COMMERCIAL INVOICE"),
            (0.30, 0.14, "INV-2026-0417"),
            (0.30, 0.30, "DHHJ FRANCHISING CO., LTD."),
        ])
        path = write_label(tmp_path, bboxes, identifier="NV1", form_type="상업송장")

        pipeline, fake = self._pipeline(json.dumps({
            "invoice_no": "INV-2026-0417",
            "buyer": "DHHJ FRANCHISING CO., LTD.",
            "total_amount": "USD 41,250.00",
        }))
        by_name = {f["name"]: f for f in pipeline.run_from_json(path).to_dict()["fields"]}

        assert by_name["total_amount"]["value"] == "USD 41,250.00"
        assert by_name["total_amount"]["source"] == "llm"
        # 임계값 아래라 초안 편집기가 사람 확인을 요구해야 한다.
        assert by_name["total_amount"]["needs_review"] is True

    def test_프롬프트가_서류_종류를_알린다(self, tmp_path):
        # "선하증권에서 읽은 원문"이라고 물으면 모델이 송장 필드를 엉뚱하게 찾는다.
        path = write_label(
            tmp_path, lines_to_bboxes([(0.38, 0.06, "PACKING LIST")]),
            identifier="PL1", form_type="포장명세서",
        )
        pipeline, fake = self._pipeline("{}")
        pipeline.run_from_json(path)

        assert fake.calls, "LLM 이 호출되지 않았다"
        prompt = fake.calls[0][1]
        assert "포장명세서" in prompt
        assert "선하증권" not in prompt

    def test_한국어_라벨을_함께_넘긴다(self, tmp_path):
        # `package_count` 보다 `package_count(포장 수량)` 쪽이 무엇을 찾아야
        # 하는지 분명하다.
        path = write_label(
            tmp_path, lines_to_bboxes([(0.38, 0.06, "PACKING LIST")]),
            identifier="PL2", form_type="포장명세서",
        )
        pipeline, fake = self._pipeline("{}")
        pipeline.run_from_json(path)

        assert "package_count(포장 수량)" in fake.calls[0][1]

    def test_명세의_핵심_필드만_묻는다(self, tmp_path):
        # 전 필드를 매번 물으면 토큰이 늘고, 무엇이 핵심인지는 DocumentSpec 이
        # 정한다 — 여기서 다시 나열하면 명세와 어긋난다.
        from ocr.doc_types import spec_for

        path = write_label(
            tmp_path, lines_to_bboxes([(0.35, 0.06, "COMMERCIAL INVOICE")]),
            identifier="NV2", form_type="상업송장",
        )
        pipeline, fake = self._pipeline("{}")
        pipeline.run_from_json(path)

        prompt = fake.calls[0][1]
        spec = spec_for("상업송장")
        for name in spec.critical:
            assert name in prompt
        # 핵심이 아닌 필드는 묻지 않는다.
        assert "incoterms" not in prompt

    def test_LLM_이_실패해도_파서_결과는_남는다(self, tmp_path):
        path = write_label(
            tmp_path, lines_to_bboxes([
                (0.35, 0.06, "COMMERCIAL INVOICE"),
                (0.05, 0.14, "INVOICE NO"), (0.30, 0.14, "INV-2026-0417"),
            ]),
            identifier="NV3", form_type="상업송장",
        )
        pipeline = IntakePipeline(use_llm=True)
        pipeline._llm = LLMFieldExtractor(FakeCompletion(error=RuntimeError("타임아웃")))

        draft = pipeline.run_from_json(path)
        by_name = {f["name"]: f for f in draft.to_dict()["fields"]}

        assert by_name["invoice_no"]["value"] == "INV-2026-0417"
        assert by_name["invoice_no"]["source"] == "anchor"

    def test_파서가_찾은_값을_덮지_않는다(self, tmp_path):
        path = write_label(
            tmp_path, lines_to_bboxes([
                (0.35, 0.06, "COMMERCIAL INVOICE"),
                (0.05, 0.14, "INVOICE NO"), (0.30, 0.14, "INV-2026-0417"),
            ]),
            identifier="NV4", form_type="상업송장",
        )
        pipeline, _ = self._pipeline(json.dumps({"invoice_no": "지어낸-번호"}))
        by_name = {f["name"]: f for f in pipeline.run_from_json(path).to_dict()["fields"]}

        # 설명 가능한 값을 설명 불가능한 값으로 바꾸는 거래는 남는 장사가 아니다.
        assert by_name["invoice_no"]["value"] == "INV-2026-0417"
        assert by_name["invoice_no"]["source"] == "anchor"

    def test_LLM_을_끄면_부르지_않는다(self, tmp_path):
        path = write_label(
            tmp_path, lines_to_bboxes([(0.35, 0.06, "COMMERCIAL INVOICE")]),
            identifier="NV5", form_type="상업송장",
        )
        fake = FakeCompletion("{}")
        pipeline = IntakePipeline(use_llm=False)
        pipeline._llm = LLMFieldExtractor(fake)
        pipeline.run_from_json(path)

        assert fake.calls == []


class Test짧은_항목명_오매칭:
    """`TO` 가 `SANTOS` 안에서 걸리던 버그."""

    def test_짧은_후보는_낱말_경계로만_맞는다(self):
        from ocr.doc_parser import _label_matches

        # 매수인 후보 `TO` 가 선사명 `SANTOS` 에 걸리면, 선사명·날짜·항차가
        # 매수인 값으로 들어간다. 실제로 그렇게 잡혔다.
        assert _label_matches("TO", "SANTOS EXPRESS") is False
        assert _label_matches("TO", "TO ORDER") is True

    def test_긴_후보는_부분_일치도_인정한다(self):
        from ocr.doc_parser import _label_matches

        # `COMMERCIAL INVOICE NO.` 안의 `INVOICE NO` 는 그 항목명이 맞다.
        assert _label_matches("INVOICE NO", "COMMERCIAL INVOICE NO") is True

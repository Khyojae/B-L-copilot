"""OCRExtractor 테스트 — 라벨 JSON 로드와 PaddleOCR 3.x 결과 파싱."""

from __future__ import annotations

import json

import pytest
from conftest import complete_bl_bboxes, make_bbox, paddle_page

from ocr.extractor import OCRExtractor


class TestFromJson:
    def test_라벨을_읽어_bbox와_메타를_채운다(self, complete_label):
        result = OCRExtractor().from_json(complete_label)

        assert result.image_id == "TEST_BL_0001"
        assert result.image_width == 1654
        assert result.image_height == 2340
        assert result.source == "json"
        assert len(result.bboxes) == len(complete_bl_bboxes())

    def test_라벨_신뢰도는_1이다(self, complete_label):
        # 사람이 라벨링한 정답 데이터이므로 OCR 불확실성이 없다.
        result = OCRExtractor().from_json(complete_label)

        assert all(b.confidence == 1.0 for b in result.bboxes)
        assert result.mean_confidence == 1.0

    def test_빈_텍스트와_좌표부족_항목은_버린다(self, label_factory):
        path = label_factory(
            [
                make_bbox("정상", 0.2, 0.2),
                {"data": "   ", "x": [0, 10], "y": [0, 10]},   # 공백만
                {"data": "좌표부족", "x": [5], "y": [0, 10]},   # x 가 1개
                {"data": "y없음", "x": [0, 10], "y": []},
            ]
        )
        result = OCRExtractor().from_json(path)

        assert [b.text for b in result.bboxes] == ["정상"]

    def test_메타가_없으면_기본_해상도를_쓴다(self, tmp_path):
        # 구역 좌표가 1654x2340 기준이라 크기를 모를 때 이 값으로 가정해야
        # 비율 환산이 어긋나지 않는다.
        path = tmp_path / "meta_none.json"
        path.write_text(json.dumps({"bbox": []}), encoding="utf-8")

        result = OCRExtractor().from_json(str(path))

        assert (result.image_width, result.image_height) == (1654, 2340)
        assert result.image_id == "meta_none"

    def test_raw_text는_읽기_순서로_이어붙인다(self, label_factory):
        path = label_factory(
            [
                make_bbox("아래줄", 0.2, 0.60),
                make_bbox("윗줄", 0.2, 0.10),
                make_bbox("가운데", 0.2, 0.35),
            ]
        )
        result = OCRExtractor().from_json(path)

        assert result.raw_text.splitlines() == ["윗줄", "가운데", "아래줄"]


class TestPaddleResultParsing:
    def test_rec_scores를_신뢰도로_보존한다(self):
        # 원본 ai_sample 은 이 값을 버렸다. 버리면 어떤 필드를 사람이
        # 확인해야 하는지 판단할 근거가 사라진다.
        page = paddle_page(["BUSAN", "KOREA"], scores=[0.98, 0.42])

        bboxes = OCRExtractor._parse_paddle_result([page])

        assert [b.text for b in bboxes] == ["BUSAN", "KOREA"]
        assert bboxes[0].confidence == pytest.approx(0.98)
        assert bboxes[1].confidence == pytest.approx(0.42)

    def test_rec_scores가_없으면_1로_둔다(self):
        # 0.0 으로 떨어뜨리면 전 필드가 저신뢰로 잡혀 확인 큐가 무의미해진다.
        bboxes = OCRExtractor._parse_paddle_result([paddle_page(["A", "B"])])

        assert [b.confidence for b in bboxes] == [1.0, 1.0]

    def test_rec_scores가_짧으면_나머지는_1로_둔다(self):
        page = paddle_page(["A", "B", "C"], scores=[0.5])

        bboxes = OCRExtractor._parse_paddle_result([page])

        assert [b.confidence for b in bboxes] == [0.5, 1.0, 1.0]

    def test_빈_텍스트는_건너뛴다(self):
        page = paddle_page(["실제", "  ", "값"], scores=[0.9, 0.9, 0.9])

        bboxes = OCRExtractor._parse_paddle_result([page])

        assert [b.text for b in bboxes] == ["실제", "값"]

    def test_polygon에서_경계상자를_만든다(self):
        page = paddle_page(
            ["기울어짐"],
            scores=[0.9],
            # 회전된 사각형 — min/max 로 축정렬 상자를 잡아야 한다
            polys=[[[110, 100], [300, 120], [295, 160], [105, 140]]],
        )

        bbox = OCRExtractor._parse_paddle_result([page])[0]

        assert (bbox.x_min, bbox.x_max) == (105, 300)
        assert (bbox.y_min, bbox.y_max) == (100, 160)
        assert bbox.center_x == pytest.approx(202.5)

    def test_결과가_비어도_죽지_않는다(self):
        assert OCRExtractor._parse_paddle_result(None) == []
        assert OCRExtractor._parse_paddle_result([]) == []
        assert OCRExtractor._parse_paddle_result([paddle_page([])]) == []


class TestLoadDataset:
    def test_디렉토리의_라벨을_모두_읽는다(self, tmp_path, label_factory):
        label_factory(complete_bl_bboxes(), identifier="BL_001")
        label_factory(complete_bl_bboxes(), identifier="BL_002")

        results = OCRExtractor().load_dataset(str(tmp_path))

        assert sorted(r.image_id for r in results) == ["BL_001", "BL_002"]

    def test_깨진_파일은_건너뛰고_계속한다(self, tmp_path, label_factory, capsys):
        label_factory(complete_bl_bboxes(), identifier="BL_001")
        (tmp_path / "broken.json").write_text("{ 이건 JSON 이 아님", encoding="utf-8")

        results = OCRExtractor().load_dataset(str(tmp_path))

        assert [r.image_id for r in results] == ["BL_001"]
        assert "broken.json" in capsys.readouterr().out


class TestPaddleOCRAbsent:
    def test_미설치시_안내_메시지를_준다(self, monkeypatch):
        # OCR 없이 from_json 으로 테스트할 수 있다는 안내가 핵심이다.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "paddleocr":
                raise ImportError("no paddleocr")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="from_json"):
            OCRExtractor()._get_ocr()

"""
F1 인테이크 파이프라인.

입력 → OCR → 필드 추출 → 초안. 저장은 하지 않는다.

저장을 여기 넣지 않는 이유는 DB 스키마가 아직 확정되지 않아서가 아니라,
넣으면 안 되기 때문이다. 추출 로직이 저장소를 알게 되면 테스트에 DB 가
필요해지고, 스키마가 바뀔 때마다 추출 로직까지 흔들린다. 저장은 호출부
(FastAPI 레이어)가 결과를 받아서 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .draft import BLDraft, build_draft
from .extractor import OCRExtractor
from .field_parser import FieldParser
from .types import LOW_CONFIDENCE_THRESHOLD, BLFields, OCRResult


class IntakePipeline:
    """서류 1건을 초안까지 처리한다."""

    def __init__(
        self,
        lang: str = "en",
        use_gpu: bool = False,
        confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.extractor = OCRExtractor(lang=lang, use_gpu=use_gpu)
        self.parser = FieldParser()
        self.confidence_threshold = confidence_threshold

    # ── 실행 ──────────────────────────────────────────────────────

    def run_from_json(self, json_path: str) -> BLDraft:
        """라벨 JSON 으로 실행. OCR 엔진 없이 동작한다."""
        return self._run(self.extractor.from_json(json_path))

    def run_from_image(self, image_path: str, preprocess: bool = True) -> BLDraft:
        """이미지로 실행."""
        path = self._preprocess(image_path) if preprocess else image_path
        return self._run(self.extractor.from_image(path))

    def run_from_pdf(self, pdf_path: str, page_number: int = 0) -> BLDraft:
        """PDF 로 실행.

        텍스트 레이어가 있으면 OCR 을 타지 않으므로 **PaddleOCR 없이도
        동작한다.** 스캔본일 때만 OCR 이 필요하다.
        """
        return self._run(self.extractor.from_pdf(pdf_path, page_number))

    def run_batch(self, label_dir: str, max_files: int = 0) -> List[BLDraft]:
        """라벨 디렉토리 일괄 처리. 실패 건은 건너뛰고 계속한다."""
        files = sorted(Path(label_dir).glob("*.json"))
        if max_files > 0:
            files = files[:max_files]

        drafts: List[BLDraft] = []
        for json_file in files:
            try:
                drafts.append(self.run_from_json(str(json_file)))
            except Exception as exc:  # noqa: BLE001 - 배치는 한 건 실패로 멈추지 않는다
                print(f"[경고] {json_file.name} 처리 실패: {exc}")
        return drafts

    # ── 내부 ─────────────────────────────────────────────────────

    def _run(self, ocr: OCRResult) -> BLDraft:
        fields: BLFields = self.parser.parse(ocr)
        return build_draft(fields, ocr, threshold=self.confidence_threshold)

    @staticmethod
    def _preprocess(image_path: str) -> str:
        """전처리 후 경로 반환. OpenCV 가 없으면 원본을 그대로 쓴다.

        preprocessor 모듈은 cv2 를 함수 안에서 import 하므로 모듈 import 자체는
        성공하고, ImportError 는 생성자에서 난다. 따라서 import 문만 감싸면
        '없으면 생략'이 실제로는 동작하지 않는다 — 생성까지 함께 감싼다.

        전처리는 정확도를 높이는 보정이지 필수 단계가 아니다. OpenCV 가 없다고
        추출 자체가 실패하면, 무거운 선택 의존성이 사실상 필수가 된다.
        """
        try:
            from .preprocessor import ImagePreprocessor

            pp = ImagePreprocessor()
        except ImportError:
            print("[경고] OpenCV 미설치 → 전처리 생략")
            return image_path

        source = Path(image_path)
        out_path = source.with_name(f"{source.stem}_preprocessed{source.suffix}")
        pp.save(pp.process(image_path), str(out_path))
        return str(out_path)


def extract_fields(json_path: str) -> BLFields:
    """라벨 JSON 에서 필드만 뽑는다. 하자 검증(F3) 입력용."""
    extractor = OCRExtractor()
    return FieldParser().parse(extractor.from_json(json_path))


__all__ = ["IntakePipeline", "extract_fields"]

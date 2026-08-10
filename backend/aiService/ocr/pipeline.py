"""
F1 인테이크 파이프라인.

입력 → OCR → 필드 추출 → 초안. 저장은 하지 않는다.

저장을 여기 넣지 않는 이유는 DB 스키마가 아직 확정되지 않아서가 아니라,
넣으면 안 되기 때문이다. 추출 로직이 저장소를 알게 되면 테스트에 DB 가
필요해지고, 스키마가 바뀔 때마다 추출 로직까지 흔들린다. 저장은 호출부
(FastAPI 레이어)가 결과를 받아서 한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from . import doc_types
from .doc_parser import DocumentParser
from .draft import BLDraft, build_document_draft, build_draft
from .extractor import OCRExtractor
from .field_parser import FieldParser
from .llm_extract import LLMFieldExtractor
from .types import LOW_CONFIDENCE_THRESHOLD, BLFields, OCRResult


def _env_flag(name: str) -> bool:
    """환경변수를 불리언으로. 미설정은 거짓이다."""
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


class IntakePipeline:
    """서류 1건을 초안까지 처리한다."""

    def __init__(
        self,
        lang: str = "en",
        use_gpu: bool = False,
        confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        use_llm: Optional[bool] = None,
    ) -> None:
        """use_llm 은 파서가 비운 핵심 필드를 LLM 으로 채울지 여부다.

        기본값은 환경변수 `LLM_STRUCTURED_EXTRACT` 이고, 그마저 없으면 꺼짐이다.
        **기본을 켬으로 두지 않는 이유**는 이 경로가 외부 API 호출이기 때문이다.
        켜져 있으면 테스트와 시연이 네트워크·요금·지연에 묶이고, 그 사실이
        코드 어디에도 드러나지 않는다. 켜는 것은 명시적 결정이어야 한다.
        """
        self.extractor = OCRExtractor(lang=lang, use_gpu=use_gpu)
        self.parser = FieldParser()
        self.doc_parser = DocumentParser()
        self.confidence_threshold = confidence_threshold
        self.use_llm = _env_flag("LLM_STRUCTURED_EXTRACT") if use_llm is None else use_llm
        self._llm: Optional[LLMFieldExtractor] = None

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

    def run_from_excel(self, path: str, sheet: str | None = None) -> BLDraft:
        """엑셀로 실행. OCR 을 타지 않으므로 PaddleOCR 없이 동작한다."""
        return self._run(self.extractor.from_excel(path, sheet=sheet))

    def run_from_email(self, path: str) -> BLDraft:
        """이메일(.eml)로 실행.

        첨부가 서류이면 그 형식의 경로를 탄다. 따라서 스캔 이미지가 첨부된
        경우에만 PaddleOCR 이 필요하다.
        """
        return self._run(self.extractor.from_email(path))

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
        spec = doc_types.spec_for(self._form_type(ocr))
        if spec is not None:
            # 선하증권 외 서류. 좌표 교정본이 없어 앵커만 쓴다 — 근거는
            # doc_types 도입부에 적었다. LLM 보충은 선하증권 필드 이름을
            # 전제하므로 여기서는 태우지 않는다.
            return build_document_draft(
                self.doc_parser.parse(ocr, spec), ocr,
                threshold=self.confidence_threshold,
            )

        fields: BLFields = self.parser.parse(ocr)
        if self.use_llm:
            # 파서가 비운 자리만 채운다. 채운 필드는 provenance 가 "llm" 이고
            # 신뢰도가 임계값 아래라 초안 편집기가 사람 확인을 요구한다.
            if self._llm is None:
                self._llm = LLMFieldExtractor()
            self._llm.fill_gaps(fields, ocr)
        return build_draft(fields, ocr, threshold=self.confidence_threshold)

    @staticmethod
    def _form_type(ocr: OCRResult) -> str:
        """서류 종류를 정한다. **본문 판별을 메타데이터보다 우선한다.**

        추출기들이 `form_type` 을 "선하증권"으로 하드코딩해 넣기 때문이다.
        그 값을 믿으면 송장을 올려도 선하증권으로 처리되고, B/L 구역 좌표로
        파싱된 그럴듯한 오값이 나온다. 오류가 아니라 값이라 조용하다.

        판별에 실패하면(`미상`) 메타데이터로 돌아간다 — 라벨 JSON 의
        `Images.form_type` 은 사람이 적어 둔 값이라 믿을 만하다.
        """
        detected = doc_types.detect(ocr.raw_text)
        return ocr.form_type if detected == doc_types.UNKNOWN else detected

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

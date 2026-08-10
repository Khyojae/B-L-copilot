"""
OCR 텍스트 추출 (PaddleOCR 3.6.0).

두 가지 입력 경로를 둔다.

- `from_image` : 실제 운영 경로. PaddleOCR 로 이미지에서 추출한다.
- `from_json`  : 라벨 JSON 로드. PaddleOCR·PaddlePaddle 설치 없이 파서와
                 하자 검증을 테스트할 수 있어 CI 에서 쓴다. 라벨은 정답
                 데이터이므로 신뢰도는 1.0 으로 둔다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Optional

from .types import BBox, OCRResult

# 지원 대상 PaddleOCR. 3.x 는 2.x 와 반환 구조가 다르다(rec_texts/dt_polys vs 튜플).
PADDLEOCR_MIN_VERSION = "3.6.0"

# oneDNN(MKLDNN) 가속을 끈다. paddlepaddle 3.3.1 Windows CPU 에서 텍스트 검출
# 추론이 다음으로 죽는다:
#
#   NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute
#   not support [pir::ArrayAttribute<pir::DoubleAttribute>]
#   (at onednn_instruction.cc:118)
#
# PIR 실행기가 oneDNN 커널의 double 배열 속성을 변환하지 못하는 문제로,
# 모델·입력과 무관하게 항상 재현된다. 끄면 통과한다. 켜서 얻는 것은 CPU
# 추론 속도뿐이고 못 켜면 기능 자체가 죽으므로 기본값을 꺼짐으로 둔다.
# 상위 버전에서 고쳐지면 이 상수만 되돌리면 된다.
_ENABLE_MKLDNN = False

# 라벨 JSON 의 기본 이미지 크기. 학습 데이터셋의 표준 해상도이며
# field_parser 의 구역 좌표가 이 비율을 기준으로 교정되어 있다.
_DEFAULT_IMAGE_WIDTH = 1654
_DEFAULT_IMAGE_HEIGHT = 2340


class OCRExtractor:
    """이미지 또는 라벨 JSON에서 OCR 결과를 만든다."""

    def __init__(self, lang: str = "en", use_gpu: bool = False) -> None:
        self._ocr: Any = None  # PaddleOCR lazy 초기화
        self._lang = lang
        self._use_gpu = use_gpu

    # ── 공개 메서드 ──────────────────────────────────────────────

    def from_json(self, json_path: str) -> OCRResult:
        """라벨 JSON 에서 OCR 결과 로드."""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        images_meta = data.get("Images", {})
        return OCRResult(
            image_id=images_meta.get("identifier", Path(json_path).stem),
            image_width=images_meta.get("width", _DEFAULT_IMAGE_WIDTH),
            image_height=images_meta.get("height", _DEFAULT_IMAGE_HEIGHT),
            form_type=images_meta.get("form_type", "선하증권"),
            bboxes=self._parse_label_bboxes(data.get("bbox", [])),
            source="json",
        )

    def from_image(self, image_path: str) -> OCRResult:
        """PaddleOCR 로 이미지에서 직접 추출."""
        started = time.perf_counter()
        raw = self._get_ocr().predict(str(image_path))
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        bboxes = self._parse_paddle_result(raw)
        width, height = self._image_size(image_path)

        return OCRResult(
            image_id=Path(image_path).stem,
            image_width=width,
            image_height=height,
            form_type="선하증권",
            bboxes=bboxes,
            source="paddleocr",
            processing_time_ms=elapsed_ms,
            model_version=self._paddleocr_version(),
        )

    def load_dataset(self, label_dir: str) -> List[OCRResult]:
        """라벨 디렉토리의 JSON 을 일괄 로드. 실패 건은 건너뛴다."""
        results: List[OCRResult] = []
        for json_file in sorted(Path(label_dir).glob("*.json")):
            try:
                results.append(self.from_json(str(json_file)))
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                print(f"[경고] {json_file.name} 로드 실패: {exc}")
        return results

    # ── 내부 ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_label_bboxes(raw: list) -> List[BBox]:
        """라벨 JSON 의 bbox 배열 → BBox 목록."""
        bboxes: List[BBox] = []
        for item in raw:
            text = (item.get("data") or "").strip()
            xs = item.get("x", [])
            ys = item.get("y", [])
            if not text or len(xs) < 2 or len(ys) < 2:
                continue
            bboxes.append(
                BBox(
                    text=text,
                    x_min=min(xs),
                    y_min=min(ys),
                    x_max=max(xs),
                    y_max=max(ys),
                    confidence=1.0,  # 사람이 라벨링한 정답
                )
            )
        return bboxes

    @staticmethod
    def _parse_paddle_result(raw: Any) -> List[BBox]:
        """PaddleOCR 3.x 결과 → BBox 목록.

        3.x 는 dict-like 결과에 rec_texts / dt_polys / rec_scores 를 담아 준다.
        rec_scores 가 필드별 신뢰도의 원천이다 — 이걸 버리면 어떤 필드를
        사람이 확인해야 하는지 판단할 근거가 사라진다.
        """
        bboxes: List[BBox] = []
        if not raw:
            return bboxes

        for page in raw:
            if not hasattr(page, "get"):
                continue
            texts = page.get("rec_texts", []) or []
            polys = page.get("dt_polys", []) or []
            scores = page.get("rec_scores", []) or []

            for idx, (text, poly) in enumerate(zip(texts, polys)):
                if not text or not text.strip():
                    continue
                points = list(poly)
                xs = [int(p[0]) for p in points]
                ys = [int(p[1]) for p in points]
                # rec_scores 가 짧거나 없을 때 0.0 으로 떨어뜨리면 전 필드가
                # 저신뢰로 잡혀 사람 확인 큐가 무의미해진다. 1.0 으로 둔다.
                score = float(scores[idx]) if idx < len(scores) else 1.0
                bboxes.append(
                    BBox(
                        text=text.strip(),
                        x_min=min(xs),
                        y_min=min(ys),
                        x_max=max(xs),
                        y_max=max(ys),
                        confidence=score,
                    )
                )
        return bboxes

    @staticmethod
    def _image_size(image_path: str) -> tuple[int, int]:
        """이미지 크기. 실패 시 라벨 데이터셋 표준 해상도로 대체한다."""
        try:
            import cv2

            img = cv2.imread(str(image_path))
            if img is not None:
                h, w = img.shape[:2]
                return int(w), int(h)
        except ImportError:
            pass
        return _DEFAULT_IMAGE_WIDTH, _DEFAULT_IMAGE_HEIGHT

    @staticmethod
    def _paddleocr_version() -> Optional[str]:
        try:
            import paddleocr

            return getattr(paddleocr, "__version__", None)
        except ImportError:
            return None

    def _get_ocr(self) -> Any:
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise ImportError(
                    "PaddleOCR 가 설치되어 있지 않습니다.\n"
                    f"설치: pip install 'paddleocr>={PADDLEOCR_MIN_VERSION}' paddlepaddle\n"
                    "OCR 없이 파서만 테스트하려면 from_json() 을 쓰세요."
                ) from exc

            # B/L 은 정형 스캔 서식이라 방향 분류·왜곡 보정이 대체로 불필요하고,
            # 켜면 처리 시간만 늘어난다. 기울어진 스캔은 preprocessor 에서 잡는다.
            self._ocr = PaddleOCR(
                lang=self._lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                enable_mkldnn=_ENABLE_MKLDNN,
            )
        return self._ocr

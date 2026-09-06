"""
OCR 텍스트 추출 (PaddleOCR 3.6.0).

세 가지 입력 경로를 둔다.

- `from_image` : 실제 운영 경로. PaddleOCR 로 이미지에서 추출한다.
- `from_json`  : 라벨 JSON 로드. PaddleOCR·PaddlePaddle 설치 없이 파서와
                 하자 검증을 테스트할 수 있어 CI 에서 쓴다. 라벨은 정답
                 데이터이므로 신뢰도는 1.0 으로 둔다.
- `from_pdf`   : PDF. **텍스트 레이어가 있으면 OCR 을 아예 타지 않는다.**

## PDF 를 OCR 로 보내지 않는 이유

전자 발행 B/L·인보이스는 대부분 텍스트 레이어를 갖는다. 그걸 굳이 이미지로
굽고 OCR 에 넣으면 정확한 글자를 흐린 픽셀로 바꿔 다시 추측하는 셈이다.
정확도가 떨어지고 장당 수십 초가 든다.

텍스트 레이어에서 좌표를 직접 읽으면 신뢰도가 1.0 이고 즉시 끝난다.
스캔본(텍스트 레이어 없음)만 이미지로 구워 OCR 에 넘긴다.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
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

# 검출·인식 모델. PaddleOCR 기본값은 `PP-OCRv6_medium` 인데, oneDNN 을 끈
# 상태의 CPU 추론이 이미지 1장당 88초라 요청 단위로 쓸 수 없다.
#
#   구성                     추론    핵심값   평균신뢰도
#   v6_medium (기본)        88.0s    8/8      0.995
#   v6_small                14.0s    8/8      0.995
#   v6_tiny                  6.0s    8/8      0.982
#   v5_mobile               13.1s    8/8      0.983
#   v6_small + textline off 10.6s    8/8      0.995   ← 채택
#
# small 은 medium 과 평균 신뢰도가 같으면서 8배 빠르다. tiny 가 더 빠르지만
# 신뢰도가 떨어져 실물 스캔에서 먼저 무너질 쪽이다.
#
# 주의: 위 수치는 **합성 B/L 1장**(깨끗하게 렌더링된 텍스트) 기준이다. 모든
# 구성이 8/8 을 맞춘 것은 입력이 쉬웠다는 뜻이지 small 이 실물 스캔에서
# medium 만큼 읽는다는 뜻이 아니다. 실물 샘플이 생기면 이 상수부터 재검증할 것.
_TEXT_DET_MODEL = "PP-OCRv6_small_det"
_TEXT_REC_MODEL = "PP-OCRv6_small_rec"

# 글줄 방향 분류. 켜면 뒤집힌 텍스트 줄을 잡아주지만 small 기준 14.0s → 10.6s
# 로 비용이 크다. 아래 PaddleOCR 생성자 주석과 같은 이유로 끈다 — B/L 은
# 정형 서식이고, 기울어진 스캔은 preprocessor 가 잡는다.
_USE_TEXTLINE_ORIENTATION = False

# 라벨 JSON 의 기본 이미지 크기. 학습 데이터셋의 표준 해상도이며
# field_parser 의 구역 좌표가 이 비율을 기준으로 교정되어 있다.
_DEFAULT_IMAGE_WIDTH = 1654
_DEFAULT_IMAGE_HEIGHT = 2340

# 텍스트 레이어를 신뢰할 최소 줄 수.
#
# 스캔 PDF 에도 텍스트가 조금은 있을 수 있다 — 워터마크, 발행 도장, 페이지
# 번호 같은 것들이다. 그걸 보고 "텍스트 레이어가 있다"고 판단하면 본문이
# 통째로 빠진 결과를 자신 있게 내놓게 된다. B/L 은 필드가 十수 개이므로
# 이 선을 넘지 못하면 스캔본으로 보고 OCR 로 보낸다.
_PDF_TEXT_MIN_LINES = 10

# 스캔 PDF 를 구울 해상도. 200dpi 는 A4 기준 약 1654×2340 으로,
# 라벨 데이터셋 해상도와 맞아떨어진다(위 상수). 우연이 아니라 그 데이터셋이
# 200dpi 스캔이기 때문이며, 구역 좌표 교정 기준과 같은 배율을 유지한다.
_PDF_RASTER_DPI = 200

# OCR 에 넣는 이미지의 최대 너비. 구역 좌표가 교정된 해상도와 같은 값이다
# (`preprocessor.STANDARD_WIDTH`). 근거는 `_downscale_for_ocr` 에 적었다.
#
# `OCR_MAX_WIDTH=0` 으로 끌 수 있다. 축소가 실물 스캔의 작은 글씨를 뭉개는지
# 아직 검증되지 않았으므로, 원천 이미지로 확인하기 전까지 끄는 문을 남긴다.
DEFAULT_OCR_MAX_WIDTH = 1654


def _max_ocr_width() -> int:
    raw = (os.getenv("OCR_MAX_WIDTH") or "").strip()
    if not raw:
        return DEFAULT_OCR_MAX_WIDTH
    try:
        return max(0, int(raw))
    except ValueError:
        print(f"[경고] OCR_MAX_WIDTH 값을 읽을 수 없습니다: {raw!r} — 기본값 사용")
        return DEFAULT_OCR_MAX_WIDTH


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
        """PaddleOCR 로 이미지에서 직접 추출.

        큰 이미지는 먼저 줄인다(`_downscale_for_ocr`). 상한을 여기 두는 이유는
        **이 경로가 모든 OCR 의 목구멍이기 때문이다** — 스캔 PDF(`_from_pdf_scan`)
        와 이메일 첨부도 결국 여기로 들어온다. 전처리기(`preprocessor`)에 두면
        `run_from_image(preprocess=True)` 만 혜택을 보고 나머지는 그대로 느리다.
        """
        started = time.perf_counter()
        with self._downscale_for_ocr(image_path) as (target, width, height):
            raw = self._get_ocr().predict(str(target))
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        bboxes = self._parse_paddle_result(raw)

        return OCRResult(
            image_id=Path(image_path).stem,
            # **실제로 OCR 에 넣은 크기를 남긴다.** 원본 크기를 남기면 좌표는
            # 축소본 기준인데 분모만 원본이 되어 구역 비율이 통째로 어긋난다.
            image_width=width,
            image_height=height,
            form_type="선하증권",
            bboxes=bboxes,
            source="paddleocr",
            processing_time_ms=elapsed_ms,
            model_version=self._paddleocr_version(),
        )

    @contextmanager
    def _downscale_for_ocr(self, image_path: str):
        """OCR 비용 상한. (넣을 경로, 너비, 높이) 를 내주는 컨텍스트 매니저.

        축소본을 만들 때만 임시 디렉터리를 열고, with 블록이 끝나면 지운다
        — 예전에는 `mkdtemp()`로 만들고 아무도 지우지 않아 업로드마다
        `/tmp`에 파일이 쌓였다(P2-1). 원본을 그대로 쓰는 경우(축소 불필요·
        Pillow 미설치)는 임시 파일 자체가 없으니 그냥 원본 경로를 낸다.

        추론 시간이 **화소 수에 비례한다.** 같은 서식을 해상도만 바꿔 재면
        이렇게 나온다(합성 B/L 1장, 4코어).

            827x1170    7.6~8.1초     박스 14  신뢰도 0.991
            1240x1755   11~13초       박스 14  신뢰도 0.994
            1653x2339   19~23초       박스 14  신뢰도 0.994
            2480x3509   36~53초       박스 14  신뢰도 0.998

        폰으로 찍은 사진은 이보다 크다. 상한이 없으면 업로드 후 1분을 기다리게
        되고, 그 시연은 성립하지 않는다.

        **상한을 `STANDARD_WIDTH` 로 잡는 이유**는 구역 좌표가 교정된 해상도가
        그것이기 때문이다. 전처리기가 작은 이미지를 이 너비로 **키우고** 있었는데
        (`preprocessor._normalize_resolution`), 큰 이미지를 줄이지는 않아 한쪽만
        정규화되고 있었다. 양방향으로 맞추는 편이 규칙으로도 단순하다.

        **정확도 영향은 아직 검증되지 않았다.** 위 표는 합성 이미지 한 장이고,
        거기서는 네 해상도가 전부 박스 14개로 같았다 — 즉 **속도만 구분했고
        정확도는 구분하지 못했다.** 실물 스캔의 작은 글씨가 축소에서 뭉개지는지는
        원천 이미지를 받아야 안다. 그때까지는 `OCR_MAX_WIDTH=0` 으로 끌 수 있게
        열어 둔다(문서 2.1 절의 "압축되지 않는 세 가지" 1번과 같은 성격의 미검증
        항목이다).
        """
        width, height = self._image_size(image_path)
        limit = _max_ocr_width()
        if not limit or width <= limit:
            yield image_path, width, height
            return

        try:
            from PIL import Image
        except ImportError:
            # Pillow 가 없으면 줄이지 않는다. 느릴 뿐 결과는 옳다.
            yield image_path, width, height
            return

        scale = limit / width
        new_size = (limit, max(1, int(round(height * scale))))
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / f"{Path(image_path).stem}_ocr.png"
            with Image.open(image_path) as img:
                img.convert("RGB").resize(new_size, Image.LANCZOS).save(target)

            print(
                f"[ai-service] OCR 입력 축소: {width}x{height} → "
                f"{new_size[0]}x{new_size[1]} (상한 {limit}px)"
            )
            yield str(target), new_size[0], new_size[1]

    def from_pdf(self, pdf_path: str, page_number: int = 0) -> OCRResult:
        """PDF 한 쪽에서 추출한다.

        텍스트 레이어가 충분하면 그대로 쓰고(`source="pdf-text"`), 스캔본이면
        이미지로 구워 OCR 에 넘긴다(`source="pdf-ocr"`). 어느 쪽을 탔는지는
        `source` 에 남는다 — 신뢰도 1.0 이 '정답'인지 'OCR 이 확신한 값'인지는
        전혀 다른 이야기이므로 호출부가 구분할 수 있어야 한다.
        """
        fitz = _import_fitz()

        with fitz.open(str(pdf_path)) as document:
            if document.page_count == 0:
                raise ValueError(f"페이지가 없는 PDF 입니다: {pdf_path}")
            if not 0 <= page_number < document.page_count:
                raise ValueError(
                    f"페이지 번호가 범위를 벗어났습니다: {page_number} "
                    f"(전체 {document.page_count}쪽)"
                )

            page = document[page_number]
            # page.rect 는 회전이 반영된 표시 좌표계다. mediabox 를 쓰면
            # 90도 회전된 스캔에서 가로·세로가 뒤바뀌어 구역 비율이 어긋난다.
            width, height = int(page.rect.width), int(page.rect.height)
            bboxes = self._pdf_text_bboxes(page)

            if len(bboxes) >= _PDF_TEXT_MIN_LINES:
                return OCRResult(
                    image_id=Path(pdf_path).stem,
                    image_width=width,
                    image_height=height,
                    form_type="선하증권",
                    bboxes=bboxes,
                    source="pdf-text",
                )

            image_bytes = page.get_pixmap(dpi=_PDF_RASTER_DPI).tobytes("png")

        # 스캔본. OCR 이 필요하고, 그만큼 느리다.
        return self._from_pdf_scan(image_bytes, Path(pdf_path).stem)

    def from_excel(self, path: str, sheet: Optional[str] = None) -> OCRResult:
        """엑셀 한 시트에서 추출한다. OCR 을 타지 않는다."""
        from .spreadsheet import from_excel

        return from_excel(path, sheet=sheet)

    def from_email(self, path: str) -> OCRResult:
        """이메일에서 추출한다.

        **첨부를 먼저 본다.** 무역 실무에서 이메일 본문은 대개 안내문이고
        첨부가 서류이므로, 본문부터 읽으면 선하증권 대신 인사말을 파싱한다.
        지원 첨부가 없을 때만 본문을 읽는다.

        어느 경로였는지는 `source` 에 남는다 — `email-pdf` / `email-excel` /
        `email-image` / `email-body`. 본문에서 뽑은 값과 첨부 원본에서 뽑은
        값은 신뢰 수준이 다르므로 호출부가 구분할 수 있어야 한다.
        """
        import tempfile

        from .mail import body_to_result, parse_email

        content = parse_email(path)
        image_id = Path(path).stem
        chosen = content.best_attachment()

        if chosen is None:
            return body_to_result(content, image_id)

        with tempfile.TemporaryDirectory() as tmp:
            attached = Path(tmp) / f"attachment{chosen.suffix}"
            attached.write_bytes(chosen.payload)

            if chosen.kind == "pdf":
                result = self.from_pdf(str(attached))
            elif chosen.kind == "excel":
                result = self.from_excel(str(attached))
            else:
                result = self.from_image(str(attached))

        # 첨부를 거쳤다는 사실이 source 에 남아야 한다. 안 남기면 이메일로
        # 받은 스캔본과 직접 올린 스캔본이 구분되지 않는다.
        result.source = f"email-{chosen.kind}"
        result.image_id = image_id
        return result

    def _from_pdf_scan(self, image_bytes: bytes, image_id: str) -> OCRResult:
        """텍스트 레이어가 없는 PDF 를 구워 OCR 에 넘긴다."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{image_id}.png"
            path.write_bytes(image_bytes)
            result = self.from_image(str(path))

        # from_image 가 붙인 source 를 덮어 어느 경로였는지 남긴다.
        result.source = "pdf-ocr"
        result.image_id = image_id
        return result

    @staticmethod
    def _pdf_text_bboxes(page: Any) -> List[BBox]:
        """PDF 텍스트 레이어 → BBox 목록.

        줄(line) 단위로 묶는다. 단어 단위로 쪼개면 라벨 JSON 보다 잘게 나뉘어
        구역 안에서 값이 조각나고, 블록 단위로 묶으면 여러 필드가 한 상자에
        섞인다. 라벨 데이터셋의 입자와 같은 줄 단위가 맞다.
        """
        bboxes: List[BBox] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:      # 0 = 텍스트, 1 = 이미지
                continue
            for line in block.get("lines", []):
                text = "".join(
                    span.get("text", "") for span in line.get("spans", [])
                ).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = line["bbox"]
                bboxes.append(
                    BBox(
                        text=text,
                        x_min=int(x0),
                        y_min=int(y0),
                        x_max=int(x1),
                        y_max=int(y1),
                        # 텍스트 레이어는 추측이 아니라 원문이다.
                        confidence=1.0,
                    )
                )
        return bboxes

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

    @staticmethod
    def _pdf_page_count(pdf_path: str) -> int:
        fitz = _import_fitz()
        with fitz.open(str(pdf_path)) as document:
            return document.page_count

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
                use_textline_orientation=_USE_TEXTLINE_ORIENTATION,
                text_detection_model_name=_TEXT_DET_MODEL,
                text_recognition_model_name=_TEXT_REC_MODEL,
                enable_mkldnn=_ENABLE_MKLDNN,
            )
        return self._ocr


def _import_fitz() -> Any:
    """PyMuPDF. PDF 경로에서만 필요하므로 지연 import 한다.

    `pymupdf` 를 먼저 본다. 구 이름 `fitz` 는 import 할 때마다 폐기 경고를
    찍는데, 그게 매 요청 로그에 섞이면 진짜 경고가 묻힌다.
    """
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        pass
    try:
        import fitz

        return fitz
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF 가 설치되어 있지 않습니다.\n"
            "설치: pip install 'PyMuPDF>=1.24.0'\n"
            "PDF 입력에만 필요하며, 이미지·라벨 JSON 경로는 없어도 동작합니다."
        ) from exc

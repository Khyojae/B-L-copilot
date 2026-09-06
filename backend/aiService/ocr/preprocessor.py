"""
스캔 이미지 전처리 (OpenCV).

저품질 스캔에서 OCR 정확도가 떨어지는 문제를 완화한다. 기획안 9절이
'OCR 정확도 한계'를 리스크로 잡고 있고, 그 대응이 신뢰도 기반 휴먼 확인
라우팅인데 — 입력 품질을 먼저 올려두면 사람이 확인할 필드 수 자체가 준다.

그레이스케일 → 노이즈 제거 → 이진화 → 기울기 보정 → 해상도 정규화 순서다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# field_parser 의 구역 좌표가 이 너비를 기준으로 교정되어 있다.
STANDARD_WIDTH = 1654

# 이 각도 미만이면 보정하지 않는다. 미세한 회전까지 잡으려다
# 보간(interpolation) 손실로 오히려 글자가 뭉개진다.
_MIN_SKEW_DEGREES = 0.5


class ImagePreprocessor:
    """B/L 스캔 이미지 전처리기."""

    def __init__(self) -> None:
        try:
            import cv2  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "opencv-python 이 필요합니다: pip install opencv-python"
            ) from exc

    def process(self, image_path: str) -> "np.ndarray":
        """전처리 파이프라인 전체 실행."""
        img = self._load(image_path)
        img = self._to_grayscale(img)
        img = self._remove_noise(img)
        img = self._binarize(img)
        img = self._deskew(img)
        return self._normalize_resolution(img)

    def save(self, img: "np.ndarray", output_path: str) -> None:
        import cv2

        cv2.imwrite(str(output_path), img)

    # ── 개별 단계 ─────────────────────────────────────────────────

    @staticmethod
    def _load(path: str) -> "np.ndarray":
        import cv2

        img = cv2.imread(str(path))
        if img is None:
            raise FileNotFoundError(f"이미지를 로드할 수 없습니다: {path}")
        return img

    @staticmethod
    def _to_grayscale(img: "np.ndarray") -> "np.ndarray":
        import cv2

        if len(img.shape) == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    @staticmethod
    def _remove_noise(img: "np.ndarray") -> "np.ndarray":
        """Gaussian 으로 센서 노이즈를, Median 으로 점 노이즈를 지운다."""
        import cv2

        img = cv2.GaussianBlur(img, (3, 3), 0)
        return cv2.medianBlur(img, 3)

    @staticmethod
    def _binarize(img: "np.ndarray") -> "np.ndarray":
        """Adaptive Thresholding.

        스캔본은 조명이 고르지 않아 전역 임계값을 쓰면 한쪽 모서리가
        통째로 날아간다. 국소 임계값을 쓴다.
        """
        import cv2

        return cv2.adaptiveThreshold(
            img,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )

    def _deskew(self, img: "np.ndarray") -> "np.ndarray":
        import cv2

        angle = self._detect_skew_angle(img)
        if abs(angle) < _MIN_SKEW_DEGREES:
            return img

        h, w = img.shape[:2]
        matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(
            img,
            matrix,
            (w, h),
            flags=cv2.INTER_CUBIC,
            # 회전으로 생긴 여백을 검게 두면 그 경계가 새 엣지로 잡혀
            # 다음 단계에서 노이즈가 된다. 가장자리 픽셀을 늘려 채운다.
            borderMode=cv2.BORDER_REPLICATE,
        )

    @staticmethod
    def _detect_skew_angle(img: "np.ndarray") -> float:
        """Hough 변환으로 텍스트 라인의 기울기를 추정한다."""
        import cv2
        import numpy as np

        edges = cv2.Canny(img, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
        )
        if lines is None:
            return 0.0

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 == x1:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # 표·테두리의 수직선을 배제하고 텍스트 baseline 만 본다.
            if abs(angle) < 45:
                angles.append(angle)

        # 평균이 아니라 중앙값을 쓴다. 서식 테두리 한두 개가 튀어도
        # 전체 각도가 끌려가지 않는다.
        return float(np.median(angles)) if angles else 0.0

    @staticmethod
    def _normalize_resolution(img: "np.ndarray") -> "np.ndarray":
        """구역 좌표 기준 해상도로 확대한다. 축소는 하지 않는다."""
        import cv2

        h, w = img.shape[:2]
        if w >= STANDARD_WIDTH:
            return img
        scale = STANDARD_WIDTH / w
        return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

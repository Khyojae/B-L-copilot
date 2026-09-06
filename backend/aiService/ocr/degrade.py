"""스캔 열화 재현 (18번).

기획안 v2 10.3 ④ 가 요구하는 축이다 — **해상도 저하·기울기·노이즈·도장
겹침·접힘을 단계별로** 재현해, 추출기가 어느 지점에서 무너지는지 본다.

`preprocessor.py` 의 정확히 반대다. 저쪽은 지우고 여기는 만든다. 두 파일을
나란히 두는 이유가 그것이다 — 무엇을 지우려 만든 보정인지, 그 보정이 실제로
지우는지가 한자리에서 읽힌다.

## 축을 따로 건다

한 번에 다 걸면 "몇 단계에서 무너졌다"만 알고 **무엇 때문에 무너졌는지**를
모른다. 해상도 때문인지 도장 때문인지 구분되지 않으면 고칠 곳도 정해지지
않는다. 그래서 축별로 따로 걸 수 있게 하고, 합성은 명시적으로 요청할 때만
한다(`DegradationProfile`).

## 결정론이 아니면 재측정이 비교가 안 된다

v2 10.3 은 난수 시드를 저장하라고 요구한다. 같은 시드·같은 단계는 항상 같은
이미지여야, 룰이나 파서를 고친 뒤 다시 잰 값이 이전 값과 비교 가능하다.
`numpy.random.default_rng(seed)` 로 축마다 독립된 흐름을 쓴다 — 전역 난수를
쓰면 축을 하나 추가하는 것만으로 나머지 축의 결과가 전부 바뀐다.

## 이것은 실물 스캔이 아니다

합성 열화는 실제 복사기·팩스·스캐너가 만드는 열화와 다르다. 여기서 얻는 것은
**추출기의 상대적 내성**(어느 축에 약한가, 어느 단계에서 꺾이는가)이지
"실물에서 85% 를 넘는다"는 답이 아니다. 그 답은 실물 스캔 말뭉치가 있어야
나온다. 이 표를 정확도 근거로 인용하면 2.1 절이 겪은 것과 같은 과장이 된다.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    import numpy as np

# 단계. 0 은 원본이며 **표에 반드시 포함한다** — 열화 없는 값이 없으면
# 나머지 단계가 얼마나 나빠진 것인지 말할 수 없다.
LEVELS: Tuple[int, ...] = (0, 1, 2, 3)

NONE, LIGHT, MODERATE, SEVERE = LEVELS

LEVEL_LABELS: Dict[int, str] = {
    NONE: "원본",
    LIGHT: "약함",
    MODERATE: "보통",
    SEVERE: "심함",
}

# 축 이름. v2 10.3 ④ 의 열거 순서를 그대로 쓴다.
RESOLUTION = "해상도"
SKEW = "기울기"
NOISE = "노이즈"
STAMP = "도장"
FOLD = "접힘"

AXES: Tuple[str, ...] = (RESOLUTION, SKEW, NOISE, STAMP, FOLD)

# 축별 단계 강도. 단계 0 은 아무것도 하지 않으므로 표에서 뺀다.
#
# 값은 초기 목표치다(기획안 10.5). 실물 스캔과 대조해 조정할 때는 이 표만
# 고치지 말고 왜 바꿨는지를 남길 것.
_RESOLUTION_SCALE = {LIGHT: 0.60, MODERATE: 0.40, SEVERE: 0.25}
_SKEW_DEGREES = {LIGHT: 1.5, MODERATE: 4.0, SEVERE: 8.0}
_NOISE_SIGMA = {LIGHT: 8.0, MODERATE: 18.0, SEVERE: 32.0}
_SALT_PEPPER = {LIGHT: 0.002, MODERATE: 0.008, SEVERE: 0.020}
# 도장이 덮는 지면 폭 비율과 불투명도.
_STAMP_RADIUS = {LIGHT: 0.06, MODERATE: 0.10, SEVERE: 0.15}
_STAMP_ALPHA = {LIGHT: 0.25, MODERATE: 0.45, SEVERE: 0.65}
# 접힘선 개수와 그늘의 세기.
_FOLD_COUNT = {LIGHT: 1, MODERATE: 2, SEVERE: 3}
_FOLD_DARKNESS = {LIGHT: 0.12, MODERATE: 0.25, SEVERE: 0.40}


class DegradationError(RuntimeError):
    """열화를 적용할 수 없을 때."""


def _require_cv2():
    try:
        import cv2

        return cv2
    except ImportError as exc:  # pragma: no cover - 설치 환경에 달렸다
        raise DegradationError(
            "opencv-python 이 필요합니다: pip install opencv-python"
        ) from exc


def _rng(seed: int, axis: str, level: int):
    """축·단계마다 독립된 난수 흐름.

    시드 하나를 공유하면 축을 추가하거나 순서를 바꾸는 것만으로 다른 축의
    결과가 전부 달라진다. 그러면 "노이즈 축만 고쳤는데 도장 축 수치가
    바뀌었다"가 되어 비교가 성립하지 않는다.

    축을 구분하는 값으로 `hash(axis)` 를 쓰면 안 된다 — 파이썬 문자열 해시는
    **프로세스마다 달라진다**(PYTHONHASHSEED). 같은 시드로 오늘과 내일 만든
    이미지가 달라지고, 그러면 재측정이 비교가 되지 않는다. 열화 재현의
    존재 이유가 통째로 무너지는 종류의 버그라 안정된 값을 쓴다.
    """
    import numpy as np

    return np.random.default_rng((seed, zlib.crc32(axis.encode("utf-8")), level))


# ── 축별 열화 ────────────────────────────────────────────────────

def apply_resolution(img: "np.ndarray", level: int, seed: int = 0) -> "np.ndarray":
    """해상도 저하. 줄였다가 원래 크기로 되돌린다.

    되돌리는 것이 핵심이다. 작은 이미지를 그대로 주면 추출기가
    `_normalize_resolution` 으로 확대해 버려, 열화가 아니라 크기 차이만
    측정하게 된다. 잃은 정보를 잃은 채로 원래 크기를 되찾아야 한다.
    """
    if level == NONE:
        return img.copy()
    cv2 = _require_cv2()

    scale = _RESOLUTION_SCALE[level]
    h, w = img.shape[:2]
    small = cv2.resize(
        img, (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def apply_skew(img: "np.ndarray", level: int, seed: int = 0) -> "np.ndarray":
    """기울기. 부호를 무작위로 정해 한쪽으로만 기울지 않게 한다."""
    if level == NONE:
        return img.copy()
    cv2 = _require_cv2()

    rng = _rng(seed, SKEW, level)
    angle = _SKEW_DEGREES[level] * (1 if rng.random() < 0.5 else -1)

    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h),
        flags=cv2.INTER_LINEAR,
        # 검은 여백을 두면 그 경계가 새 엣지가 되어 기울기 추정을 돕는다 —
        # 열화가 오히려 보정을 쉽게 만드는 셈이라 가장자리를 늘려 채운다.
        borderMode=cv2.BORDER_REPLICATE,
    )


def apply_noise(img: "np.ndarray", level: int, seed: int = 0) -> "np.ndarray":
    """센서 노이즈(가우시안) + 점 노이즈(소금·후추).

    둘을 함께 거는 이유는 `preprocessor._remove_noise` 가 Gaussian 과 Median
    두 가지로 지우기 때문이다. 한 종류만 만들면 보정의 절반이 검사되지 않는다.
    """
    if level == NONE:
        return img.copy()
    import numpy as np

    rng = _rng(seed, NOISE, level)
    out = img.astype(np.float32)
    out += rng.normal(0.0, _NOISE_SIGMA[level], size=img.shape)

    mask = rng.random(img.shape[:2])
    ratio = _SALT_PEPPER[level]
    out[mask < ratio / 2] = 0.0
    out[mask > 1 - ratio / 2] = 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_stamp(img: "np.ndarray", level: int, seed: int = 0) -> "np.ndarray":
    """도장 겹침. 글자 위에 반투명 원형 인영을 얹는다.

    **글자가 있는 자리에 놓아야 한다.** 여백에 찍으면 아무것도 가리지 않아
    열화가 아니다. 어두운 픽셀이 몰린 곳을 골라 그 위에 얹는다.
    """
    if level == NONE:
        return img.copy()
    cv2 = _require_cv2()
    import numpy as np

    rng = _rng(seed, STAMP, level)
    out = img.copy()
    h, w = img.shape[:2]
    radius = int(min(h, w) * _STAMP_RADIUS[level])

    center = _densest_text_point(img, radius, rng)
    overlay = out.copy()
    color = (0, 0, 200) if out.ndim == 3 else 90     # 인영은 붉은색이다
    cv2.circle(overlay, center, radius, color, thickness=-1)
    cv2.circle(overlay, center, int(radius * 0.82), color, thickness=max(2, radius // 12))

    alpha = _STAMP_ALPHA[level]
    blended = cv2.addWeighted(overlay, alpha, out, 1 - alpha, 0)
    return np.asarray(blended, dtype=np.uint8)


def _densest_text_point(img: "np.ndarray", radius: int, rng) -> Tuple[int, int]:
    """글자가 가장 몰린 지점. 가장자리는 반지름만큼 피한다."""
    import numpy as np

    gray = img if img.ndim == 2 else img.mean(axis=2)
    # 밝은 종이 위의 어두운 글자. 임계값 아래를 글자로 본다.
    ink = (gray < 128).astype(np.float32)

    h, w = ink.shape
    if h <= 2 * radius or w <= 2 * radius:
        return (w // 2, h // 2)

    # 격자로 훑어 가장 진한 칸을 고른다. 정밀할 필요가 없어 성긴 격자로 둔다.
    best, best_score = (w // 2, h // 2), -1.0
    step = max(1, radius // 2)
    for y in range(radius, h - radius, step):
        for x in range(radius, w - radius, step):
            score = float(ink[y - radius:y + radius, x - radius:x + radius].sum())
            if score > best_score:
                best, best_score = (x, y), score

    if best_score <= 0:
        # 글자를 못 찾았다. 무작위로 두되 가장자리는 피한다.
        return (
            int(rng.integers(radius, w - radius)),
            int(rng.integers(radius, h - radius)),
        )
    return best


def apply_fold(img: "np.ndarray", level: int, seed: int = 0) -> "np.ndarray":
    """접힘. 가로 접힘선에 그늘을 넣고 선 양쪽을 어긋나게 민다.

    그늘만 넣으면 밝기 보정으로 지워진다. 실제 접힌 종이는 **글자가 어긋난다** —
    그 어긋남이 구역 좌표를 밀어내는 부분이고, 여기서 보고 싶은 것도 그쪽이다.
    """
    if level == NONE:
        return img.copy()
    import numpy as np

    rng = _rng(seed, FOLD, level)
    out = img.copy()
    h, w = img.shape[:2]

    for _ in range(_FOLD_COUNT[level]):
        y = int(rng.integers(int(h * 0.15), int(h * 0.85)))
        band = max(2, int(h * 0.004))
        top, bottom = max(0, y - band), min(h, y + band)

        shade = 1.0 - _FOLD_DARKNESS[level]
        out[top:bottom] = np.clip(
            out[top:bottom].astype(np.float32) * shade, 0, 255
        ).astype(np.uint8)

        # 접힘선 아래를 옆으로 민다. 종이가 접히면 두 면이 어긋나 붙는다.
        shift = int(rng.integers(1, max(2, int(w * 0.004))))
        if bottom < h:
            out[bottom:] = np.roll(out[bottom:], shift, axis=1)

    return out


APPLIERS: Dict[str, Callable[..., "np.ndarray"]] = {
    RESOLUTION: apply_resolution,
    SKEW: apply_skew,
    NOISE: apply_noise,
    STAMP: apply_stamp,
    FOLD: apply_fold,
}


# ── 조합 ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DegradationProfile:
    """축별 단계. 재현에 필요한 것이 이 값과 시드뿐이어야 한다."""

    levels: Dict[str, int]
    seed: int = 0

    @classmethod
    def single(cls, axis: str, level: int, seed: int = 0) -> "DegradationProfile":
        """축 하나만 건다. 기본 측정 단위다."""
        if axis not in APPLIERS:
            raise DegradationError(
                f"알 수 없는 축 '{axis}' (가능: {', '.join(AXES)})"
            )
        return cls(levels={axis: level}, seed=seed)

    @classmethod
    def uniform(cls, level: int, seed: int = 0) -> "DegradationProfile":
        """모든 축을 같은 단계로. 최악을 볼 때만 쓴다 — 어느 축 때문인지는 못 본다."""
        return cls(levels={axis: level for axis in AXES}, seed=seed)

    @property
    def label(self) -> str:
        active = [f"{a}{self.levels[a]}" for a in AXES if self.levels.get(a)]
        return "+".join(active) if active else "원본"

    def to_dict(self) -> dict:
        return {"levels": dict(self.levels), "seed": self.seed, "label": self.label}


def degrade(
    img: "np.ndarray", profile: DegradationProfile
) -> "np.ndarray":
    """프로파일대로 열화를 적용한다.

    적용 순서는 `AXES` 순서로 고정한다. 순서가 바뀌면 결과가 달라지는데
    (노이즈를 먼저 넣고 축소하면 노이즈가 뭉개진다), 순서를 호출부에
    맡기면 같은 프로파일이 다른 이미지를 낸다.
    """
    out = img
    for axis in AXES:
        level = profile.levels.get(axis, NONE)
        if level:
            if level not in LEVELS:
                raise DegradationError(f"{axis}: 단계는 {LEVELS} 중 하나여야 합니다")
            out = APPLIERS[axis](out, level, profile.seed)
    return out


def sweep(
    img: "np.ndarray",
    axes: Optional[Tuple[str, ...]] = None,
    seed: int = 0,
) -> List[Tuple[DegradationProfile, "np.ndarray"]]:
    """축별·단계별 이미지를 전부 만든다.

    원본(단계 0)을 **한 번만** 넣는다. 축마다 넣으면 같은 이미지가 축 수만큼
    중복되어, 표를 읽는 사람이 원본이 여러 개인 줄 알게 된다.
    """
    axes = axes or AXES
    base = DegradationProfile(levels={}, seed=seed)
    out: List[Tuple[DegradationProfile, "np.ndarray"]] = [(base, img.copy())]

    for axis in axes:
        for level in LEVELS:
            if level == NONE:
                continue
            profile = DegradationProfile.single(axis, level, seed)
            out.append((profile, degrade(img, profile)))
    return out


# ── 성적표 ───────────────────────────────────────────────────────
#
# 열화를 만들기만 하고 아무도 부르지 않으면 도구가 아니라 코드다. 축·단계별로
# 추출을 돌려 어디서 꺾이는지를 표로 낸다.
#
# 이 경로는 PaddleOCR 이 필요하다(이미지를 실제로 읽어야 하므로). 테스트는
# 여기를 타지 않는다 — 타게 하면 CI 가 OCR 설치와 장당 10초에 묶인다.

@dataclass
class DegradationScore:
    """열화 1건에 대한 추출 성적."""

    profile: DegradationProfile
    filled: int          # 값이 채워진 필드 수
    total: int           # 전체 필드 수
    review: int          # 사람 확인으로 라우팅된 필드 수
    mean_confidence: float
    elapsed_ms: float

    @property
    def fill_ratio(self) -> float:
        return self.filled / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict(),
            "filled": self.filled,
            "total": self.total,
            "fill_ratio": round(self.fill_ratio, 4),
            "review": self.review,
            "mean_confidence": round(self.mean_confidence, 4),
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


def score_sweep(image_path: str, seed: int = 0) -> List[DegradationScore]:
    """축·단계별로 열화해 추출을 돌리고 성적을 모은다."""
    import tempfile
    from time import perf_counter

    cv2 = _require_cv2()
    from .pipeline import IntakePipeline

    img = cv2.imread(str(image_path))
    if img is None:
        raise DegradationError(f"이미지를 로드할 수 없습니다: {image_path}")

    pipeline = IntakePipeline()
    scores: List[DegradationScore] = []

    with tempfile.TemporaryDirectory() as tmp:
        for index, (profile, degraded) in enumerate(sweep(img, seed=seed)):
            path = f"{tmp}/{index:02d}.png"
            cv2.imwrite(path, degraded)

            start = perf_counter()
            # 전처리는 켠 채로 둔다. 우리가 아는 것은 "보정을 거친 파이프라인이
            # 이 열화를 견디는가"이지 원시 OCR 의 내성이 아니다.
            draft = pipeline.run_from_image(path)
            elapsed = (perf_counter() - start) * 1000

            scores.append(DegradationScore(
                profile=profile,
                filled=sum(1 for f in draft.fields if f.value),
                total=len(draft.fields),
                review=len(draft.review_fields),
                mean_confidence=draft.ocr_mean_confidence,
                elapsed_ms=elapsed,
            ))
    return scores


def render_scores(scores: Sequence[DegradationScore]) -> str:
    lines = [
        "",
        "스캔 열화 단계별 추출 성적 (기획안 v2 10.3 ④)",
        "=" * 68,
        f"{'프로파일':<14} {'추출':<12} {'확인요청':<10} {'평균신뢰도':<12} 시간",
        "-" * 68,
    ]
    for s in scores:
        lines.append(
            f"{s.profile.label:<14} {s.filled:>2}/{s.total:<9} "
            f"{s.review:>3}{'':<7} {s.mean_confidence:<12.4f} {s.elapsed_ms / 1000:.1f}초"
        )
    lines.append("-" * 68)
    lines.append(
        "이 표는 **상대적 내성**이다. 합성 열화는 실물 스캔과 다르므로 "
        "여기 수치를 수용 기준(스캔 85%)의 답으로 쓰지 말 것."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="스캔 열화 단계별 추출 성적 (18번)")
    parser.add_argument("--image", required=True, help="열화를 걸 원본 서류 이미지")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", help="결과를 JSON 으로 저장")
    args = parser.parse_args()

    scores = score_sweep(args.image, seed=args.seed)
    print(render_scores(scores))

    if args.json:
        Path(args.json).write_text(
            _json.dumps(
                {"seed": args.seed, "scores": [s.to_dict() for s in scores]},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(f"JSON 저장: {args.json}")


__all__ = [
    "AXES",
    "FOLD",
    "LEVELS",
    "LEVEL_LABELS",
    "LIGHT",
    "MODERATE",
    "NOISE",
    "NONE",
    "RESOLUTION",
    "SEVERE",
    "SKEW",
    "STAMP",
    "DegradationError",
    "DegradationProfile",
    "DegradationScore",
    "degrade",
    "render_scores",
    "score_sweep",
    "sweep",
]


if __name__ == "__main__":
    main()

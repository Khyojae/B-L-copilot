"""
F1 서류 인테이크 공용 타입.

필드 값과 신뢰도를 **별도 맵으로 분리**해서 담는다. `ocr_results` 테이블이
structured_fields(JSONB) 와 field_confidence(JSONB) 를 두 컬럼으로 나눠 정의하고
있어 그 구조를 그대로 따른 것이다. 값과 신뢰도를 한 객체에 묶으면 저장 시점에
다시 갈라야 하고, 하자 검증기(F3)는 값만 필요한데 래퍼를 벗겨야 한다.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# 신뢰도 등급 경계 (기획안 v2 5.1 "신뢰도 등급과 휴먼 확인 라우팅").
#
#   확정      0.90 이상           자동 반영, 확인 불필요
#   확인 권고  0.70 이상 0.90 미만  검증 실행은 가능하되 리포트에 미확인 항목으로 기재
#   필수 확인  0.70 미만           해당 필드 확인 전까지 "검증 실행" 차단
#   미검출     근거 위치 없음       직접 입력 유도 (임의 추정값 표시 금지)
#
# v2 10.5 는 이 둘을 "제품이 지향하는 초기 목표치이며 실측이나 실무 검토로
# 확정된 값이 아니다"로 규정한다. 옮길 때는 기획안 5장과 10장을 함께 갱신하고
# 근거를 남길 것 — 이 파일만 고치면 명세와 코드가 조용히 갈라진다.
CONFIRMED_THRESHOLD = 0.90
REVIEW_REQUIRED_THRESHOLD = 0.70

# 하자 예측 모델의 `low_confidence_ratio` 피처가 쓰는 경계.
#
# **화면 기준선이 아니다.** S3 편집기의 노란색 배경은 위 `CONFIRMED_THRESHOLD`
# 가 가른다. 이 값이 0.80 에 남아 있는 것은 학습 분포 때문이다 — 지금 모델은
# 0.80 으로 센 비율을 보고 학습했고, 등급 경계를 따라 0.90 으로 옮기면 같은
# 서류의 피처 값이 달라진다. 그런데 **모델은 그 사실을 알리지 않고 그럴듯한
# 확률을 낸다.** 조용히 틀린 값은 눈에 보이는 실패보다 나쁘다.
#
# 옮기려면 재학습이 먼저다(`remaining-work.md` 29·30번).
LOW_CONFIDENCE_THRESHOLD = 0.80

# 구역(좌표) 기반이 아니라 키워드 앵커로 찾은 값에 적용하는 감점 계수.
# 앵커는 "라벨 오른쪽/아래에 값이 있다"는 레이아웃 가정에 의존하므로
# OCR 자체가 확신하더라도 매핑이 틀렸을 여지가 구역 방식보다 크다.
ANCHOR_CONFIDENCE_PENALTY = 0.85


class ConfidenceGrade(str, Enum):
    """필드 신뢰도 등급 (기획안 v2 5.1 등급표).

    등급을 사유(`draft.ReviewReason`)와 **따로 두는 이유**는 둘이 다른 질문에
    답하기 때문이다. 사유는 "왜 확인해야 하는가"를 사람에게 설명하고, 등급은
    "얼마나 못 믿는가"를 기계가 센다. 후자가 없으면 5.4 의 보류 20% 게이트처럼
    **개수를 세는 규칙**을 쓸 수 없다 — 사유는 6종이라 심각도 순서가 없다.
    """

    CONFIRMED = "confirmed"      # 확정
    RECOMMENDED = "recommended"  # 확인 권고
    REQUIRED = "required"        # 필수 확인
    UNDETECTED = "undetected"    # 미검출

    @property
    def label(self) -> str:
        return {
            "confirmed": "확정",
            "recommended": "확인 권고",
            "required": "필수 확인",
            "undetected": "미검출",
        }[self.value]

    @property
    def blocks_verification(self) -> bool:
        """이 등급이 "검증 실행"을 막는지.

        **필수 확인만 막는다.** 미검출은 5.1 이 "사용자 직접 입력 유도"로
        정했을 뿐 차단 대상이 아니다 — 값이 없는 것은 룰엔진이 `missing_field`
        로 이미 하자로 잡으므로, 차단까지 걸면 같은 사실로 두 번 멈춰 세운다.
        """
        return self is ConfidenceGrade.REQUIRED


# 등급의 심각도 순서. 미검출은 여기 없다 — 값이 없으면 다른 판정과 겹칠 여지
# 없이 미검출로 확정되므로, 강등 결합에 참여하지 않는다.
_GRADE_RANK: Dict[ConfidenceGrade, int] = {
    ConfidenceGrade.CONFIRMED: 0,
    ConfidenceGrade.RECOMMENDED: 1,
    ConfidenceGrade.REQUIRED: 2,
}


def grade_for(
    value: Optional[str],
    confidence: Optional[float],
    demote_to: Optional[ConfidenceGrade] = None,
    confirmed: float = CONFIRMED_THRESHOLD,
    required: float = REVIEW_REQUIRED_THRESHOLD,
) -> ConfidenceGrade:
    """값과 신뢰도로 등급을 매긴다.

    `demote_to` 는 신뢰도와 무관하게 적용할 하한이다. 5.1 이 "스키마 위반 ·
    출처 간 값 충돌"을 신뢰도와 **별개의 필수 확인 사유**로 적고, "손글씨
    기재·도장 겹침·저해상도 팩스 스캔은 필수 확인 등급으로 강등한다"고
    쓴 것이 이 자리다. 둘 중 나쁜 쪽을 택한다.

    **신뢰도가 없으면 확정으로 본다.** S3 편집기에서 사람이 고쳐 넣은 값이
    이 경로로 오고, 사람이 확정한 값에는 OCR 불확실성이 없다. `features.py`
    의 신뢰도 계열 피처가 dict 입력에서 기본값으로 떨어지는 것과 같은 판단이다.

    `confirmed`·`required` 는 스캔 품질이 일정하게 나쁜 배치에서 확인 큐를
    감당 가능한 크기로 줄일 때 함께 내린다. **한쪽만 내리면 안 된다** —
    확정 경계만 내리면 필수 확인 구간이 그대로 남아 검증 차단이 풀리지 않고,
    그 배치는 아무것도 검증하지 못한다.
    """
    if not value:
        return ConfidenceGrade.UNDETECTED

    if confidence is None:
        graded = ConfidenceGrade.CONFIRMED
    elif confidence < required:
        graded = ConfidenceGrade.REQUIRED
    elif confidence < confirmed:
        graded = ConfidenceGrade.RECOMMENDED
    else:
        graded = ConfidenceGrade.CONFIRMED

    if demote_to is None or demote_to is ConfidenceGrade.UNDETECTED:
        return graded
    return max(graded, demote_to, key=_GRADE_RANK.__getitem__)


def review_required_fields(
    values: Dict[str, Optional[str]],
    confidence: Optional[Dict[str, float]] = None,
) -> List[str]:
    """필수 확인 등급인 필드 이름.

    F3 가 판정을 보류할 대상이다(5.3). 값 dict 와 신뢰도 dict 를 받는 이유는
    **이 경로에 초안 객체가 없기 때문**이다 — `/verify` 는 F1 이 뽑은 값이든
    사람이 고친 값이든 같은 형태로 받고, 신뢰도는 `ocr_results.field_confidence`
    와 같은 별도 맵으로 온다.

    신뢰도를 주지 않으면 빈 목록이다. 등급을 모르는 것과 전부 확정인 것은
    다르지만, 여기서 후자로 보는 편이 안전하다 — 모른다고 전부 보류하면
    신뢰도를 싣지 않는 기존 호출부의 검증이 통째로 멈춘다.
    """
    confidence = confidence or {}
    return [
        name
        for name, value in values.items()
        if grade_for(value, confidence.get(name)) is ConfidenceGrade.REQUIRED
    ]


@dataclass
class BBox:
    """단일 OCR 바운딩 박스."""

    text: str
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    # PaddleOCR 의 rec_scores. 라벨 JSON 로드 시에는 1.0(정답 데이터).
    confidence: float = 1.0
    center_x: float = field(init=False)
    center_y: float = field(init=False)

    def __post_init__(self) -> None:
        self.center_x = (self.x_min + self.x_max) / 2
        self.center_y = (self.y_min + self.y_max) / 2

    @property
    def width(self) -> int:
        return self.x_max - self.x_min

    @property
    def height(self) -> int:
        return self.y_max - self.y_min


@dataclass
class OCRResult:
    """OCR 추출 결과 (문서 1건)."""

    image_id: str
    image_width: int
    image_height: int
    form_type: str
    bboxes: List[BBox]
    source: str  # "json" | "paddleocr"
    processing_time_ms: Optional[int] = None
    model_version: Optional[str] = None

    @property
    def raw_text(self) -> str:
        """읽기 순서로 이어붙인 원문. ocr_results.raw_text 에 대응."""
        ordered = sorted(self.bboxes, key=lambda b: (b.center_y, b.x_min))
        return "\n".join(b.text for b in ordered)

    @property
    def mean_confidence(self) -> float:
        if not self.bboxes:
            return 0.0
        return sum(b.confidence for b in self.bboxes) / len(self.bboxes)


# 추출 대상 필드. 순서는 B/L 서식의 읽기 순서를 따른다.
BL_FIELD_NAMES = (
    "bl_no",
    "shipper",
    "consignee",
    "notify_party",
    "vessel",
    "voyage_no",
    "port_of_loading",
    "port_of_discharge",
    "description_of_goods",
    "gross_weight",
    "measurement",
    "date_of_issue",
    "place_of_issue",
    "on_board_date",
    "total_freight",
    "incoterms",
    "no_of_original_bl",
    "bl_clauses",
)

# 이게 비면 하자 검증 자체가 성립하지 않는 필드.
CRITICAL_FIELD_NAMES = (
    "bl_no",
    "consignee",
    "port_of_loading",
    "port_of_discharge",
    "date_of_issue",
)


@dataclass
class BLFields:
    """추출된 B/L 필드 집합."""

    bl_no: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    notify_party: Optional[str] = None
    vessel: Optional[str] = None
    voyage_no: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    description_of_goods: Optional[str] = None
    gross_weight: Optional[str] = None
    measurement: Optional[str] = None
    date_of_issue: Optional[str] = None
    place_of_issue: Optional[str] = None
    on_board_date: Optional[str] = None
    total_freight: Optional[str] = None
    incoterms: Optional[str] = None
    no_of_original_bl: Optional[str] = None
    # 원문 페이지 전체 텍스트. 문언·부기(charter party, 갑판적재, 정정 등)는
    # 라벨 박스가 없어 구역/앵커 추출로 못 잡으므로 전체 스캔이 유일한 방법이다.
    bl_clauses: Optional[str] = None

    # 필드명 → 0.0~1.0. 추출 실패한 필드는 아예 키가 없다.
    confidence: Dict[str, float] = field(default_factory=dict)
    # 필드명 → "region" | "anchor". 왜 그 값이 나왔는지 설명할 때 쓴다.
    provenance: Dict[str, str] = field(default_factory=dict)
    # 필드명 → 그 값을 만든 bbox 들 (원본 이미지 픽셀 좌표). "출처 없는 값은
    # 표시하지 않는다" 원칙을 지키려면 값뿐 아니라 어디서 읽었는지도 함께
    # 남겨야 한다 — draft.py 가 여기서 정규화된 사각형을 계산한다.
    bbox: Dict[str, List[BBox]] = field(default_factory=dict)
    # 원시 구역 텍스트 (디버그용)
    raw_regions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """값만 담은 dict. ocr_results.structured_fields 에 대응."""
        return {name: getattr(self, name) for name in BL_FIELD_NAMES}

    def confidence_dict(self) -> Dict[str, float]:
        """추출된 필드의 신뢰도. ocr_results.field_confidence 에 대응."""
        return dict(self.confidence)

    def missing_critical_fields(self) -> List[str]:
        """추출 실패한 핵심 필드 목록."""
        return [n for n in CRITICAL_FIELD_NAMES if not getattr(self, n)]

    def low_confidence_fields(
        self, threshold: float = LOW_CONFIDENCE_THRESHOLD
    ) -> List[str]:
        """사람 확인이 필요한 필드 목록.

        기획안 S3 의 저신뢰 하이라이트 대상이다. 값이 아예 없는 필드는
        '저신뢰'가 아니라 '누락'이므로 여기 포함하지 않는다.
        """
        return [
            name
            for name in BL_FIELD_NAMES
            if getattr(self, name) and self.confidence.get(name, 0.0) < threshold
        ]

    def set_field(
        self,
        name: str,
        value: Optional[str],
        confidence: float,
        source: str,
        bboxes: Optional[List[BBox]] = None,
    ) -> None:
        """필드 값과 근거를 함께 기록한다.

        값이 없으면 신뢰도도 남기지 않는다. '값 없음'과 '신뢰도 0'은
        의미가 다르고, 후자를 남기면 저신뢰 목록 계산이 지저분해진다.
        """
        if name not in BL_FIELD_NAMES:
            raise ValueError(f"알 수 없는 필드: {name}")
        setattr(self, name, value)
        if value:
            self.confidence[name] = round(max(0.0, min(1.0, confidence)), 4)
            self.provenance[name] = source
            if bboxes:
                self.bbox[name] = bboxes
            else:
                self.bbox.pop(name, None)
        else:
            self.confidence.pop(name, None)
            self.provenance.pop(name, None)
            self.bbox.pop(name, None)

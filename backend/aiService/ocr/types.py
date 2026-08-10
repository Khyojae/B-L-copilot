"""
F1 서류 인테이크 공용 타입.

필드 값과 신뢰도를 **별도 맵으로 분리**해서 담는다. `ocr_results` 테이블이
structured_fields(JSONB) 와 field_confidence(JSONB) 를 두 컬럼으로 나눠 정의하고
있어 그 구조를 그대로 따른 것이다. 값과 신뢰도를 한 객체에 묶으면 저장 시점에
다시 갈라야 하고, 하자 검증기(F3)는 값만 필요한데 래퍼를 벗겨야 한다.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 이 값 미만이면 사람이 확인해야 하는 필드로 본다.
# 기획안 S3(초안 편집기)의 "저신뢰 필드 노란색 배경" 기준선.
LOW_CONFIDENCE_THRESHOLD = 0.80

# 구역(좌표) 기반이 아니라 키워드 앵커로 찾은 값에 적용하는 감점 계수.
# 앵커는 "라벨 오른쪽/아래에 값이 있다"는 레이아웃 가정에 의존하므로
# OCR 자체가 확신하더라도 매핑이 틀렸을 여지가 구역 방식보다 크다.
ANCHOR_CONFIDENCE_PENALTY = 0.85


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

    # 필드명 → 0.0~1.0. 추출 실패한 필드는 아예 키가 없다.
    confidence: Dict[str, float] = field(default_factory=dict)
    # 필드명 → "region" | "anchor". 왜 그 값이 나왔는지 설명할 때 쓴다.
    provenance: Dict[str, str] = field(default_factory=dict)
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
        else:
            self.confidence.pop(name, None)
            self.provenance.pop(name, None)

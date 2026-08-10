"""
B/L 초안 생성 (F1 후반부).

추출 결과를 사용자가 확인·수정할 초안으로 바꾼다. 기획안 F1 의 정의가
"사용자는 확인·수정만 수행"이므로, 초안은 값만 담아선 안 되고 **어디를
봐야 하는지**를 함께 알려줘야 한다. 그래서 필드마다 확인 필요 여부와
그 사유를 붙인다.

기획안 S3(초안 편집기)가 이 구조를 그대로 화면에 쓴다 — 저신뢰 필드는
노란색 배경, 누락 필드는 빈 입력란.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .types import (
    BL_FIELD_NAMES,
    CRITICAL_FIELD_NAMES,
    LOW_CONFIDENCE_THRESHOLD,
    BLFields,
    OCRResult,
)


class ReviewReason(str, Enum):
    """사람이 확인해야 하는 이유."""

    MISSING_CRITICAL = "missing_critical"   # 핵심 필드인데 추출 실패
    MISSING = "missing"                     # 그 외 필드 추출 실패
    LOW_CONFIDENCE = "low_confidence"       # 값은 있으나 OCR 신뢰도 미달
    ANCHOR_DERIVED = "anchor_derived"       # 좌표가 아닌 라벨 근접으로 추정


# 화면에 그대로 쓸 수 있는 한국어 라벨.
FIELD_LABELS: Dict[str, str] = {
    "bl_no": "B/L 번호",
    "shipper": "송하인",
    "consignee": "수하인",
    "notify_party": "통지처",
    "vessel": "선박명",
    "voyage_no": "항차",
    "port_of_loading": "선적항",
    "port_of_discharge": "양하항",
    "description_of_goods": "화물 명세",
    "gross_weight": "총 중량",
    "measurement": "용적",
    "date_of_issue": "발행일",
    "place_of_issue": "발행지",
    "on_board_date": "선적일",
    "total_freight": "운임",
}

_REASON_MESSAGES: Dict[ReviewReason, str] = {
    ReviewReason.MISSING_CRITICAL: "검증에 반드시 필요한 항목입니다. 직접 입력해 주세요.",
    ReviewReason.MISSING: "추출하지 못했습니다. 원본을 확인해 주세요.",
    ReviewReason.LOW_CONFIDENCE: "인식 정확도가 낮습니다. 원본과 대조해 주세요.",
    ReviewReason.ANCHOR_DERIVED: "위치가 아닌 항목명으로 찾은 값입니다. 확인해 주세요.",
}


@dataclass
class DraftField:
    """초안의 필드 하나."""

    name: str
    label: str
    value: Optional[str]
    confidence: Optional[float]
    is_critical: bool
    needs_review: bool
    review_reason: Optional[ReviewReason] = None
    review_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "confidence": self.confidence,
            "is_critical": self.is_critical,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason.value if self.review_reason else None,
            "review_message": self.review_message,
        }


@dataclass
class BLDraft:
    """사용자가 확인·수정할 B/L 초안."""

    image_id: str
    fields: List[DraftField] = field(default_factory=list)
    source: str = ""
    ocr_mean_confidence: float = 0.0
    processing_time_ms: Optional[int] = None

    # ── 조회 ──────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[DraftField]:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def review_fields(self) -> List[DraftField]:
        """확인이 필요한 필드. 핵심 필드를 앞에 둔다."""
        pending = [f for f in self.fields if f.needs_review]
        return sorted(pending, key=lambda f: (not f.is_critical, f.name))

    @property
    def is_ready_for_verification(self) -> bool:
        """하자 검증(F3)을 돌릴 수 있는 상태인지.

        핵심 필드가 비어 있으면 검증 결과가 '값이 없어서 하자'로만
        도배되어 의미가 없다.
        """
        return not any(f.is_critical and not f.value for f in self.fields)

    def completeness(self) -> float:
        """값이 채워진 필드 비율."""
        if not self.fields:
            return 0.0
        filled = sum(1 for f in self.fields if f.value)
        return round(filled / len(self.fields), 4)

    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "source": self.source,
            "ocr_mean_confidence": round(self.ocr_mean_confidence, 4),
            "processing_time_ms": self.processing_time_ms,
            "completeness": self.completeness(),
            "is_ready_for_verification": self.is_ready_for_verification,
            "review_required_count": len(self.review_fields),
            "fields": [f.to_dict() for f in self.fields],
        }


def build_draft(
    fields: BLFields,
    ocr: Optional[OCRResult] = None,
    threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> BLDraft:
    """추출 결과 → 초안.

    threshold 는 저신뢰 판정선이다. 스캔 품질이 일정하게 나쁜 배치에서는
    낮춰 잡아야 확인 큐가 실무적으로 감당 가능한 크기가 된다.
    """
    draft = BLDraft(
        image_id=ocr.image_id if ocr else "",
        source=ocr.source if ocr else "",
        ocr_mean_confidence=ocr.mean_confidence if ocr else 0.0,
        processing_time_ms=ocr.processing_time_ms if ocr else None,
    )

    for name in BL_FIELD_NAMES:
        value = getattr(fields, name)
        confidence = fields.confidence.get(name)
        is_critical = name in CRITICAL_FIELD_NAMES
        reason = _review_reason(name, value, confidence, fields, is_critical, threshold)

        draft.fields.append(
            DraftField(
                name=name,
                label=FIELD_LABELS.get(name, name),
                value=value,
                confidence=confidence,
                is_critical=is_critical,
                needs_review=reason is not None,
                review_reason=reason,
                review_message=_REASON_MESSAGES.get(reason) if reason else None,
            )
        )

    return draft


def _review_reason(
    name: str,
    value: Optional[str],
    confidence: Optional[float],
    fields: BLFields,
    is_critical: bool,
    threshold: float,
) -> Optional[ReviewReason]:
    """확인이 필요한 이유. 필요 없으면 None."""
    if not value:
        return ReviewReason.MISSING_CRITICAL if is_critical else ReviewReason.MISSING

    if confidence is not None and confidence < threshold:
        return ReviewReason.LOW_CONFIDENCE

    # 앵커 추출은 OCR 신뢰도가 높아도 매핑이 틀렸을 수 있다.
    # 핵심 필드에 한해서만 확인을 요구한다 — 전 필드에 걸면
    # 확인 큐가 불어나 F1 의 시간 단축 효과가 사라진다.
    if is_critical and fields.provenance.get(name) == "anchor":
        return ReviewReason.ANCHOR_DERIVED

    return None

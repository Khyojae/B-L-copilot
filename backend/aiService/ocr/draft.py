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

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .types import (
    BL_FIELD_NAMES,
    CONFIRMED_THRESHOLD,
    CRITICAL_FIELD_NAMES,
    REVIEW_REQUIRED_THRESHOLD,
    BBox,
    BLFields,
    ConfidenceGrade,
    OCRResult,
    grade_for,
)


class ReviewReason(str, Enum):
    """사람이 확인해야 하는 이유."""

    MISSING_CRITICAL = "missing_critical"   # 핵심 필드인데 추출 실패
    MISSING = "missing"                     # 그 외 필드 추출 실패
    LOW_CONFIDENCE = "low_confidence"       # 값은 있으나 OCR 신뢰도 미달
    ANCHOR_DERIVED = "anchor_derived"       # 좌표가 아닌 라벨 근접으로 추정
    LABEL_ECHOED = "label_echoed"           # 값에 항목명이 그대로 섞임
    UNCALIBRATED_LAYOUT = "uncalibrated_layout"  # 구역 좌표를 보정하지 않은 형식


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
    "incoterms": "인코텀즈",
    "no_of_original_bl": "원본 통수",
    "bl_clauses": "문언·부기",
}

# 신뢰도와 무관하게 등급을 끌어내리는 사유 (기획안 v2 5.1).
#
# 5.1 은 필수 확인의 기준으로 "0.70 미만 · **스키마 위반** · 출처 간 값 충돌"
# 셋을 나란히 적는다. 즉 신뢰도가 높아도 값의 형태가 틀렸으면 필수 확인이다.
# 아래 셋이 우리 코드에서 그 자리에 해당한다.
#
# **`LABEL_ECHOED` 만 필수 확인이다.** 값에 서식 항목명이 섞였다는 것은 값이
# 틀렸다는 뜻이지 흐릿하다는 뜻이 아니므로 스키마 위반으로 본다.
#
# 나머지 둘은 확인 권고에 둔다. 필수 확인으로 올리면 **검증 실행이 차단**되는데,
# `UNCALIBRATED_LAYOUT` 은 pdf-text·excel·email-body 경로의 핵심 필드 전건에
# 걸리므로 그 세 입력 경로가 통째로 죽는다. `ANCHOR_DERIVED` 도 이미
# `ANCHOR_CONFIDENCE_PENALTY`(0.85)로 신뢰도가 깎여 확인 권고 구간에 들어와
# 있어, 여기서 다시 올릴 이유가 없다.
_GRADE_DEMOTION: Dict[ReviewReason, ConfidenceGrade] = {
    ReviewReason.LABEL_ECHOED: ConfidenceGrade.REQUIRED,
    ReviewReason.UNCALIBRATED_LAYOUT: ConfidenceGrade.RECOMMENDED,
    ReviewReason.ANCHOR_DERIVED: ConfidenceGrade.RECOMMENDED,
}

_REASON_MESSAGES: Dict[ReviewReason, str] = {
    ReviewReason.MISSING_CRITICAL: "검증에 반드시 필요한 항목입니다. 직접 입력해 주세요.",
    ReviewReason.MISSING: "추출하지 못했습니다. 원본을 확인해 주세요.",
    ReviewReason.LOW_CONFIDENCE: "인식 정확도가 낮습니다. 원본과 대조해 주세요.",
    ReviewReason.ANCHOR_DERIVED: "위치가 아닌 항목명으로 찾은 값입니다. 확인해 주세요.",
    ReviewReason.LABEL_ECHOED: "값에 서식의 항목명이 섞여 있습니다. 원본과 대조해 주세요.",
    ReviewReason.UNCALIBRATED_LAYOUT: "이 형식은 필드 위치가 서식마다 달라 값이 밀릴 수 있습니다. 원본과 대조해 주세요.",
}

# 구역 좌표를 보정하지 않은 입력 형식.
#
# `FieldParser.REGIONS` 는 라벨 데이터셋(1654×2340 스캔본) 레이아웃에 맞춰
# 교정된 값이다. 그 데이터셋에서 온 입력(`json`)과 OCR 로 읽은 스캔본은 같은
# 서식 계열이라 구역이 대체로 맞는다. 반면 아래 형식들은 **서식 배치가 제각각**
# 이라 구역이 맞을 근거가 없다.
#
# 그런데 이 형식들은 동시에 **신뢰도가 전 필드 1.0** 이다. 글자를 정확히 읽은
# 것이 맞으므로 옳은 값이지만, 그 결과 `LOW_CONFIDENCE` 판정이 원리적으로
# 발동하지 않는다. 즉 **가장 밀리기 쉬운 입력에서 신뢰도 신호가 죽어 있다.**
#
# `LABEL_ECHOED` 가 일부를 잡지만 전부는 아니다. 실측에서 `PLACE OF ISSUE` 의
# 값 `PUSAN` 이 `port_of_discharge` 로 꽂혔는데, 항목명이 섞이지 않아 세 검사를
# 모두 통과했다 — 핵심 필드에 틀린 값이 확인 없이 검증까지 흘러간 경우다.
_UNCALIBRATED_SOURCES = frozenset({"pdf-text", "excel", "email-body"})

# 값에 섞였을 때 오추출로 볼 항목명의 최소 길이.
#
# `FIELD_ANCHORS` 에는 "POL", "FROM" 같은 짧은 것도 있는데, 그런 조각은
# 정상 상호·항구명에도 흔히 들어가 오탐이 된다. 반대로 너무 길게 잡으면
# `VESSEL`(6자) 처럼 실제로 관측된 오추출을 놓친다.
#
# 오탐의 대가는 불필요한 확인 요청 한 건이고, 미탐의 대가는 **틀린 값이
# 확인 없이 검증까지 흘러가는 것**이다. 대가가 비대칭이므로 낮게 잡는다.
_MIN_LABEL_LENGTH = 6


@dataclass
class DraftField:
    """초안의 필드 하나."""

    name: str
    label: str
    value: Optional[str]
    confidence: Optional[float]
    is_critical: bool
    needs_review: bool
    # 신뢰도 등급 (기획안 v2 5.1). 화면의 표시 색과 후속 처리가 여기서 갈린다 —
    # 확정은 기본, 확인 권고는 노란색, 필수 확인은 적색 + 검증 실행 차단.
    grade: ConfidenceGrade = ConfidenceGrade.CONFIRMED
    review_reason: Optional[ReviewReason] = None
    review_message: Optional[str] = None
    # 이 값이 어떻게 나왔는지. "region" | "anchor" | "llm" | None(값 없음).
    #
    # 신뢰도만으로는 부족하다. 0.55 라는 숫자는 "좌표로 찾았는데 OCR 이
    # 흐릿했다"와 "LLM 이 원문을 보고 답했다"를 구분하지 못하는데, 사람이
    # 그 값을 확인하는 방법은 둘이 전혀 다르다. 앞은 원본 이미지의 그 자리를
    # 보면 되고, 뒤는 서류 전체에서 근거를 찾아야 한다.
    source: Optional[str] = None
    # 이 값의 근거 위치. [x0, y0, x1, y1], 이미지 가로/세로에 대한 0~1 비율.
    # 픽셀 좌표로 두면 이미지 해상도(스캔마다 다름)를 응답에 함께 실어야
    # 하는데, 비율로 두면 그럴 필요가 없다 — DB의 field_value.bbox_x1~y1
    # 컬럼도 같은 0~1 비율 관례를 쓴다.
    bbox: Optional[Tuple[float, float, float, float]] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "grade": self.grade.value,
            "grade_label": self.grade.label,
            "is_critical": self.is_critical,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason.value if self.review_reason else None,
            "review_message": self.review_message,
            "bbox": list(self.bbox) if self.bbox else None,
        }


@dataclass
class BLDraft:
    """사용자가 확인·수정할 B/L 초안."""

    image_id: str
    fields: List[DraftField] = field(default_factory=list)
    source: str = ""
    ocr_mean_confidence: float = 0.0
    processing_time_ms: Optional[int] = None
    # 서류 종류. 선하증권 / 상업송장 / 포장명세서 / 미상.
    #
    # 초안의 **형태는 종류와 무관하게 같다.** 필드 이름과 라벨만 달라진다.
    # 종류마다 다른 응답 구조를 내면 S3 편집기가 종류 수만큼 렌더러를
    # 갖게 되고, 종류를 추가할 때마다 화면도 함께 고쳐야 한다.
    form_type: str = "선하증권"

    # ── 조회 ──────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[DraftField]:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def review_fields(self) -> List[DraftField]:
        """확인이 필요한 필드. 핵심 필드를 앞에 둔다."""
        pending = [f for f in self.fields if f.needs_review]
        return sorted(pending, key=lambda f: (not f.is_critical, f.name))

    @property
    def review_required_fields(self) -> List[str]:
        """필수 확인 등급 필드 이름. F3 의 판정 보류 대상이다(5.3)."""
        return [
            f.name for f in self.fields
            if f.grade is ConfidenceGrade.REQUIRED
        ]

    @property
    def is_ready_for_verification(self) -> bool:
        """하자 검증(F3)을 돌릴 수 있는 상태인지.

        두 가지가 막는다.

        **핵심 필드 공백** — 검증 결과가 '값이 없어서 하자'로만 도배되어
        의미가 없다.

        **필수 확인 등급 필드** — 기획안 v2 5.1 이 "해당 필드 확인 전까지
        '검증 실행' 차단"으로 정했다. 값은 있지만 못 믿는 상태이므로 그대로
        검증하면 **틀린 값에 근거한 조문 인용**이 나가는데, 그건 위반 0건보다
        나쁘다 — 사용자가 그 인용을 믿고 서류를 그대로 제출한다.

        이 값이 False 여도 `/verify` 는 여전히 돌아간다. 차단은 화면(S3)의
        버튼이 하고, API 는 5.3 이 정한 대로 해당 룰을 판정 보류로 돌린다.
        게이트웨이가 이 값을 보고 버튼을 잠그라고 있는 자리다.
        """
        if any(f.is_critical and not f.value for f in self.fields):
            return False
        return not any(f.grade.blocks_verification for f in self.fields)

    def grade_counts(self) -> Dict[str, int]:
        """등급별 필드 수. 화면 상단의 '확인 필요 n건' 배지가 쓴다."""
        counts = {g.value: 0 for g in ConfidenceGrade}
        for f in self.fields:
            counts[f.grade.value] += 1
        return counts

    def hold_ratio(self) -> float:
        """필수 확인 필드 비율.

        기획안 v2 5.4 가 "판정 보류 항목이 많은 경우(전체 필드의 20% 초과)"로
        리포트의 확률 표기를 가르는 데 쓰는 값이다. **미검출은 세지 않는다** —
        5.3 이 판정 보류의 대상으로 "필수 확인 필드"만 지목했고, 값이 없는
        필드는 룰엔진이 `missing_field` 로 이미 하자에 반영하기 때문에 여기서
        또 세면 같은 사실이 확률을 두 번 흐린다.
        """
        if not self.fields:
            return 0.0
        return round(len(self.review_required_fields) / len(self.fields), 4)

    def completeness(self) -> float:
        """값이 채워진 필드 비율."""
        if not self.fields:
            return 0.0
        filled = sum(1 for f in self.fields if f.value)
        return round(filled / len(self.fields), 4)

    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "form_type": self.form_type,
            "source": self.source,
            "ocr_mean_confidence": round(self.ocr_mean_confidence, 4),
            "processing_time_ms": self.processing_time_ms,
            "completeness": self.completeness(),
            "is_ready_for_verification": self.is_ready_for_verification,
            "review_required_count": len(self.review_fields),
            "grades": self.grade_counts(),
            # 검증 실행을 막는 필드. 화면이 이 목록으로 바로가기를 그린다 —
            # "검증할 수 없습니다"만 띄우면 사용자는 어디를 고쳐야 하는지 모른다.
            "blocking_fields": self.review_required_fields,
            "hold_ratio": self.hold_ratio(),
            "fields": [f.to_dict() for f in self.fields],
        }


def _merge_bbox(
    bboxes: Optional[List[BBox]], image_width: int, image_height: int
) -> Optional[Tuple[float, float, float, float]]:
    """한 필드에 기여한 여러 bbox를 하나의 사각형(0~1 비율)으로 합친다.

    필드 하나가 여러 줄·여러 구역에서 값을 모아오는 경우(예: 화물 명세 +
    중량 구역을 합쳐 총중량을 뽑는 경우)가 있어, 개별 bbox 각각이 아니라
    전부를 감싸는 최소 사각형 하나로 표현한다.
    """
    if not bboxes or image_width <= 0 or image_height <= 0:
        return None
    x0 = min(b.x_min for b in bboxes) / image_width
    y0 = min(b.y_min for b in bboxes) / image_height
    x1 = max(b.x_max for b in bboxes) / image_width
    y1 = max(b.y_max for b in bboxes) / image_height
    return (
        round(max(0.0, min(1.0, x0)), 5),
        round(max(0.0, min(1.0, y0)), 5),
        round(max(0.0, min(1.0, x1)), 5),
        round(max(0.0, min(1.0, y1)), 5),
    )


def build_draft(
    fields: BLFields,
    ocr: Optional[OCRResult] = None,
    threshold: float = CONFIRMED_THRESHOLD,
) -> BLDraft:
    """추출 결과 → 초안.

    threshold 는 확정 등급의 하한이다(기획안 v2 5.1 의 0.90). 이 아래는 등급이
    확인 권고 또는 필수 확인으로 떨어지며 확인 대기열에 오른다. 스캔 품질이
    일정하게 나쁜 배치에서는 낮춰 잡아야 확인 큐가 실무적으로 감당 가능한
    크기가 된다.
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
        reason = _review_reason(
            name, value, confidence, fields, is_critical, threshold, draft.source
        )
        grade = grade_for(
            value, confidence, _GRADE_DEMOTION.get(reason),
            confirmed=threshold, required=min(REVIEW_REQUIRED_THRESHOLD, threshold),
        )
        bbox = _merge_bbox(
            fields.bbox.get(name), ocr.image_width if ocr else 0, ocr.image_height if ocr else 0
        )

        draft.fields.append(
            DraftField(
                name=name,
                label=FIELD_LABELS.get(name, name),
                value=value,
                confidence=confidence,
                source=fields.provenance.get(name),
                grade=grade,
                is_critical=is_critical,
                needs_review=grade is not ConfidenceGrade.CONFIRMED,
                review_reason=reason,
                review_message=_REASON_MESSAGES.get(reason) if reason else None,
                bbox=bbox,
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
    source: str = "",
) -> Optional[ReviewReason]:
    """확인이 필요한 이유. 필요 없으면 None."""
    # 문언·부기(bl_clauses)는 페이지 전체 원문이라 서식 항목명을 필연적으로
    # 포함한다 — 아래 LABEL_ECHOED 검사가 사실상 항상 발동한다. 확인 큐에
    # 긴 원문이 오르면 F1 의 시간 단축 효과가 사라지므로 이 필드는 항상
    # 확인 대상에서 제외한다.
    if name == "bl_clauses":
        return None
    if not value:
        return ReviewReason.MISSING_CRITICAL if is_critical else ReviewReason.MISSING

    # ── 매핑을 의심할 이유가 신뢰도보다 앞선다 ──────────────────
    #
    # 순서가 뒤집혀 있었다. 등급 경계가 0.90 이 되면서 앵커 감점(0.85)이 그
    # 아래로 떨어지는데, 신뢰도를 먼저 보면 **모든 앵커 값이 "인식 정확도가
    # 낮습니다"로 설명된다.** OCR 은 1.0 으로 확신했고 의심스러운 것은 매핑인데,
    # 그 메시지는 사용자에게 원본의 엉뚱한 곳을 보라고 시킨다.
    #
    # 사유는 "어디를 어떻게 확인해야 하는가"를 답하는 값이므로, 더 구체적인
    # 쪽이 이겨야 한다. 흐릿해서 못 믿는 것과 자리가 밀려서 못 믿는 것은
    # 확인 방법이 다르다.

    # 값에 서식의 항목명이 그대로 들어왔으면 구역 판정이 밀린 것이다.
    #
    # 이 검사가 필요한 이유는 신뢰도가 오추출을 못 잡기 때문이다. 텍스트
    # 레이어 PDF 는 전 필드가 신뢰도 1.0 인데 — 글자를 정확히 읽은 것은
    # 맞으므로 옳은 값이다 — *올바른 필드에 꽂혔는가* 는 다른 질문이다.
    # 그 결과 값이 밀려도 확인 대기열이 비어 사람이 아무것도 보지 않는다.
    # 입력이 정확할수록 검토가 사라지는 역설이라 별도 신호가 필요하다.
    if _echoes_label(value):
        return ReviewReason.LABEL_ECHOED

    # 앵커 추출은 OCR 신뢰도가 높아도 매핑이 틀렸을 수 있다.
    # 핵심 필드에 한해서만 확인을 요구한다 — 전 필드에 걸면
    # 확인 큐가 불어나 F1 의 시간 단축 효과가 사라진다.
    if is_critical and fields.provenance.get(name) == "anchor":
        return ReviewReason.ANCHOR_DERIVED

    # 구역 좌표를 보정하지 않은 형식에서 구역으로 잡힌 핵심 필드.
    #
    # 위 세 검사가 전부 통과해도 값이 틀릴 수 있다. 신뢰도는 1.0 으로 고정이고,
    # 항목명이 섞이지 않은 채 **옆 칸 값이 통째로 들어오는** 경우가 남는다.
    # 그런 값은 겉보기에 정상이라 사람이 보지 않으면 걸러지지 않는다.
    #
    # 핵심 필드로 한정하는 이유는 ANCHOR_DERIVED 와 같다 — 전 필드에 걸면
    # 확인 큐가 불어나 F1 의 시간 단축 효과가 사라진다. 5개면 화면에서
    # 훑을 만하고, 이 다섯이 틀리면 하자 검증 결과 전체가 무의미해진다.
    if is_critical and source in _UNCALIBRATED_SOURCES:
        return ReviewReason.UNCALIBRATED_LAYOUT

    if confidence is not None and confidence < threshold:
        return ReviewReason.LOW_CONFIDENCE

    return None


def _label_vocabulary() -> frozenset:
    """서식 항목명 어휘.

    앵커 목록이 곧 "서류에 인쇄된 항목명" 목록이므로 따로 관리하면 두
    목록이 어긋난다. 룰을 데이터로 두는 것과 같은 이유다.

    **선하증권 외 서류의 항목명도 함께 모은다.** 빠뜨리면 그 서류에서만
    검사가 헐거워진다 — 실제로 송장의 `INVOICE DATE` 가 값에 딸려 들어왔는데
    어휘에 없어 통과했다. 서류 종류가 늘 때마다 여기를 고쳐야 한다면 같은
    실수가 반복되므로, 명세에서 자동으로 끌어온다.
    """
    global _LABEL_VOCABULARY
    if _LABEL_VOCABULARY is None:
        from . import doc_types
        from .field_parser import FieldParser

        phrases = [
            phrase
            for group in FieldParser.FIELD_ANCHORS.values()
            for phrase in group
        ] + FieldParser.EXTRA_FORM_LABELS + [
            phrase
            for spec in doc_types.SPECS.values()
            for group in spec.anchors.values()
            for phrase in group
        ]
        _LABEL_VOCABULARY = frozenset(
            normalized
            for normalized in (_normalize(p) for p in phrases)
            if len(normalized) >= _MIN_LABEL_LENGTH
        )
    return _LABEL_VOCABULARY


_LABEL_VOCABULARY: Optional[frozenset] = None


def _normalize(text: str) -> str:
    """대문자·영숫자·공백만 남긴다. `B/L NO.` 와 `BL NO` 를 같게 본다."""
    return re.sub(r"[^A-Z0-9 ]", " ", text.upper()).strip()


def _echoes_label(value: str) -> bool:
    """값이 서식 항목명을 품고 있거나, 항목명의 조각인지.

    두 방향을 다 본다. 실제로 두 방향 모두 관측됐다 —
    `DESCRIPTION OF GOODS SAW MACHINE` 은 항목명을 품은 경우고,
    `OCEAN VESSEL` 라벨에서 잘려 나온 `OCEAN` 은 조각인 경우다.
    """
    normalized = re.sub(r"\s+", " ", _normalize(value))
    if not normalized:
        return False

    # "SAME AS CONSIGNEE" — 통지처 칸의 정상적인 값이고 실무에서 가장 흔한
    # 표기다. 항목명을 품고 있는 것은 맞지만 밀린 값이 아니므로, 이걸 걸면
    # 확인 대기열에 늘 한 건이 얹힌다.
    if re.match(r"^SAME AS \b", normalized):
        return False

    padded = f" {normalized} "
    for label in _label_vocabulary():
        if f" {label} " in padded:
            return True
        # 값 전체가 항목명의 일부인 경우. 값이 항목명보다 짧을 때만 본다 —
        # 정상 값이 항목명의 부분 문자열이 되는 일은 드물다.
        if len(normalized) < len(label) and f" {normalized} " in f" {label} ":
            return True
    return False


def build_document_draft(
    fields,
    ocr: Optional[OCRResult] = None,
    threshold: float = CONFIRMED_THRESHOLD,
) -> BLDraft:
    """선하증권 외 서류(`doc_parser.DocumentFields`) → 초안.

    `build_draft` 와 **같은 형태**를 낸다. 필드 이름·라벨·핵심 여부만 서류
    명세에서 가져온다. 형태를 맞추는 이유는 `BLDraft.form_type` 주석에 적었다.

    확인 사유 판정은 공유한다 — 누락, 저신뢰, 항목명 혼입은 서류 종류와
    무관한 실패 유형이다. 다만 **추출 방식 자체를 사유로 걸지는 않는다.**
    이 경로의 값은 앵커 아니면 LLM 이라, 방식을 사유로 삼으면 전건에 걸려
    신호가 되지 못한다. 대신 두 방식 모두 신뢰도가 깎여 있어
    (`ANCHOR_CONFIDENCE_PENALTY` · `LLM_CONFIDENCE`) 저신뢰 판정으로 이어진다.
    """
    spec = fields.spec
    draft = BLDraft(
        image_id=ocr.image_id if ocr else "",
        form_type=spec.name,
        source=ocr.source if ocr else "",
        ocr_mean_confidence=ocr.mean_confidence if ocr else 0.0,
        processing_time_ms=ocr.processing_time_ms if ocr else None,
    )

    for name in spec.fields:
        value = fields.get(name)
        confidence = fields.confidence.get(name)
        is_critical = name in spec.critical
        reason = _document_review_reason(value, confidence, is_critical, threshold)
        grade = grade_for(
            value, confidence, _GRADE_DEMOTION.get(reason),
            confirmed=threshold, required=min(REVIEW_REQUIRED_THRESHOLD, threshold),
        )
        bbox = _merge_bbox(
            fields.bbox.get(name), ocr.image_width if ocr else 0, ocr.image_height if ocr else 0
        )

        draft.fields.append(
            DraftField(
                name=name,
                label=spec.label_for(name),
                value=value,
                confidence=confidence,
                source=fields.provenance.get(name),
                grade=grade,
                is_critical=is_critical,
                needs_review=grade is not ConfidenceGrade.CONFIRMED,
                review_reason=reason,
                review_message=_REASON_MESSAGES.get(reason) if reason else None,
                bbox=bbox,
            )
        )

    return draft


def _document_review_reason(
    value: Optional[str],
    confidence: Optional[float],
    is_critical: bool,
    threshold: float,
) -> Optional[ReviewReason]:
    if not value:
        return ReviewReason.MISSING_CRITICAL if is_critical else ReviewReason.MISSING
    # 항목명 혼입이 신뢰도보다 앞선다 — `_review_reason` 과 같은 이유다.
    if _echoes_label(value):
        return ReviewReason.LABEL_ECHOED
    if confidence is not None and confidence < threshold:
        return ReviewReason.LOW_CONFIDENCE
    return None

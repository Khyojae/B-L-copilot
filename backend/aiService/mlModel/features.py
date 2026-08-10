"""
하자 예측 피처.

룰엔진 결과와 서류 자체의 상태를 수치 벡터로 만든다.

**룰 위반 여부를 피처로 쓰지 않는다.** 그러면 모델이 룰을 그대로 베끼게 되고,
룰이 이미 잡은 것만 잡아 존재 이유가 없어진다. 대신 룰이 못 보는 신호를 넣는다.

- 무엇을 검사하지 **못했는지** (평가불가 비율) — 룰은 여기서 침묵한다
- 필드가 얼마나 비었고 OCR 신뢰도가 얼마나 낮은지 — 하자의 선행 지표다
- 기한까지 며칠 남았는지 — 위반 전 단계의 위험을 본다

기획안 3.1 ④ 피드백 플라이휠이 실전 라벨을 쌓으면, 이 피처로 "룰은 통과했지만
은행이 하자로 잡은" 케이스를 학습하게 된다. 그게 룰엔진 위에 모델을 얹는 이유다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from ruleEngine.checks import field_value, parse_date
from ruleEngine.types import LCTerms, Severity, Verdict

# 피처 순서는 학습·추론에서 반드시 같아야 한다. XGBoost 는 위치로 읽는다.
FEATURE_NAMES: List[str] = [
    "critical_count",
    "warning_count",
    "info_count",
    "violation_weight_sum",
    "skipped_ratio",
    "evaluated_count",
    "field_missing_ratio",
    "critical_field_missing_count",
    "low_confidence_ratio",
    "mean_confidence",
    "anchor_derived_ratio",
    "days_to_shipment_deadline",
    "days_to_expiry",
    "lc_condition_count",
]

# 기한 정보가 없을 때 쓰는 값. 0 을 쓰면 '오늘이 마감'으로 읽혀
# 위험이 과대평가된다. 넉넉한 양수로 둔다.
NO_DEADLINE = 999.0


@dataclass
class FeatureVector:
    values: List[float]

    def as_dict(self) -> Dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values))

    def __len__(self) -> int:
        return len(self.values)


def extract_features(
    bl,
    lc: Optional[LCTerms],
    verdict: Verdict,
    as_of: Optional[datetime] = None,
) -> FeatureVector:
    """서류 1건 → 피처 벡터."""
    lc = lc or LCTerms()
    as_of = as_of or datetime.now()

    counts = verdict.counts
    total_rules = verdict.evaluated_count + len(verdict.skipped)

    values = [
        float(counts[Severity.CRITICAL.value]),
        float(counts[Severity.WARNING.value]),
        float(counts[Severity.INFO.value]),
        float(sum(v.weight for v in verdict.violations)),
        _ratio(len(verdict.skipped), total_rules),
        float(verdict.evaluated_count),
        _field_missing_ratio(bl),
        float(len(_missing_critical(bl))),
        _low_confidence_ratio(bl),
        _mean_confidence(bl),
        _anchor_ratio(bl),
        _days_until(lc.latest_shipment_date, as_of),
        _days_until(lc.expiry_date, as_of),
        float(_lc_condition_count(lc)),
    ]
    return FeatureVector(values=values)


# ── 개별 피처 ────────────────────────────────────────────────────

def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _bl_field_names(bl) -> List[str]:
    from ocr.types import BL_FIELD_NAMES

    return list(BL_FIELD_NAMES)


def _field_missing_ratio(bl) -> float:
    # field_value 를 쓴다. dict 가 들어왔을 때 getattr 로 읽으면 전 필드가
    # 누락으로 계산되어, 정상 서류가 최고 위험으로 분류된다.
    names = _bl_field_names(bl)
    missing = sum(1 for n in names if not field_value(bl, n))
    return _ratio(missing, len(names))


def _missing_critical(bl) -> List[str]:
    getter = getattr(bl, "missing_critical_fields", None)
    return getter() if callable(getter) else []


def _low_confidence_ratio(bl) -> float:
    """저신뢰 필드 비율. 신뢰도 정보가 없으면 0.

    아래 신뢰도 계열 피처는 dict 입력(S3 편집기에서 사람이 고친 값)에서
    기본값으로 떨어진다. 의도한 동작이다 — 사람이 확정한 값에는 OCR
    불확실성이 없으므로 '저신뢰 없음'이 맞다.
    """
    getter = getattr(bl, "low_confidence_fields", None)
    if not callable(getter):
        return 0.0
    names = _bl_field_names(bl)
    return _ratio(len(getter()), len(names))


def _mean_confidence(bl) -> float:
    """추출된 필드들의 평균 신뢰도.

    값이 있는 필드만 센다. 누락 필드까지 0 으로 넣으면 이 피처가
    field_missing_ratio 와 같은 것을 말하게 되어 중복이 된다.
    """
    confidence = getattr(bl, "confidence", None) or {}
    if not confidence:
        return 1.0
    return round(sum(confidence.values()) / len(confidence), 4)


def _anchor_ratio(bl) -> float:
    """앵커로 찾은 필드 비율. 레이아웃 가정에 기댄 값이 많을수록 불확실하다."""
    provenance = getattr(bl, "provenance", None) or {}
    if not provenance:
        return 0.0
    anchored = sum(1 for src in provenance.values() if src == "anchor")
    return _ratio(anchored, len(provenance))


def _days_until(date_str: Optional[str], as_of: datetime) -> float:
    """기한까지 남은 일수. 지났으면 음수."""
    if not date_str:
        return NO_DEADLINE
    parsed = parse_date(str(date_str))
    if parsed is None:
        return NO_DEADLINE
    return float((parsed - as_of).days)


def _lc_condition_count(lc: LCTerms) -> int:
    """L/C 에 명시된 조건 수.

    조건이 적으면 검사할 것도 적어 '하자 없음'이 쉽게 나온다. 모델이 그
    편향을 보정할 수 있도록 넣는다.
    """
    skip = {"lc_no", "partial_shipment", "transhipment", "currency",
            "tolerance_pct", "presentation_days"}
    count = 0
    for name in lc.__dataclass_fields__:
        if name in skip:
            continue
        value = getattr(lc, name, None)
        if value:
            count += 1
    return count

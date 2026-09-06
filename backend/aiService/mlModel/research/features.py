"""★ 피처 계약. 학습·추론 단일 진입점 (설계서 4절).

- `extract_features(snapshot, groups=ALL_GROUPS) -> dict[str, float]` 하나만 존재한다.
- 컬럼 순서는 FEATURE_SPECS 로 고정되고 `to_vector()` 만 벡터화를 수행한다.
- 결측은 0 이 아니라 NaN 이다(XGBoost 네이티브 결측 처리, 설계서 4절 원칙 4).
- 기획안 10.4의 "모델 단독" 조건 = Group 1(RULE_VIOLATION) 제외, 74 → 44 피처
  (fs-2, HANDOFF.md 3단계).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from f3_research.schema import ShipmentSnapshot

FEATURE_SCHEMA_VERSION = "fs-2"

NAN = float("nan")

# ---------------------------------------------------------------------------
# 룰 카탈로그 — 실제 룰엔진(`ruleEngine/rules.yaml`)의 21개 D-코드에서 유도한다
# (fs-2, HANDOFF.md 3단계). fs-1 의 UCP600_xx/LC_COND_xx/DOC_MATCH_xx 자리표시자
# 40개는 폐기됐다 — 실제 룰엔진이 생겼으므로 더 이상 가짜 카탈로그를 흉내낼
# 이유가 없다.
#
# YAML 을 import 시점에 읽는 것은 알려진 위험이다(HANDOFF.md R2: rules.yaml
# 이 바뀌면 rv_<code> 컬럼의 의미가 조용히 달라진다). 두 방어선을 둔다:
#   1. `_rule_catalog_ids()` 를 메모이즈해 반복 로드를 피한다.
#   2. 로드 결과를 동결 리터럴과 대조한다 — 카탈로그가 바뀌면 여기서 즉시
#      AssertionError 로 죽는다(테스트 수집 단계에서부터).
# ---------------------------------------------------------------------------

_FROZEN_RULE_CODES: tuple[str, ...] = (
    "D001",
    "D002",
    "D003",
    "D004",
    "D005",
    "D005B",
    "D006",
    "D007",
    "D007B",
    "D008",
    "D009",
    "D010",
    "D011",
    "D012",
    "D012B",
    "D013",
    "D014",
    "D015",
    "D016",
    "D017",
    "D018",
)


@lru_cache(maxsize=1)
def _rule_catalog_ids() -> tuple[str, ...]:
    from f3_research.ruleEngine.engine import load_catalog

    _, rules = load_catalog()
    return tuple(sorted(rule["id"] for rule in rules))


RULE_CODES: tuple[str, ...] = _rule_catalog_ids()
assert RULE_CODES == _FROZEN_RULE_CODES, (
    "rules.yaml 변경 — FEATURE_SCHEMA_VERSION 을 올리세요 "
    f"(카탈로그: {RULE_CODES}, 동결 리터럴: {_FROZEN_RULE_CODES})"
)

SEVERITY_WEIGHT = {"CRITICAL": 3, "WARNING": 2, "INFO": 1}

# eval_report_merged.json 의 field_accuracy_by_field 키와 맞춘 추출 품질 체크 필드.
EXTRACTION_CHECKED_FIELDS: tuple[str, ...] = (
    "bl_no",
    "shipper",
    "consignee",
    "port_of_loading",
    "port_of_discharge",
    "date_of_issue",
    "gross_weight",
)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    missing_policy: str  # 사람이 읽는 설명. NaN 인코딩 여부는 dtype 로 판단.


def _rv_specs() -> list[FeatureSpec]:
    specs = [
        FeatureSpec(f"rv_{code}", "RULE_VIOLATION", "NaN (판정불가/미평가)")
        for code in RULE_CODES
    ]
    specs += [
        FeatureSpec("rv_critical_count", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_warning_count", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_info_count", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_severity_weighted_sum", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_weight_sum", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_distinct_field_count", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_any_critical", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_skipped_count", "RULE_VIOLATION", "0"),
        FeatureSpec("rv_skipped_critical_count", "RULE_VIOLATION", "0"),
    ]
    return specs


def _dc_specs() -> list[FeatureSpec]:
    names = [
        "dc_max_edit_distance_ratio",
        "dc_mean_edit_distance_ratio",
        "dc_qty_deviation_ratio",
        "dc_weight_deviation_ratio",
        "dc_amount_deviation_ratio",
        "dc_conflict_field_count",
        "dc_party_name_mismatch_count",
    ]
    return [FeatureSpec(n, "DOC_CONSISTENCY", "NaN (비교 대상 없음)") for n in names]


def _eq_specs() -> list[FeatureSpec]:
    names = [
        "eq_mean_confidence",
        "eq_min_confidence",
        "eq_required_check_count",
        "eq_recommend_check_count",
        "eq_missing_field_count",
        "eq_no_evidence_ratio",
        "eq_src_text_pdf",
        "eq_src_scan",
        "eq_src_json",
        "eq_src_manual",
    ]
    return [FeatureSpec(n, "EXTRACTION_QUALITY", "0/NaN") for n in names]


def _lc_specs() -> list[FeatureSpec]:
    names = [
        "lc_required_doc_count",
        "lc_47a_char_length",
        "lc_47a_condition_count",
        "lc_has_special_clause",
        "lc_is_transferable",
        "lc_partial_shipment_allowed",
        "lc_transshipment_allowed",
        "lc_amount_tolerance_pct",
        "lc_absent",
    ]
    return [FeatureSpec(n, "LC_COMPLEXITY", "NaN if lc_absent") for n in names]


def _tm_specs() -> list[FeatureSpec]:
    names = [
        "tm_days_to_expiry",
        "tm_days_onboard_to_presentation",
        "tm_presentation_period_remaining_ratio",
        "tm_days_issue_to_onboard",
        "tm_is_over_21d",
    ]
    return [FeatureSpec(n, "TIME_MARGIN", "NaN (날짜 결측)") for n in names]


def _hist_specs() -> list[FeatureSpec]:
    names = [
        "hist_counterparty_defect_rate",
        "hist_bank_defect_rate",
        "hist_cargo_type_defect_rate",
        "hist_counterparty_shipment_count",
        "hist_is_cold_start",
    ]
    return [FeatureSpec(n, "HISTORY", "NaN if cold start") for n in names]


def _llm_specs() -> list[FeatureSpec]:
    names = [
        "llm_47a_verifiable_ratio",
        "llm_47a_unverifiable_count",
        "llm_goods_semantic_equiv",
        "llm_goods_invoice_semantic_equiv",
        "llm_party_semantic_equiv_min",
        "llm_doc_conflict_count",
        "llm_lc_complexity_score",
        "llm_available",
    ]
    policy = "NaN if snapshot.llm is None (llm_available 예외: 항상 0.0/1.0)"
    return [FeatureSpec(n, "LLM_SEMANTIC", policy) for n in names]


FEATURE_SPECS: tuple[FeatureSpec, ...] = tuple(
    _rv_specs()
    + _dc_specs()
    + _eq_specs()
    + _lc_specs()
    + _tm_specs()
    + _hist_specs()
    + _llm_specs()
)
assert len(FEATURE_SPECS) == 74, f"74 피처 계약 위반(fs-2): {len(FEATURE_SPECS)}"

FEATURE_NAMES: tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS)
FEATURE_GROUP_BY_NAME: dict[str, str] = {s.name: s.group for s in FEATURE_SPECS}

ALL_GROUPS: tuple[str, ...] = (
    "RULE_VIOLATION",
    "DOC_CONSISTENCY",
    "EXTRACTION_QUALITY",
    "LC_COMPLEXITY",
    "TIME_MARGIN",
    "HISTORY",
    "LLM_SEMANTIC",
)
# 기획안 10.4 "모델 단독" 조건 (74 → 44) — 룰 피처 제외, LLM 은 포함.
MODEL_ONLY_GROUPS: tuple[str, ...] = tuple(g for g in ALL_GROUPS if g != "RULE_VIOLATION")
# LLM 투자 정당화 비교용(HANDOFF.md 핵심 설계 결정 A) — LLM 피처 제외, 룰은 포함.
NO_LLM_GROUPS: tuple[str, ...] = tuple(g for g in ALL_GROUPS if g != "LLM_SEMANTIC")
# 둘 다 제외 — 룰도 LLM 도 없는 "순수 서류 정합성" 조건.
MODEL_ONLY_NO_LLM_GROUPS: tuple[str, ...] = tuple(
    g for g in ALL_GROUPS if g not in ("RULE_VIOLATION", "LLM_SEMANTIC")
)


def _levenshtein_ratio(a: str, b: str) -> float:
    """정규화 편집거리 비율 = distance / max(len). 순수 파이썬 구현(외부 의존 없음)."""
    if a == b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 1.0
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[lb]
    return dist / max(la, lb)


def _deviation_ratio(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return NAN
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def _rv_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    """Group 1 (fs-2, 30 피처): 룰 카탈로그의 삼진 판정을 인코딩한다.

    `rv_<code>` 는 위반이면 1.0, "평가했고 통과"면 0.0, "평가 못함"이면 NaN 이다
    — fs-1 의 "0.0=미발화"와 의미가 다르다(HANDOFF.md 4절 "의미 변경 주의").
    "평가했고 통과" 집합은 카탈로그 전체에서 위반·스킵 집합을 뺀 나머지로
    암묵 계산한다(`RuleEngineOutcome` docstring 참고).

    `rv_any_critical` 은 이름이 코드 안팎(train.py 룰 단독 베이스라인,
    dataset.leakage_diagnostics)에 하드코딩돼 있다 — 바꾸지 않는다.
    """
    outcome = snapshot.rule_outcome

    fired_codes: dict[str, float] = {}
    fields: set[str] = set()
    critical = warning = info = 0
    severity_weighted_sum = 0.0
    weight_sum = 0.0  # 비클리핑 — Verdict.defect_probability(1.0 클리핑)는 쓰지 않는다.

    for firing in outcome.firings:
        fired_codes[firing.rule_code] = 1.0
        if firing.severity == "CRITICAL":
            critical += 1
        elif firing.severity == "WARNING":
            warning += 1
        else:
            info += 1
        # 매핑에 없는 심각도를 조용히 0점 처리하지 않는다(SEVERITY_WEIGHT.get(.., 0)
        # 패턴 금지) — 인덱싱 자체가 계약이다. rule_adapter.py 의 SEVERITY_MAP 이
        # ruleEngine.Severity 전 항목을 커버하므로 여기 도달하는 값은 항상 유효하다.
        severity_weighted_sum += SEVERITY_WEIGHT[firing.severity]
        weight_sum += firing.weight
        fields.update(firing.field_codes)

    skipped_codes = {s.rule_code for s in outcome.skipped}
    skipped_critical_count = sum(
        1 for s in outcome.skipped if s.catalog_severity == "CRITICAL"
    )

    out: dict[str, float] = {}
    for code in RULE_CODES:
        if code in fired_codes:
            out[f"rv_{code}"] = 1.0
        elif code in skipped_codes:
            out[f"rv_{code}"] = NAN
        else:
            out[f"rv_{code}"] = 0.0  # 평가했고 통과

    out["rv_critical_count"] = float(critical)
    out["rv_warning_count"] = float(warning)
    out["rv_info_count"] = float(info)
    out["rv_severity_weighted_sum"] = float(severity_weighted_sum)
    out["rv_weight_sum"] = float(weight_sum)
    out["rv_distinct_field_count"] = float(len(fields))
    out["rv_any_critical"] = 1.0 if critical > 0 else 0.0
    out["rv_skipped_count"] = float(len(outcome.skipped))
    out["rv_skipped_critical_count"] = float(skipped_critical_count)
    return out


def _dc_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    dc = snapshot.doc_consistency
    ratios = []
    mismatch_count = 0
    for _name, a, b in dc.party_name_pairs:
        if a is None or b is None:
            continue
        ratio = _levenshtein_ratio(a.strip().upper(), b.strip().upper())
        ratios.append(ratio)
        if ratio > 0.15:
            mismatch_count += 1
    return {
        "dc_max_edit_distance_ratio": max(ratios) if ratios else NAN,
        "dc_mean_edit_distance_ratio": (sum(ratios) / len(ratios)) if ratios else NAN,
        "dc_qty_deviation_ratio": _deviation_ratio(dc.bl_qty, dc.packing_qty_sum),
        "dc_weight_deviation_ratio": _deviation_ratio(dc.bl_weight, dc.packing_weight_sum),
        "dc_amount_deviation_ratio": _deviation_ratio(dc.invoice_amount, dc.computed_amount),
        "dc_conflict_field_count": float(dc.conflict_field_count),
        "dc_party_name_mismatch_count": float(mismatch_count),
    }


def _eq_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    eq = snapshot.extraction_quality
    confidences = list(eq.field_confidences.values())
    required = sum(1 for c in confidences if c < 0.70)
    recommend = sum(1 for c in confidences if 0.70 <= c < 0.90)
    checked = eq.checked_field_count or len(EXTRACTION_CHECKED_FIELDS)
    no_evidence_ratio = (len(eq.no_evidence_fields) / checked) if checked else NAN
    return {
        "eq_mean_confidence": (sum(confidences) / len(confidences)) if confidences else NAN,
        "eq_min_confidence": min(confidences) if confidences else NAN,
        "eq_required_check_count": float(required),
        "eq_recommend_check_count": float(recommend),
        "eq_missing_field_count": float(len(eq.missing_fields)),
        "eq_no_evidence_ratio": no_evidence_ratio,
        "eq_src_text_pdf": 1.0 if eq.source == "pdf" else 0.0,
        "eq_src_scan": 1.0 if eq.source == "scan" else 0.0,
        "eq_src_json": 1.0 if eq.source == "json" else 0.0,
        "eq_src_manual": 1.0 if eq.source == "manual" else 0.0,
    }


def _lc_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    lc = snapshot.lc
    if lc is None:
        return {
            "lc_required_doc_count": NAN,
            "lc_47a_char_length": NAN,
            "lc_47a_condition_count": NAN,
            "lc_has_special_clause": NAN,
            "lc_is_transferable": NAN,
            "lc_partial_shipment_allowed": NAN,
            "lc_transshipment_allowed": NAN,
            "lc_amount_tolerance_pct": NAN,
            "lc_absent": 1.0,
        }
    condition_count = len([c for c in lc.field_47a_text.split(";") if c.strip()])
    return {
        "lc_required_doc_count": (
            float(lc.required_doc_count) if lc.required_doc_count is not None else NAN
        ),
        "lc_47a_char_length": float(len(lc.field_47a_text)),
        "lc_47a_condition_count": float(condition_count),
        "lc_has_special_clause": 1.0 if lc.has_special_clause else 0.0,
        "lc_is_transferable": 1.0 if lc.is_transferable else 0.0,
        "lc_partial_shipment_allowed": 1.0 if lc.partial_shipment_allowed else 0.0,
        "lc_transshipment_allowed": 1.0 if lc.transshipment_allowed else 0.0,
        "lc_amount_tolerance_pct": float(lc.amount_tolerance_pct),
        "lc_absent": 0.0,
    }


def _tm_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    d = snapshot.dates

    def days(a, b) -> float:
        if a is None or b is None:
            return NAN
        return float((a - b).days)

    # tm_days_to_expiry: 선적(onboard) 시점 기준 LC 만료까지 남은 여유일.
    # "오늘" 기준으로 두면 재현성이 깨지므로(생성 시점마다 값이 바뀜) onboard_date
    # 를 기준점으로 고정한다 — 설계서 4절 원칙 4의 "tm_days_to_expiry=0(오늘 만료)"
    # 예시는 실전 추론(예측 시점=오늘) 맥락이고, 합성 데이터는 선적 완결 시점 기준으로
    # 동일한 의미(만료까지 남은 날)를 재현한다.
    days_to_expiry = days(d.lc_expiry_date, d.onboard_date)
    days_onboard_to_presentation = days(d.presentation_date, d.onboard_date)
    days_issue_to_onboard = days(d.onboard_date, d.bl_issue_date)

    remaining_ratio = NAN
    if d.presentation_period_days and not math.isnan(days_onboard_to_presentation):
        remaining_ratio = (
            d.presentation_period_days - days_onboard_to_presentation
        ) / d.presentation_period_days

    is_over_21d = NAN
    if not math.isnan(days_onboard_to_presentation):
        is_over_21d = 1.0 if days_onboard_to_presentation > 21 else 0.0

    return {
        "tm_days_to_expiry": days_to_expiry,
        "tm_days_onboard_to_presentation": days_onboard_to_presentation,
        "tm_presentation_period_remaining_ratio": remaining_ratio,
        "tm_days_issue_to_onboard": days_issue_to_onboard,
        "tm_is_over_21d": is_over_21d,
    }


def _hist_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    h = snapshot.history
    cold_start = h.counterparty_shipment_count == 0
    return {
        "hist_counterparty_defect_rate": (
            NAN if cold_start or h.counterparty_defect_rate is None
            else float(h.counterparty_defect_rate)
        ),
        "hist_bank_defect_rate": (
            NAN if cold_start or h.bank_defect_rate is None else float(h.bank_defect_rate)
        ),
        "hist_cargo_type_defect_rate": (
            NAN if cold_start or h.cargo_type_defect_rate is None
            else float(h.cargo_type_defect_rate)
        ),
        "hist_counterparty_shipment_count": float(h.counterparty_shipment_count),
        "hist_is_cold_start": 1.0 if cold_start else 0.0,
    }


def _llm_features(snapshot: ShipmentSnapshot) -> dict[str, float]:
    """Group 7 (fs-2, 8 피처, 신규): Gemini 의미론적 피처.

    `snapshot.llm is None`(LLM 미사용/실패, HANDOFF.md 12절 2번)이면 전부 NaN,
    단 `llm_available` 만은 0.0 — 이 피처는 절대 NaN 이 되면 안 된다(모델이
    "LLM 을 신뢰할 수 있는가" 자체를 학습할 유일한 신호이기 때문).
    """
    llm = snapshot.llm
    if llm is None:
        return {
            "llm_47a_verifiable_ratio": NAN,
            "llm_47a_unverifiable_count": NAN,
            "llm_goods_semantic_equiv": NAN,
            "llm_goods_invoice_semantic_equiv": NAN,
            "llm_party_semantic_equiv_min": NAN,
            "llm_doc_conflict_count": NAN,
            "llm_lc_complexity_score": NAN,
            "llm_available": 0.0,
        }

    def _f(v: float | int | None) -> float:
        return NAN if v is None else float(v)

    return {
        "llm_47a_verifiable_ratio": _f(llm.verifiable_47a_ratio),
        "llm_47a_unverifiable_count": _f(llm.unverifiable_47a_count),
        "llm_goods_semantic_equiv": _f(llm.goods_semantic_equiv),
        "llm_goods_invoice_semantic_equiv": _f(llm.goods_invoice_semantic_equiv),
        "llm_party_semantic_equiv_min": _f(llm.party_semantic_equiv_min),
        "llm_doc_conflict_count": _f(llm.doc_conflict_count),
        "llm_lc_complexity_score": _f(llm.lc_complexity_score),
        "llm_available": 1.0,
    }


_GROUP_EXTRACTORS = {
    "RULE_VIOLATION": _rv_features,
    "DOC_CONSISTENCY": _dc_features,
    "EXTRACTION_QUALITY": _eq_features,
    "LC_COMPLEXITY": _lc_features,
    "TIME_MARGIN": _tm_features,
    "HISTORY": _hist_features,
    "LLM_SEMANTIC": _llm_features,
}


def extract_features(
    snapshot: ShipmentSnapshot, groups: tuple[str, ...] = ALL_GROUPS
) -> dict[str, float]:
    """설계서 4절 원칙 1: 학습과 추론이 공유하는 유일한 피처 함수.

    groups 로 피처군을 선택할 수 있다 (기획안 10.4 "모델 단독" = MODEL_ONLY_GROUPS).
    선택되지 않은 그룹의 피처는 결과 dict 에 아예 포함하지 않는다 — to_vector() 가
    FEATURE_SPECS 순서로 채울 때 없는 키는 NaN 으로 채운다.
    """
    out: dict[str, float] = {}
    for group in groups:
        out.update(_GROUP_EXTRACTORS[group](snapshot))
    return out


def to_vector(features: dict[str, float]) -> list[float]:
    """FEATURE_SPECS 순서로 고정 벡터화. 없는 피처는 NaN(결측)으로 채운다."""
    return [features.get(spec.name, NAN) for spec in FEATURE_SPECS]


def feature_group(name: str) -> str | None:
    """prediction_factor.feature_group 조회용 — explain.py 가 하드코딩하지 않도록."""
    return FEATURE_GROUP_BY_NAME.get(name)

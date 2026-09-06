"""features.py 피처 계약 테스트 (설계서 4절, fs-2 HANDOFF.md 3단계)."""

from __future__ import annotations

import dataclasses
import math

from f3_research.features import (
    ALL_GROUPS,
    FEATURE_SPECS,
    MODEL_ONLY_GROUPS,
    MODEL_ONLY_NO_LLM_GROUPS,
    NO_LLM_GROUPS,
    extract_features,
    to_vector,
)
from f3_research.schema import (
    DocConsistencyInputs,
    ExtractionQualityInputs,
    HistoryStats,
    LCTerms,
    RuleEngineOutcome,
    RuleFiring,
    ShipmentDates,
    ShipmentSnapshot,
)


def _empty_outcome() -> RuleEngineOutcome:
    return RuleEngineOutcome(firings=(), skipped=(), catalog_version="test")


def _empty_snapshot() -> ShipmentSnapshot:
    return ShipmentSnapshot(
        shipment_id="T1",
        base_shipment_id="B1",
        rule_outcome=_empty_outcome(),
        doc_consistency=DocConsistencyInputs(),
        extraction_quality=ExtractionQualityInputs(),
        lc=None,
        dates=ShipmentDates(),
        history=HistoryStats(),
    )


def test_feature_contract_has_74_features() -> None:
    assert len(FEATURE_SPECS) == 74


def test_group_constant_sizes_stay_in_sync() -> None:
    """fs-2 그룹 상수 4개(74/44/66/36)가 서로 어긋나지 않는지 고정한다.

    이후 어느 그룹의 피처 수가 바뀌어도 이 테스트가 먼저 죽어야 한다 —
    MODEL_ONLY/NO_LLM/MODEL_ONLY_NO_LLM 이 개별적으로 재계산되므로 조용히
    엇나갈 수 있다.
    """
    assert len(FEATURE_SPECS) == 74
    assert len([s for s in FEATURE_SPECS if s.group in MODEL_ONLY_GROUPS]) == 44
    assert len([s for s in FEATURE_SPECS if s.group in NO_LLM_GROUPS]) == 66
    assert len([s for s in FEATURE_SPECS if s.group in MODEL_ONLY_NO_LLM_GROUPS]) == 36


def test_model_only_groups_exclude_rule_violation_and_total_44() -> None:
    assert "RULE_VIOLATION" not in MODEL_ONLY_GROUPS
    names = [s.name for s in FEATURE_SPECS if s.group in MODEL_ONLY_GROUPS]
    assert len(names) == 44


def test_no_llm_groups_exclude_llm_semantic_and_total_66() -> None:
    assert "LLM_SEMANTIC" not in NO_LLM_GROUPS
    names = [s.name for s in FEATURE_SPECS if s.group in NO_LLM_GROUPS]
    assert len(names) == 66


def test_model_only_no_llm_groups_exclude_both_and_total_36() -> None:
    assert "RULE_VIOLATION" not in MODEL_ONLY_NO_LLM_GROUPS
    assert "LLM_SEMANTIC" not in MODEL_ONLY_NO_LLM_GROUPS
    names = [s.name for s in FEATURE_SPECS if s.group in MODEL_ONLY_NO_LLM_GROUPS]
    assert len(names) == 36


def test_extract_features_missing_values_are_nan_not_zero() -> None:
    snapshot = _empty_snapshot()
    feats = extract_features(snapshot)
    # L/C 없음 → lc_absent=1, 나머지 8개는 NaN(0 이 아니다).
    assert feats["lc_absent"] == 1.0
    assert math.isnan(feats["lc_required_doc_count"])
    assert math.isnan(feats["lc_47a_char_length"])
    # 날짜가 전혀 없으므로 TIME_MARGIN 은 전부 NaN.
    assert math.isnan(feats["tm_days_to_expiry"])
    # 콜드스타트 → 이력 비율은 NaN, count 는 0.
    assert feats["hist_is_cold_start"] == 1.0
    assert math.isnan(feats["hist_counterparty_defect_rate"])
    assert feats["hist_counterparty_shipment_count"] == 0.0
    # LLM 없음 → llm_available=0.0(NaN 아님), 나머지는 전부 NaN.
    assert feats["llm_available"] == 0.0
    assert math.isnan(feats["llm_goods_semantic_equiv"])
    assert math.isnan(feats["llm_47a_verifiable_ratio"])


def test_rule_violation_features_zero_when_no_firings() -> None:
    feats = extract_features(_empty_snapshot())
    assert feats["rv_any_critical"] == 0.0
    assert feats["rv_critical_count"] == 0.0
    # 평가했고 통과(발화도 스킵도 아님) → 0.0, NaN 아니다.
    assert feats["rv_D001"] == 0.0
    assert feats["rv_skipped_count"] == 0.0
    assert feats["rv_skipped_critical_count"] == 0.0
    assert feats["rv_weight_sum"] == 0.0


def test_rule_violation_aggregates_from_firings() -> None:
    outcome = RuleEngineOutcome(
        firings=(
            RuleFiring("D001", "CRITICAL", ("bl_no",), weight=0.30),
            RuleFiring("D009", "WARNING", ("shipper",), weight=0.10),
        ),
        skipped=(),
        catalog_version="test",
    )
    snapshot = dataclasses.replace(_empty_snapshot(), rule_outcome=outcome)
    feats = extract_features(snapshot)
    assert feats["rv_D001"] == 1.0
    assert feats["rv_D009"] == 1.0
    assert feats["rv_any_critical"] == 1.0
    assert feats["rv_critical_count"] == 1.0
    assert feats["rv_warning_count"] == 1.0
    assert feats["rv_distinct_field_count"] == 2.0
    assert feats["rv_severity_weighted_sum"] == 3.0 + 2.0
    assert feats["rv_weight_sum"] == 0.30 + 0.10
    # 발화하지도 스킵되지도 않은 나머지 룰은 "평가했고 통과" = 0.0.
    assert feats["rv_D018"] == 0.0


def test_rule_violation_skipped_rules_are_nan_not_zero() -> None:
    """fs-2 핵심 의미 변경: 판정불가는 0.0(미발화)이 아니라 NaN 이다."""
    from f3_research.schema import SkippedRule

    outcome = RuleEngineOutcome(
        firings=(),
        skipped=(
            SkippedRule("D002", "CRITICAL", "latest_shipment_date 없음"),
            SkippedRule("D007B", "WARNING", "measurement 없음"),
        ),
        catalog_version="test",
    )
    snapshot = dataclasses.replace(_empty_snapshot(), rule_outcome=outcome)
    feats = extract_features(snapshot)
    assert math.isnan(feats["rv_D002"])
    assert math.isnan(feats["rv_D007B"])
    assert feats["rv_skipped_count"] == 2.0
    assert feats["rv_skipped_critical_count"] == 1.0
    # 스킵된 룰은 위반이 아니므로 rv_any_critical 에 반영되지 않는다.
    assert feats["rv_any_critical"] == 0.0


def test_groups_switch_excludes_unrequested_groups() -> None:
    snapshot = _empty_snapshot()
    feats = extract_features(snapshot, groups=MODEL_ONLY_GROUPS)
    assert not any(k.startswith("rv_") for k in feats)
    vector = to_vector(feats)
    assert len(vector) == 74
    # RULE_VIOLATION 컬럼은 요청하지 않았으므로 NaN 으로 채워진다.
    rv_positions = [i for i, s in enumerate(FEATURE_SPECS) if s.group == "RULE_VIOLATION"]
    assert all(math.isnan(vector[i]) for i in rv_positions)


def test_to_vector_follows_feature_specs_order() -> None:
    feats = {s.name: float(i) for i, s in enumerate(FEATURE_SPECS)}
    vector = to_vector(feats)
    assert vector == [float(i) for i in range(len(FEATURE_SPECS))]


def test_lc_present_gives_numeric_group4() -> None:
    snapshot = ShipmentSnapshot(
        shipment_id="T2",
        base_shipment_id="B2",
        rule_outcome=_empty_outcome(),
        doc_consistency=DocConsistencyInputs(),
        extraction_quality=ExtractionQualityInputs(),
        lc=LCTerms(required_doc_count=4, field_47a_text="A;B;C"),
        dates=ShipmentDates(),
        history=HistoryStats(),
    )
    feats = extract_features(snapshot)
    assert feats["lc_absent"] == 0.0
    assert feats["lc_required_doc_count"] == 4.0
    assert feats["lc_47a_condition_count"] == 3.0


def test_llm_available_when_llm_present() -> None:
    from f3_research.schema import LLMFeatures

    llm = LLMFeatures(
        verifiable_47a_ratio=0.5,
        unverifiable_47a_count=1,
        goods_semantic_equiv=0.9,
        goods_invoice_semantic_equiv=0.8,
        party_semantic_equiv_min=0.7,
        doc_conflict_count=0,
        lc_complexity_score=0.3,
    )
    snapshot = dataclasses.replace(_empty_snapshot(), llm=llm)
    feats = extract_features(snapshot)
    assert feats["llm_available"] == 1.0
    assert feats["llm_goods_semantic_equiv"] == 0.9
    assert feats["llm_47a_unverifiable_count"] == 1.0


def test_all_groups_constant_matches_feature_specs_groups() -> None:
    spec_groups = {s.group for s in FEATURE_SPECS}
    assert spec_groups == set(ALL_GROUPS)

"""인젝터 ↔ 실제 룰엔진 정렬 검증 (HANDOFF.md 4b단계 Task 4).

v3까지 `COVERED_SPECS` 는 가상의 40코드 룰 벡터를 전제로 작성돼, 실제 21룰 엔진에는
대부분 발화하지 않았다(HANDOFF.md 4b단계 진단: `phi(y, rv_any_critical)` 0.074,
10/21 룰 무발화). 이 파일은 그 재발을 막는다 — `COVERED_SPECS` 각 항목이 실제로
`target_rule` 을 발화시키는지, `UNCOVERED_SPECS` 각 항목이 정말로 어떤 룰도
발화시키지 않는지를 개별 assert 로 검증한다. `DefectSpec.target_rule` 이 그
매핑을 데이터로 고정하므로, 새 covered spec 을 추가하고 target_rule 을 빼먹으면
이 파일의 파라미터화 테스트가 즉시 실패한다.

관측 노이즈(`synth/extraction_view.py`)를 거치지 않고 **진실**(주입 직후의
`SynthShipment`) 을 곧바로 `rule_adapter.evaluate_shipment` 에 태운다 — 노이즈가
섞이면 "이 하자가 이 룰을 발화시키는가"라는 질문 자체가 흐려진다(HANDOFF.md 5단계
관측 노이즈는 채널 A 의 실전 동작이지, 인젝터 정렬 자체의 검증 대상이 아니다).
"""

from __future__ import annotations

import random
from datetime import date

import pytest

from f3_research import rule_adapter
from f3_research.ruleEngine.engine import RuleEngine
from f3_research.synth import injector
from f3_research.synth.generator import SynthShipment

# 시행 횟수 — required_field_missing 처럼 매 호출마다 무작위로 필드를 고르는
# spec 도 있으므로, 시드를 바꿔가며 여러 번 시도해 "요행이 아니라 실제로
# 발화하는지"를 확인한다(대부분의 spec 은 1회로도 결정론적으로 발화한다).
_TRIALS = 10


def _clean_shipment(**overrides) -> SynthShipment:
    """모든 필드가 채워진 정합성 완전 선적 하나(`tests/test_rule_adapter.py::_make_shipment`
    와 동일한 계약 — EQ/SUM/DERIVE 제약 만족). 이 파일은 injector.py 정렬만
    검증하므로 독립적으로 둔다(다른 테스트 파일의 내부 헬퍼에 의존하지 않는다)."""
    base = dict(
        base_shipment_id="S00000",
        shipment_id="S00000",
        counterparty_id="CP0000",
        bank_id="BANK000",
        bank_strictness=1.0,
        counterparty_propensity=1.0,
        cargo_type="ELECTRONICS",
        cargo_type_propensity=1.0,
        bl_no="BLKR1234567",
        shipper="ACME SHIPPER CO., LTD.",
        consignee="ACME CONSIGNEE CO., LTD.",
        invoice_consignee="ACME CONSIGNEE CO., LTD.",
        notify_party="ACME NOTIFY CO., LTD.",
        lc_consignee="ACME CONSIGNEE CO., LTD.",
        port_of_loading="BUSAN, KOREA",
        port_of_discharge="LOS ANGELES, USA",
        lc_port_of_discharge="LOS ANGELES, USA",
        lc_port_of_loading="BUSAN, KOREA",
        vessel="OCEAN STAR",
        voyage_no="001",
        goods_description="GENERAL CARGO",
        invoice_goods_description="GENERAL CARGO",
        lc_goods_description="GENERAL CARGO",
        package_qty=100,
        packing_list_qty_sum=100,
        gross_weight_kg=500.0,
        packing_list_weight_sum=500.0,
        measurement_cbm=12.5,
        unit_price_usd=10.0,
        invoice_amount_usd=1000.0,
        freight_amount_usd=1200.0,
        original_bl_count=3,
        required_original_count=3,
        admin_note_conflict=False,
        lc_present=True,
        lc_required_doc_count=5,
        lc_documents_required=["BILL OF LADING", "COMMERCIAL INVOICE", "PACKING LIST"],
        lc_47a_text="",
        lc_has_special_clause=False,
        lc_is_transferable=False,
        lc_partial_shipment_allowed=True,
        lc_transshipment_allowed=True,
        lc_amount_tolerance_pct=10.0,
        lc_expiry_date=date(2024, 6, 10),
        lc_latest_shipment_date=date(2024, 1, 31),
        lc_presentation_period_days=21,
        lc_max_gross_weight_kg=800.0,
        lc_max_measurement_cbm=20.0,
        lc_freight_amount=1200.0,
        lc_incoterms="FOB",
        bl_issue_date=date(2024, 1, 15),
        onboard_date=date(2024, 1, 15),
        presentation_date=date(2024, 1, 20),
        extraction_source="pdf",
        field_confidences={},
        missing_fields=[],
        no_evidence_fields=[],
    )
    base.update(overrides)
    return SynthShipment(**base)


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine()


def _fired_ids(shipment: SynthShipment, engine: RuleEngine) -> set[str]:
    outcome = rule_adapter.evaluate_shipment(
        shipment, engine, catalog_version=engine.catalog_version
    )
    return {f.rule_code for f in outcome.firings}


def test_clean_shipment_baseline_fires_nothing(engine):
    """전제 조건 확인 — 아래 두 테스트가 "하자가 룰을 발화시켰다"고 결론 내리려면
    무하자 기준 선적 자체는 반드시 0건이어야 한다(그렇지 않으면 원인 귀속이 틀린다)."""
    shipment = _clean_shipment()
    fired = _fired_ids(shipment, engine)
    assert not fired, f"기준 선적이 이미 룰을 발화시킵니다(테스트 전제 위반): {sorted(fired)}"


@pytest.mark.parametrize("spec", injector.COVERED_SPECS, ids=lambda s: s.type)
def test_covered_spec_fires_target_rule(spec, engine):
    """COVERED_SPECS 각 항목이 실제로 target_rule 을 발화시킨다.

    HANDOFF.md 4b단계가 고친 정확히 그 버그(예: expiry_exceeded 가 date_of_issue
    대신 onboard_date 를 바꿔 D008 이 안 터지던 것, port_mismatch 가 `" (ALT)"`
    접미사로 토큰 일치를 통과하던 것)가 재발하면 여기서 즉시 실패해야 한다.
    """
    assert spec.covered_by_rule, f"{spec.type}: COVERED_SPECS 항목인데 covered_by_rule=False"
    assert spec.target_rule, f"{spec.type}: target_rule 이 비어 있습니다 — 매핑 누락"

    fired_union: set[str] = set()
    for seed in range(_TRIALS):
        shipment = _clean_shipment(base_shipment_id=f"S{seed:05d}", shipment_id=f"S{seed:05d}")
        rng = random.Random(seed)
        spec.apply(shipment, rng)
        fired_union |= _fired_ids(shipment, engine)

    hit = fired_union & set(spec.target_rule)
    assert hit, (
        f"{spec.type}: target_rule={spec.target_rule} 중 어느 것도 {_TRIALS}회 시도에서 "
        f"발화하지 않았습니다. 실제 발화(합집합): {sorted(fired_union)}"
    )


@pytest.mark.parametrize("spec", injector.UNCOVERED_SPECS, ids=lambda s: s.type)
def test_uncovered_spec_fires_no_rule(spec, engine):
    """UNCOVERED_SPECS 는 (진실 위에서) 어떤 룰도 발화시키지 않는다 — 엔진이
    송장·포장명세서 필드를 아예 입력받지 않으므로 구조적으로 불가능해야 한다
    (설계서 5.3.1 "룰 밖" 표)."""
    assert not spec.covered_by_rule, f"{spec.type}: UNCOVERED_SPECS 항목인데 covered_by_rule=True"
    assert spec.target_rule == (), (
        f"{spec.type}: 룰 밖 하자인데 target_rule 이 비어있지 않습니다: {spec.target_rule}"
    )

    for seed in range(_TRIALS):
        shipment = _clean_shipment(base_shipment_id=f"S{seed:05d}", shipment_id=f"S{seed:05d}")
        rng = random.Random(seed)
        spec.apply(shipment, rng)
        fired = _fired_ids(shipment, engine)
        assert not fired, f"{spec.type}: 룰 밖 하자인데 {sorted(fired)} 가 발화했습니다(seed={seed})"


def test_every_defect_spec_type_is_unique():
    """COVERED_SPECS 와 UNCOVERED_SPECS 를 합쳐 type 이 중복되면 ALL_SPECS 딕셔너리가
    조용히 하나를 덮어써 버린다 — 여기서 명시적으로 잡는다."""
    all_specs = list(injector.COVERED_SPECS) + list(injector.UNCOVERED_SPECS)
    types = [s.type for s in all_specs]
    assert len(types) == len(set(types)), f"중복된 defect type: {sorted(set(t for t in types if types.count(t) > 1))}"

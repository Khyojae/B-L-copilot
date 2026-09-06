"""`rule_adapter.py` 검증 (HANDOFF.md 2단계).

여기서 확인하는 것:
- 알려진 하자를 가진 선적이 실제로 기대한 룰 id 를 발화시키는지(라운드 트립).
- `firings`/`skipped` 가 21개 룰 카탈로그를 정확히 분할하는지.
- 심각도 매핑이 `EngineSeverity` 전 항목을 커버하는지.
- 가중치 합이 `Verdict.defect_probability` 처럼 1.0 에서 잘리지 않는지.
- L/C 없는 선적은 L/C 의존 룰을 skip(위반 아님)으로 남기는지.
- `as_of` 가 실제로 엔진에 전달되는지.
- `schema.LCTerms` 와 `EngineLCTerms` 가 별개 클래스라는 하자드 가드.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from f3_research import rule_adapter, schema
from f3_research.ruleEngine.engine import RuleEngine
from f3_research.ruleEngine.types import LCTerms as EngineLCTerms
from f3_research.ruleEngine.types import Severity as EngineSeverity
from f3_research.synth.generator import SynthShipment


def _make_shipment(**overrides) -> SynthShipment:
    """모든 필드를 채운 "정합성 완전" 선적 하나. 개별 테스트가 특정 필드만
    덮어써서 하자를 만든다.

    B/L·L/C 신규 필드(설계서 5.3.1, HANDOFF.md 4단계)는 기본값 상태에서
    서로 정합하도록 맞춘다 — `lc_port_of_loading`/`lc_consignee`/
    `lc_goods_description` 은 B/L 쪽과 동일(EQ 제약), `lc_latest_shipment_date`
    는 `onboard_date` 이후이자 `lc_expiry_date` 이전, `lc_max_gross_weight_kg`/
    `lc_max_measurement_cbm` 은 실제 값 이상, `lc_freight_amount` 는
    `freight_amount_usd` 와 동일(허용오차 내), `lc_documents_required` 는
    B/L 을 포함한다.
    """
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


# ── 라운드 트립 ──────────────────────────────────────────────────────


def test_알려진_하자_라운드_트립(engine):
    """L/C 유효기간(2024-01-10)보다 늦은 발행일(2024-01-15)을 가진 선적은
    D008(유효기간 경과)을 발화시켜야 한다.

    실측 결과(2026-08-16, RuleEngine() 기본 카탈로그):
        fired = ['D001', 'D008']
        skipped = ['D002', 'D003', 'D005B', 'D006', 'D007', 'D007B',
                    'D013', 'D014', 'D015', 'D016', 'D017']
    D001 이 같이 발화하는 이유: `bl_no`/`measurement`/`total_freight` 는
    `SynthShipment` 에 아직 없어(4단계 몫) `to_engine_bl()` 이 그 키를
    아예 넣지 않는다 — B/L 번호 누락으로 정직하게 위반 처리된다.
    """
    shipment = _make_shipment(
        lc_expiry_date=date(2024, 1, 10),
        bl_issue_date=date(2024, 1, 15),
    )
    outcome = rule_adapter.evaluate_shipment(
        shipment, engine, catalog_version=engine.catalog_version
    )
    fired_ids = {f.rule_code for f in outcome.firings}
    assert "D008" in fired_ids, f"D008 이 발화하지 않았습니다. 실제 발화: {sorted(fired_ids)}"


# ── firings ⊎ skipped == 카탈로그 ─────────────────────────────────────


def test_firings와_skipped는_카탈로그를_분할한다(engine):
    """21개 룰 각각은 firings 또는 skipped 중 정확히 하나(또는 어느 쪽에도
    없이 '통과')에 속해야 한다 — 겹치면 안 되고, 카탈로그 밖 id 가 나오면
    안 된다."""
    shipment = _make_shipment()
    outcome = rule_adapter.evaluate_shipment(
        shipment, engine, catalog_version=engine.catalog_version
    )
    fired_ids = {f.rule_code for f in outcome.firings}
    skipped_ids = {s.rule_code for s in outcome.skipped}
    catalog_ids = set(engine.rule_ids)

    assert fired_ids & skipped_ids == set(), (
        f"같은 룰이 firings 와 skipped 에 동시에 있습니다: {fired_ids & skipped_ids}"
    )
    assert fired_ids <= catalog_ids, f"카탈로그에 없는 발화: {fired_ids - catalog_ids}"
    assert skipped_ids <= catalog_ids, f"카탈로그에 없는 skip: {skipped_ids - catalog_ids}"
    assert len(engine.rule_ids) == 21


# ── 심각도 매핑 ──────────────────────────────────────────────────────


def test_심각도_매핑은_EngineSeverity_전_항목을_커버한다():
    assert set(rule_adapter.SEVERITY_MAP) == set(EngineSeverity)
    for eng_sev in EngineSeverity:
        mapped = rule_adapter.SEVERITY_MAP[eng_sev]
        assert mapped == eng_sev.value.upper()


# ── 가중치 합은 클리핑되지 않는다 ──────────────────────────────────────


def test_가중치_합은_1_0에서_잘리지_않는다(engine):
    """필수 critical 필드 4개(bl_no/consignee/port_of_loading/port_of_discharge)를
    동시에 비워 위반 4건(0.30×4=1.20)을 만든다. `Verdict.defect_probability` 라면
    1.0 으로 clipping 되지만, firings 의 weight 합은 그러면 안 된다.

    주의: 4a 단계에서 `bl_no` 가 생성기에 추가되기 전에는 D001 이 자동으로 발화해
    필드 3개만 비워도 4건이 됐다. 이제는 **명시적으로 비워야** 한다 — 테스트가
    "필드가 없어서 우연히 터지는" 상태에 의존하지 않게 한다."""
    shipment = _make_shipment(
        bl_no="",
        consignee="",
        port_of_loading="",
        port_of_discharge="",
    )
    outcome = rule_adapter.evaluate_shipment(
        shipment, engine, catalog_version=engine.catalog_version
    )
    total_weight = sum(f.weight for f in outcome.firings)
    assert total_weight > 1.0, (
        f"가중치 합이 1.0 을 넘는 케이스를 만들지 못했습니다: {total_weight}"
    )


# ── L/C 없음 → skip, 위반 아님 ─────────────────────────────────────────


def test_LC_없는_선적은_LC_의존_룰이_skip된다(engine):
    shipment = _make_shipment(
        lc_present=False,
        lc_required_doc_count=None,
        lc_47a_text="",
        lc_has_special_clause=False,
        lc_is_transferable=False,
        lc_expiry_date=None,
        lc_presentation_period_days=None,
        lc_amount_tolerance_pct=0,
    )
    outcome = rule_adapter.evaluate_shipment(
        shipment, engine, catalog_version=engine.catalog_version
    )
    fired_ids = {f.rule_code for f in outcome.firings}
    skipped_ids = {s.rule_code for s in outcome.skipped}

    lc_dependent = {
        "D002", "D003", "D004", "D005B", "D006",
        "D008", "D013", "D014", "D015", "D016", "D017",
    }
    assert fired_ids & lc_dependent == set(), (
        f"L/C 가 없는데 L/C 의존 룰이 발화했습니다: {fired_ids & lc_dependent}"
    )
    assert lc_dependent & skipped_ids, "L/C 의존 룰이 하나도 skip 되지 않았습니다"


# ── as_of 가 실제로 전달된다 ────────────────────────────────────────────


def test_as_of가_실제로_전달된다(engine):
    """같은 선적을 제시일만 다르게 해서 두 번 평가하면(D018 제시기간 룰이
    보는 as_of 가 달라지므로) 결과가 달라야 한다."""
    early = _make_shipment(
        onboard_date=date(2024, 1, 1),
        bl_issue_date=date(2024, 1, 1),
        presentation_date=date(2024, 1, 3),  # 제시기간(21일) 이내
    )
    late = dataclasses.replace(early, presentation_date=date(2024, 2, 10))  # 이내를 넘음

    outcome_early = rule_adapter.evaluate_shipment(
        early, engine, catalog_version=engine.catalog_version
    )
    outcome_late = rule_adapter.evaluate_shipment(
        late, engine, catalog_version=engine.catalog_version
    )

    fired_early = {f.rule_code for f in outcome_early.firings}
    fired_late = {f.rule_code for f in outcome_late.firings}
    assert "D018" not in fired_early
    assert "D018" in fired_late
    assert fired_early != fired_late


# ── LCTerms 동명이물 하자드 가드 ─────────────────────────────────────────


def test_schema_LCTerms와_EngineLCTerms는_별개_클래스다():
    """`schema.LCTerms` 와 `ruleEngine.types.LCTerms`(`EngineLCTerms`)는
    이름은 같지만 필드가 완전히 다른 별개 클래스여야 한다. 누군가 나중에
    "이름이 같으니 하나로 합치자"고 하면, 이 테스트가 조용한 회귀
    (모든 룰이 평가불가로 떨어지는) 대신 시끄러운 실패로 알려준다."""
    schema_fields = set(schema.LCTerms.__dataclass_fields__)
    engine_fields = set(EngineLCTerms.__dataclass_fields__)

    assert schema.LCTerms is not EngineLCTerms
    assert schema_fields.isdisjoint(engine_fields), (
        "schema.LCTerms 와 EngineLCTerms 가 필드를 공유합니다 — "
        f"공유 필드: {schema_fields & engine_fields}. "
        "두 클래스가 통합되었다면 rule_adapter.py 의 EngineLCTerms 별칭 "
        "관례 전체를 재검토해야 합니다."
    )

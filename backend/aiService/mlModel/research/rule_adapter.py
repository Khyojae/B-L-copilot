"""실제 룰엔진(`ruleEngine/`) ↔ 피처 파이프라인(`schema.py`) 어댑터 (설계서 5.4).

`rule_sim.py`("★ 이 모듈은 임시 대역이다 ★")가 흉내내던 채널 A 출력을, 실제
룰엔진의 `Verdict` 로부터 만든다.

★★ `LCTerms` 동명이물 경고 ★★
`f3_research.schema.LCTerms` (피처 쪽, Group 4 원천)과
`f3_research.ruleEngine.types.LCTerms` (엔진 쪽, MT700 조건)은 이름만 같고
필드가 완전히 다른 별개 클래스다. 이 모듈에서 엔진 쪽은 **항상**
`EngineLCTerms` 로 별칭을 걸어 import 한다. 별칭 없이 잘못 import 하면(즉
`schema.LCTerms` 인스턴스를 엔진에 넘기면) 모든 `.get()` 호출이 `None` 을
돌려준다 — 21개 룰 전부가 "평가불가"로 떨어지고 위반 0건, 즉 "하자 없음"으로
읽힌다. 예외도, 테스트 실패도 없이 그럴듯하게 틀린 답이 나온다.

Production·research 양쪽이 이 모듈을 쓴다 — 그래서 `synth/` 밑이 아니라
패키지 최상위에 둔다.
"""

from __future__ import annotations

from datetime import datetime, time

from f3_research.ruleEngine.engine import RuleEngine, load_catalog
from f3_research.ruleEngine.types import (
    DEFAULT_TOLERANCE_PCT,
    LCTerms as EngineLCTerms,
    Severity as EngineSeverity,
    Verdict,
)
from f3_research.schema import (
    RuleEngineOutcome,
    RuleFiring,
    Severity,
    SkippedRule,
)
from f3_research.synth.generator import SynthShipment

# ── 심각도 매핑 ──────────────────────────────────────────────────────
#
# ruleEngine.types.Severity 는 소문자 str Enum("critical"/"warning"/"info"),
# schema.Severity 는 대문자 Literal("CRITICAL"/"WARNING"/"INFO")이다. 반드시
# 명시적 dict 로 인덱싱한다(`MAP[sev]`) — `.get(sev, default)` 을 쓰면
# features.py::_rv_features 의 `SEVERITY_WEIGHT.get(..., 0)` 과 같은 패턴이
# 되어, 매핑에 없는 심각도가 조용히 0점(INFO 취급)으로 새어 들어간다.
SEVERITY_MAP: dict[EngineSeverity, Severity] = {
    EngineSeverity.CRITICAL: "CRITICAL",
    EngineSeverity.WARNING: "WARNING",
    EngineSeverity.INFO: "INFO",
}
assert set(SEVERITY_MAP) == set(EngineSeverity), (
    "SEVERITY_MAP 이 EngineSeverity 전 항목을 커버하지 않습니다"
)


# ── B/L bag ──────────────────────────────────────────────────────────


def to_engine_bl(shipment: SynthShipment) -> dict[str, str]:
    """설계서 5.4: `SynthShipment` → 룰엔진이 duck-type 으로 받는 B/L bag.

    엔진은 값을 문자열로 읽어 재파싱하므로 포맷이 결과를 바꾼다. 특히
    `gross_weight`/`measurement` 는 단위 접미사가 없으면 `parse_quantity()` 가
    `None` 을 돌려준다 — 검증됨: bare `"512.0"` 은 파싱되지 않고, `"512.0 KG"` 만
    된다(`tests/test_rule_engine.py::test_parse_quantity_단위_접미사_필수`).
    `total_freight` 는 `within_tolerance` 가 `parse_amount()` 로 읽으므로 단위
    접미사가 필요 없다 — 숫자 문자열이면 된다.

    `bl_no`/`measurement`/`total_freight` 는 설계서 5.3.1(HANDOFF.md 4단계)에서
    `SynthShipment` 에 추가됐다.

    `date_of_issue`/`gross_weight` 는 `None` 일 수 있다 — `synth/extraction_view.py`
    (설계서 5.4, HANDOFF.md 5단계)가 관측 노이즈로 필드를 "드랍"할 때, 문자열
    필드는 빈 문자열로 왜곡되지만 `bl_issue_date`(date)/`gross_weight_kg`(float)는
    타입상 빈 문자열을 담을 수 없어 `None` 으로 드랍된다. `to_engine_lc` 가 이미
    Optional 날짜 필드에 쓰는 것과 같은 패턴(`... if ... else None`)을 여기서도
    쓴다 — `None` 은 빈 문자열로 렌더링되고, `checks.field_value()` 가 빈 문자열을
    "값 없음"으로 정규화하므로 해당 룰은 required-missing 또는 not-evaluated 로
    떨어진다(워터마크 없이 자연스러운 결측 표현).
    """
    description_of_goods = shipment.goods_description
    if shipment.lc_incoterms:
        # D015(Incoterms 미표시, checks.py::contains_incoterms)가 정상 건에서
        # 통과하려면 L/C 지정 Incoterms 코드가 물품 명세 어딘가에 있어야 한다
        # (설계서 5.3.1 "B/L 품명이 D015 가 찾는 걸 실어야 한다"). Group 2
        # dc_max_edit_distance_ratio 등은 `shipment.goods_description` 원본을
        # 그대로 쓰므로(`generator.to_snapshot`), 접미사는 엔진 입력 변환
        # 지점인 여기서만 붙이고 SynthShipment 필드 자체는 건드리지 않는다.
        description_of_goods = f"{description_of_goods} {shipment.lc_incoterms}"
    return {
        "shipper": shipment.shipper,
        "consignee": shipment.consignee,
        "notify_party": shipment.notify_party,
        "vessel": shipment.vessel,
        "port_of_loading": shipment.port_of_loading,
        "port_of_discharge": shipment.port_of_discharge,
        "description_of_goods": description_of_goods,
        "on_board_date": shipment.onboard_date.isoformat(),
        "date_of_issue": shipment.bl_issue_date.isoformat() if shipment.bl_issue_date else "",
        "gross_weight": (
            f"{shipment.gross_weight_kg:.1f} KG" if shipment.gross_weight_kg is not None else ""
        ),
        "bl_no": shipment.bl_no,
        "measurement": f"{shipment.measurement_cbm:.2f} CBM",
        "total_freight": f"{shipment.freight_amount_usd:.2f}",
    }


# ── L/C 조건 ─────────────────────────────────────────────────────────


def to_engine_lc(shipment: SynthShipment) -> EngineLCTerms | None:
    """설계서 5.4/5.3.1: `SynthShipment` → 룰엔진의 `EngineLCTerms`.

    L/C 없는 거래(설계서 4절, 전체의 5%)는 `None` 을 돌려준다.
    `RuleEngine.verify()` 는 `lc=None` 이면 기본 `EngineLCTerms()` 로 채우고,
    조건이 명시되지 않은 대조 룰들은 위반이 아니라 not_evaluated 로 skip
    된다 — 삼항 평가 설계(ruleEngine/types.py 모듈 docstring)가 지키는 것이
    "입력 부족을 통과로 읽지 않는다"이다.

    `lc_no`/`currency_amount`/`applicant`/`beneficiary` 는 어떤 룰도 참조하지
    않아(설계서 5.3.1) 여전히 매핑하지 않는다 — `None`/기본값 그대로 둔다.
    나머지 L/C 필드는 HANDOFF.md 4단계에서 `SynthShipment` 에 추가됐다.
    """
    if not shipment.lc_present:
        return None

    tolerance_pct = shipment.lc_amount_tolerance_pct
    if tolerance_pct == 0:
        # generator._build_shipment 가 rng.choice([0, 5, 10]) 로 0 을 뽑는다
        # (설계서 5.2). 0 을 그대로 넣으면 within_tolerance 룰이 "정확히
        # 일치해야만 통과"가 되어, 반올림 수준의 오차에도 발화하는 오탐
        # 룰이 된다. L/C 가 :39A: 를 침묵했을 때의 UCP 600 Art.30(a) 기본
        # 허용치(엔진 DEFAULT_TOLERANCE_PCT)로 대체한다 — 0 은 "명시적으로
        # 무허용"이 아니라 "39A 미기재"를 나타내는 값이라고 본다.
        tolerance_pct = DEFAULT_TOLERANCE_PCT

    return EngineLCTerms(
        port_of_loading=shipment.lc_port_of_loading,
        port_of_discharge=shipment.lc_port_of_discharge,
        consignee=shipment.lc_consignee,
        description_of_goods=shipment.lc_goods_description,
        latest_shipment_date=(
            shipment.lc_latest_shipment_date.isoformat()
            if shipment.lc_latest_shipment_date
            else None
        ),
        partial_shipment="ALLOWED" if shipment.lc_partial_shipment_allowed else "PROHIBITED",
        transhipment="ALLOWED" if shipment.lc_transshipment_allowed else "PROHIBITED",
        expiry_date=shipment.lc_expiry_date.isoformat() if shipment.lc_expiry_date else None,
        tolerance_pct=tolerance_pct,
        presentation_days=shipment.lc_presentation_period_days,
        max_gross_weight_kg=shipment.lc_max_gross_weight_kg,
        max_measurement_cbm=shipment.lc_max_measurement_cbm,
        freight_amount=shipment.lc_freight_amount,
        incoterms=shipment.lc_incoterms,
        documents_required=list(shipment.lc_documents_required),
    )


# ── 카탈로그 심각도 조회 ─────────────────────────────────────────────

_catalog_severity_cache: dict[str, EngineSeverity] | None = None


def _catalog_severity_lookup() -> dict[str, EngineSeverity]:
    """`rules.yaml` 에서 `rule_id → 심각도` 조회표를 만든다 (지연 로드, 캐시).

    스킵된 룰은 outcome 이 없어 심각도를 outcome 에서 읽을 수 없다 —
    `SkippedRule.catalog_severity` 는 반드시 카탈로그 원본에서 와야 한다.
    """
    global _catalog_severity_cache
    if _catalog_severity_cache is None:
        _, rules = load_catalog()
        _catalog_severity_cache = {
            rule["id"]: EngineSeverity(rule["severity"]) for rule in rules
        }
    return _catalog_severity_cache


# ── 변환·진입점 ──────────────────────────────────────────────────────


def verdict_to_outcome(verdict: Verdict, *, catalog_version: str) -> RuleEngineOutcome:
    """룰엔진 `Verdict` → `RuleEngineOutcome`.

    "통과" 집합은 담지 않는다 — 카탈로그 전체(`RULE_CODES`)에서
    `firings`·`skipped` 의 rule_code 를 뺀 나머지가 통과 집합이다(암묵적,
    schema.py `RuleEngineOutcome` docstring 참고).

    `Verdict.defect_probability` 는 쓰지 않는다 — 1.0 에서 클리핑되어
    가중치 합의 정보를 파괴한다(검증됨: 치명 0.40+0.40+0.30 셋 다 1.0 으로
    뭉개진다). 가중치 합이 필요하면 `sum(f.weight for f in outcome.firings)`
    를 직접 계산한다 — 클리핑되지 않는다.
    """
    catalog_severity = _catalog_severity_lookup()

    firings = tuple(
        RuleFiring(
            rule_code=violation.rule_id,
            severity=SEVERITY_MAP[violation.severity],
            field_codes=tuple(violation.fields),
            weight=violation.weight,
        )
        for violation in verdict.violations
    )
    skipped = tuple(
        SkippedRule(
            rule_code=skip.rule_id,
            catalog_severity=SEVERITY_MAP[catalog_severity[skip.rule_id]],
            reason=skip.reason,
        )
        for skip in verdict.skipped
    )
    return RuleEngineOutcome(
        firings=firings, skipped=skipped, catalog_version=catalog_version
    )


def evaluate_shipment(
    shipment: SynthShipment, engine: RuleEngine, *, catalog_version: str
) -> RuleEngineOutcome:
    """`SynthShipment` 를 룰엔진에 태워 `RuleEngineOutcome` 을 얻는 편의 함수.

    `as_of` 는 반드시 넘긴다 — 넘기지 않으면 `verify()` 가 `datetime.now()`
    로 떨어져(ruleEngine/checks.py::presentation_period) 재현성이 깨진다.
    기준 시각은 서류 제시일(`presentation_date`) 자정으로 고정한다.
    """
    bl = to_engine_bl(shipment)
    lc = to_engine_lc(shipment)
    as_of = datetime.combine(shipment.presentation_date, time.min)
    verdict = engine.verify(bl, lc, as_of=as_of)
    return verdict_to_outcome(verdict, catalog_version=catalog_version)


__all__ = [
    "SEVERITY_MAP",
    "evaluate_shipment",
    "to_engine_bl",
    "to_engine_lc",
    "verdict_to_outcome",
]

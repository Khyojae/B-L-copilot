"""기획안 5.3 피처군의 입력 DTO.

`features.py::extract_features(snapshot)` 가 읽는 유일한 입력 형태다.
학습 시에는 `synth/generator.py` + `synth/injector.py` + `rule_adapter.py`(또는
`synth/rule_sim.py` 임시 대역, HANDOFF.md 3단계) 가 채우고, 실전 추론 시에는
룰엔진·추출 파이프라인·DB 이력 조회가 채운다. 두 경로 모두 이 스키마를
거치므로 피처 계약이 하나로 유지된다(설계서 4절 원칙 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Severity = Literal["CRITICAL", "WARNING", "INFO"]
ExtractionSource = Literal["pdf", "scan", "json", "manual"]


@dataclass(frozen=True)
class RuleFiring:
    """Group 1 원천. 실제 룰엔진(`ruleEngine/`) `Verdict.violations` 1건에 대응한다
    (설계서 5.4, HANDOFF.md 3단계에서 옛 40코드 자리표시자 형태를 대체).

    `field_codes` 는 튜플이다 — `ruleEngine.types.Violation.fields` 는 리스트라서
    D014(환적 금지, 필드 3개)처럼 여러 개일 수도, D016(요구서류 목록에 B/L
    없음)처럼 0개일 수도 있다. 단일 `str | None` 로 접으면
    `rv_distinct_field_count` 가 저평가된다.
    """

    rule_code: str
    severity: Severity
    field_codes: tuple[str, ...] = ()
    weight: float = 0.0


@dataclass(frozen=True)
class SkippedRule:
    """평가되지 못한 룰 1건 (삼항 평가의 세 번째 상태, ruleEngine/types.py 참고).

    `catalog_severity` 는 `rules.yaml` 원본 카탈로그의 심각도다 — 스킵된
    룰은 outcome 이 없으므로 outcome 에서 심각도를 읽을 방법이 없다.
    """

    rule_code: str
    catalog_severity: Severity
    reason: str


@dataclass(frozen=True)
class RuleEngineOutcome:
    """실제 룰엔진 `Verdict` 1건을 Group 1 피처가 쓰기 좋은 형태로 담는다.

    "통과" 집합은 별도 필드로 담지 않는다 — 룰 카탈로그 전체 집합에서
    `firings`·`skipped` 의 rule_code 를 뺀 나머지가 곧 통과 집합이다
    (`RULE_CODES - fired - skipped`, 카탈로그는 `rule_adapter.py` 또는
    호출부가 `RuleEngine.rule_ids` 로 얻는다).
    """

    firings: tuple[RuleFiring, ...]
    skipped: tuple[SkippedRule, ...]
    catalog_version: str


@dataclass(frozen=True)
class LLMFeatures:
    """Group 7 원천 — Gemini(HANDOFF.md 8~10단계) 산출 의미론적 피처.

    전 필드가 `None` 가능하다 — `snapshot.llm is None`(LLM 미사용/실패)이면
    `llm_available=0.0` 이고 이 필드들은 전부 NaN 으로 인코딩된다(features.py).
    `llm_available` 자체는 이 dataclass 의 필드가 아니다 — `snapshot.llm` 의
    존재 여부에서 파생되는 값이라 이중 저장을 피한다.
    """

    verifiable_47a_ratio: float | None
    unverifiable_47a_count: int | None
    goods_semantic_equiv: float | None
    goods_invoice_semantic_equiv: float | None
    party_semantic_equiv_min: float | None
    doc_conflict_count: int | None
    lc_complexity_score: float | None


@dataclass(frozen=True)
class DocConsistencyInputs:
    """Group 2 원천 — 서류 간 비교 대상 원시값.

    편차율은 features.py 가 계산한다(계약 위반 방지: 계산 로직은 한 곳에만 둔다).
    """

    # (필드 이름, B/L측 값, 대조서류측 값) — 이름 매칭 편의를 위해 named pair 사용
    party_name_pairs: tuple[tuple[str, str | None, str | None], ...] = ()
    bl_qty: float | None = None
    packing_qty_sum: float | None = None
    bl_weight: float | None = None
    packing_weight_sum: float | None = None
    invoice_amount: float | None = None
    computed_amount: float | None = None  # 수량 × 단가 (DERIVE 제약)
    conflict_field_count: int = 0  # 연속값 비율로 안 잡히는 범주형 불일치(항구·품명 등) 개수


@dataclass(frozen=True)
class ExtractionQualityInputs:
    """Group 3 원천 — 필드별 추출 신뢰도.

    field_confidences 의 키 집합은 eval_report_merged.json 의
    field_accuracy_by_field 키(bl_no, shipper, consignee, port_of_loading,
    port_of_discharge, date_of_issue, gross_weight)와 맞춘다(설계서 5.1).
    """

    field_confidences: dict[str, float] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    no_evidence_fields: tuple[str, ...] = ()
    checked_field_count: int = 0
    source: ExtractionSource = "pdf"


@dataclass(frozen=True)
class LCTerms:
    """Group 4 원천. None 이면 lc_absent=1 이고 나머지는 전부 NaN(설계서 4절).

    ★ 동명이물 경고 ★ `f3_research.ruleEngine.types.LCTerms`(엔진 쪽, MT700
    조건)와 이름만 같고 필드가 완전히 다른 별개 클래스다. 엔진 쪽은 항상
    `EngineLCTerms` 로 별칭을 걸어 import 한다(`rule_adapter.py` 참고).
    """

    required_doc_count: int | None = None  # :46A:
    field_47a_text: str = ""
    has_special_clause: bool = False
    is_transferable: bool = False
    partial_shipment_allowed: bool = True
    transshipment_allowed: bool = True
    amount_tolerance_pct: float = 0.0


@dataclass(frozen=True)
class ShipmentDates:
    """Group 5 원천. 결측은 NaN 으로 features.py 가 인코딩한다."""

    lc_expiry_date: date | None = None  # :31D:
    bl_issue_date: date | None = None
    onboard_date: date | None = None
    presentation_date: date | None = None
    presentation_period_days: int | None = None  # :48:


@dataclass(frozen=True)
class HistoryStats:
    """Group 6 원천. 이미 계산된 이력 비율을 그대로 담는다(계산은 dataset.py/실전 DB 조회).

    콜드스타트(counterparty_shipment_count == 0)면 세 비율은 반드시 None 이어야 한다.
    """

    counterparty_defect_rate: float | None = None
    bank_defect_rate: float | None = None
    cargo_type_defect_rate: float | None = None
    counterparty_shipment_count: int = 0


@dataclass(frozen=True)
class ShipmentSnapshot:
    """extract_features() 의 유일한 입력 타입."""

    shipment_id: str
    base_shipment_id: str  # GroupKFold 용 그룹 키(설계서 6.1)
    rule_outcome: RuleEngineOutcome
    doc_consistency: DocConsistencyInputs
    extraction_quality: ExtractionQualityInputs
    lc: LCTerms | None
    dates: ShipmentDates
    history: HistoryStats
    llm: LLMFeatures | None = None

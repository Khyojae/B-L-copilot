"""하자 주입 (설계서 5.3, 5.3.1).

정합성이 완전한 `SynthShipment` 사본에 하자 1~3건을 주입하고
`injected_defects[]` 를 기록한다. 이것이 채널 A(rule_adapter)·채널 B(review)의
공통 입력이자 유일한 접점이다 — 이 시점 이후 두 채널은 서로를 참조하지 않는다.

주입 유형은 두 부류로 나눈다 (룰 커버 65% / 룰 밖 35%). 35%는 설계서 1절 해법의
필수 조건이다 — 이 부류가 없으면 모델이 룰 위에 더할 정보가 존재하지 않는다.

★ HANDOFF.md 4b단계(인젝터 재정렬) ★
v3까지 COVERED_SPECS 는 가상의 40코드 룰 벡터를 전제로 작성돼, 실제 21룰 엔진
(`ruleEngine/`, B/L↔L/C만 비교)에는 대부분 보이지 않았다(`phi(y, rv_any_critical)`
0.074까지 붕괴, 10/21 룰 무발화). 아래 COVERED_SPECS 는 각 항목이 **실제로 목표
룰을 발화시키는지** `tests/test_injector_alignment.py` 가 개별 assert 로 검증한다
— `DefectSpec.target_rule` 이 그 매핑을 데이터로 고정한다(주석이 아니라).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from f3_research.synth import generator
from f3_research.synth.generator import (
    SynthShipment,
    natural_deviation_ratio,
    vary_wording,
)


@dataclass(frozen=True)
class Defect:
    """주입된 하자 1건. 두 채널의 공통 입력."""

    type: str
    field: str
    severity: str  # CRITICAL | WARNING | INFO
    covered_by_rule: bool


@dataclass(frozen=True)
class DefectSpec:
    type: str
    weight: float  # 부류(covered/uncovered) 내 상대 샘플링 가중치
    severity: str
    field: str
    covered_by_rule: bool
    apply: Callable[[SynthShipment, random.Random], None]
    # 이 하자가 발화시켜야 할 룰 id(들, 설계서 5.3.1 표). covered_by_rule=False 인
    # 하자는 반드시 빈 튜플이다 — `tests/test_injector_alignment.py` 가 두 방향
    # 모두 강제한다(룰 커버는 발화해야, 룰 밖은 발화하면 안 된다). 대부분 1개짜리
    # 튜플이지만 `required_field_missing` 은 매 호출마다 무작위로 필드 하나를
    # 비우므로(D001/D005/D009/D010/D011/D012/D012B 중 하나) 후보 전체를 담는다 —
    # 테스트는 "그중 하나라도 발화" 를 확인한다.
    target_rule: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 룰 커버 하자 (65%) — 실제 룰엔진이 발화시킬 수 있는 것만(설계서 5.3.1).
#
# 금지: 접미사 부착(`" (ALT)"`)처럼 토큰 일치(ruleEngine/checks.py::_tokens_match,
# MATCH_THRESHOLD=0.6)로 통과해 버리는 변형. 항구·회사명은 전혀 다른 값으로
# **교체**한다 — 아래 ALT_PORT_POOL/ALT_COMPANY_POOL 이 그 후보다.
# ---------------------------------------------------------------------------

# 항구 교체용 풀. pools.py(AI Hub 값 분포)에 의존하지 않고 자기완결적으로 둔다
# (generator.py 의 LC_47A_CONDITION_POOL 과 같은 패턴 — 이 모듈만으로도
# 재현·단위테스트가 가능해야 한다). 같은 나라 항구끼리도 도시명 토큰이 달라
# `_tokens_match` 의 0.6 임계값을 넘지 못한다(도시+국가 2토큰 중 국가만 겹치면
# 0.5) — 원래 값과 동일한 문자열만 제외하면 안전하게 미스매치가 만들어진다.
ALT_PORT_POOL: tuple[str, ...] = (
    "BUSAN, KOREA",
    "INCHEON, KOREA",
    "SHANGHAI, CHINA",
    "NINGBO, CHINA",
    "SINGAPORE, SINGAPORE",
    "ROTTERDAM, NETHERLANDS",
    "LOS ANGELES, USA",
    "LONG BEACH, USA",
    "HAMBURG, GERMANY",
    "DUBAI, UAE",
    "HO CHI MINH CITY, VIETNAM",
    "TOKYO, JAPAN",
)

# 수하인 교체용 풀(D005B). 실제 거래처명과 겹치지 않는 가공의 회사명 — 우연히
# 원래 값과 같은 문자열만 배제하면 된다(match_place 의 토큰 임계값을 넘길 만큼
# 겹칠 확률은 사실상 0).
ALT_COMPANY_POOL: tuple[str, ...] = (
    "GLOBAL TRADING CO., LTD.",
    "PACIFIC IMPORT EXPORT CORP.",
    "UNITED CARGO LOGISTICS INC.",
    "ORIENT MERCHANDISE PTE. LTD.",
    "ATLANTIC COMMERCE GMBH",
    "SILK ROAD TRADING LLC",
    "HARBOR LINE INDUSTRIES CO., LTD.",
    "EVERGREEN CONSOLIDATED TRADING INC.",
)

# 화물 명세 교체용 풀(D006). L/C 키워드가 그대로 들어있으면 contains_keywords 가
# 통과해 버리므로, lc_goods_description 의 키워드를 포함하지 않는 후보만 고른다
# (_apply_goods_desc_mismatch 참고).
ALT_GOODS_POOL: tuple[str, ...] = (
    "UNSPECIFIED GENERAL MERCHANDISE",
    "MIXED CONSIGNMENT ITEMS N.O.S.",
    "ASSORTED CONSUMER GOODS PER PACKING LIST",
    "SUNDRY ARTICLES OF TRADE",
    "MISCELLANEOUS CARGO PER INVOICE",
)

# required_field_missing(D001/D005/D009/D010/D011/D012/D012B) — ruleEngine/rules.yaml
# 의 `check: required` 룰이 보는 B/L 필드와 SynthShipment 속성명의 매핑.
_REQUIRED_FIELD_TO_RULE: dict[str, str] = {
    "bl_no": "D001",
    "consignee": "D005",
    "shipper": "D009",
    "notify_party": "D010",
    "vessel": "D011",
    "port_of_loading": "D012",
    "port_of_discharge": "D012B",
}


def _apply_expiry_exceeded(s: SynthShipment, rng: random.Random) -> None:
    # D008(유효기간 경과) 는 date_of_issue(=bl_issue_date) 를 본다 — onboard_date
    # 가 아니다(설계서 5.3.1, v3의 미탐 원인). bl_issue_date 를 L/C 유효기일 이후로
    # 민다.
    if s.lc_expiry_date is None:
        return
    s.bl_issue_date = s.lc_expiry_date + timedelta(days=rng.randint(1, 15))
    if s.onboard_date < s.bl_issue_date:
        s.onboard_date = s.bl_issue_date
    if s.presentation_date < s.onboard_date:
        s.presentation_date = s.onboard_date + timedelta(days=rng.randint(2, 10))


def _apply_latest_shipment_exceeded(s: SynthShipment, rng: random.Random) -> None:
    # D002(선적기한 초과) 는 fields=[on_board_date, date_of_issue] 중 첫 번째로
    # 값이 있는 필드를 본다(_first_present) — on_board_date 가 항상 채워지므로
    # 실질적으로 onboard_date 만 본다.
    if s.lc_latest_shipment_date is None:
        return
    s.onboard_date = s.lc_latest_shipment_date + timedelta(days=rng.randint(1, 15))
    if s.presentation_date < s.onboard_date:
        s.presentation_date = s.onboard_date + timedelta(days=rng.randint(2, 10))


def _apply_pol_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # D003. lc_port_of_loading(L/C 지정값)은 그대로 두고 B/L 쪽만 다른 항구로
    # 교체한다 — EQ 제약이 깨져야 하자다.
    if not s.lc_present or not s.lc_port_of_loading:
        return
    candidates = [p for p in ALT_PORT_POOL if p != s.port_of_loading]
    s.port_of_loading = rng.choice(candidates)


def _apply_pod_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # D004(port_mismatch 개명). v3 는 `" (ALT)"` 접미사를 붙였는데
    # `_tokens_match` 가 원래 토큰을 그대로 포함한 문자열을 통과시켜(부분집합
    # 관계상 overlap/len(lc_tokens)=1.0 ≥ 0.6) 미탐이었다. 접미사가 아니라
    # 다른 항구로 **교체**한다.
    if not s.lc_present:
        return
    candidates = [p for p in ALT_PORT_POOL if p != s.port_of_discharge]
    s.port_of_discharge = rng.choice(candidates)


def _apply_bl_consignee_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # D005B. B/L consignee 를 L/C 지정 수하인과 다른 회사로 바꾼다.
    if not s.lc_present or not s.lc_consignee:
        return
    candidates = [c for c in ALT_COMPANY_POOL if c != s.consignee]
    s.consignee = rng.choice(candidates)


def _apply_goods_desc_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # D006(contains_keywords, ruleEngine/checks.py). lc_goods_description 을
    # 콤마로 나눈 조각(대개 콤마가 없으므로 전체 문자열 자체)이 B/L 명세에
    # 부분 문자열로 있어야 통과다. 그 키워드를 포함하지 않는 문구로 완전히
    # 바꾼다 — 빈 문자열로 지우면 not_evaluated(평가불가) 로 빠져 위반이 아니게
    # 된다는 점에 주의(required 룰이 아니라 contains_keywords 다).
    if not s.lc_present or not s.lc_goods_description:
        return
    keywords = [k.strip().upper() for k in s.lc_goods_description.split(",") if k.strip()]
    candidates = [g for g in ALT_GOODS_POOL if not any(k in g.upper() for k in keywords)]
    if not candidates:
        candidates = list(ALT_GOODS_POOL)
    s.goods_description = rng.choice(candidates)


def _apply_weight_over_limit(s: SynthShipment, rng: random.Random) -> None:
    # D007(numeric_not_above). 총중량을 L/C 한도 위로 올린다.
    if not s.lc_present or s.lc_max_gross_weight_kg is None:
        return
    s.gross_weight_kg = round(s.lc_max_gross_weight_kg * rng.uniform(1.05, 1.30), 1)


def _apply_freight_tolerance_breach(s: SynthShipment, rng: random.Random) -> None:
    # D017(within_tolerance). L/C 허용오차(lc_amount_tolerance_pct, 0/5/10% —
    # 0 이면 엔진이 DEFAULT_TOLERANCE_PCT=10% 로 대체한다, rule_adapter.to_engine_lc)
    # 보다 확실히 큰 폭(20~50%)으로 벗어나 허용오차 값과 무관하게 항상 위반되게 한다.
    if not s.lc_present or s.lc_freight_amount is None:
        return
    direction = rng.choice((-1, 1))
    pct = rng.uniform(0.20, 0.50) * direction
    s.freight_amount_usd = round(max(0.01, s.lc_freight_amount * (1 + pct)), 2)


def _apply_required_field_missing(s: SynthShipment, rng: random.Random) -> None:
    # D001/D005/D009/D010/D011/D012/D012B 중 하나(required 검사) — B/L 필수
    # 필드 하나를 무작위로 비운다. field_value() 는 빈 문자열을 "값 없음"으로
    # 정규화하므로 required 룰이 위반으로 떨어진다.
    field_name = rng.choice(list(_REQUIRED_FIELD_TO_RULE))
    setattr(s, field_name, "")


def _apply_presentation_period_exceeded(s: SynthShipment, rng: random.Random) -> None:
    # D018 — 이미 실제로 발화한다(HANDOFF.md 4b단계 진단). 변경 없음.
    period = s.lc_presentation_period_days or 21
    s.presentation_date = s.onboard_date + timedelta(days=period + rng.randint(1, 10))


COVERED_SPECS: tuple[DefectSpec, ...] = (
    DefectSpec("expiry_exceeded", 1.0, "CRITICAL", "bl_issue_date", True, _apply_expiry_exceeded, ("D008",)),
    DefectSpec("latest_shipment_exceeded", 1.0, "CRITICAL", "onboard_date", True, _apply_latest_shipment_exceeded, ("D002",)),
    DefectSpec("pol_mismatch", 1.0, "CRITICAL", "port_of_loading", True, _apply_pol_mismatch, ("D003",)),
    DefectSpec("pod_mismatch", 1.0, "CRITICAL", "port_of_discharge", True, _apply_pod_mismatch, ("D004",)),
    DefectSpec("bl_consignee_mismatch", 1.0, "CRITICAL", "consignee", True, _apply_bl_consignee_mismatch, ("D005B",)),
    DefectSpec("goods_desc_mismatch", 1.0, "CRITICAL", "goods_description", True, _apply_goods_desc_mismatch, ("D006",)),
    DefectSpec("weight_over_limit", 1.0, "CRITICAL", "gross_weight_kg", True, _apply_weight_over_limit, ("D007",)),
    DefectSpec("freight_tolerance_breach", 1.0, "CRITICAL", "freight_amount_usd", True, _apply_freight_tolerance_breach, ("D017",)),
    DefectSpec(
        "required_field_missing",
        1.0,
        "CRITICAL",
        "required_field",
        True,
        _apply_required_field_missing,
        ("D001", "D005", "D009", "D010", "D011", "D012", "D012B"),
    ),
    DefectSpec("presentation_period_exceeded", 1.0, "CRITICAL", "presentation_date", True, _apply_presentation_period_exceeded, ("D018",)),
)

# 의도적으로 제외한 것(설계서 5.3.1 "룰 커버" 표, HANDOFF.md 4b단계 지시):
#   D007B(용적 한도 초과) — 측정 한계상 실무에서 드물다(중량 초과와 중복성 높음).
#   D013(분할선적 금지 위반)/D014(환적 금지 위반) — L/C 가 실제로 금지 조건을
#     명시했을 때만 평가되는데(그 외엔 not_evaluated), 그 조건 자체가 드물어
#     "룰 커버 하자"로 항상 재현 가능한 변형을 만들기 어렵다.
#   D015(Incoterms 미표시)/D016(요구서류 목록에 B/L 없음) — severity=info, 심사
#     결과에 실질적 영향이 없는 참고 항목이라 하자 주입 대상으로 부적합하다.

# ---------------------------------------------------------------------------
# 룰 밖 하자 (35%, 설계서 1절 필수 조건) — HANDOFF.md 4b단계로 5종 추가.
#
# 엔진은 B/L·L/C 만 받고 송장·포장명세서 필드를 아예 입력받지 않으므로(설계서
# 5.3.1 "룰 밖" 표), 아래 5종은 상수를 조작하지 않아도 **구조적으로** 룰 밖이다.
# 나머지 중 freeform_47a_unmet 은 9단계(설계서 §5.3.2, HANDOFF.md)에서 검증불가
# 혼합비 이동으로 재설계됐다 — 아래 함수 정의부의 FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE
# 참고. 그 외는 v3 중첩 설계를 그대로 유지한다(변경 없음).
#
# ⚠️ 워터마크 위험(HANDOFF.md 4b단계 Task 3, 3절 "되돌린 시도"가 이미 두 번
# 잡아낸 함정과 동종). qty/weight/amount_deviation_ratio 는 무하자 건에서
# 정확히 0.0000이었다 — generator.py 가 이제 무하자 건에도 자연 변동을 주므로
# (natural_deviation_ratio), 아래 하자들은 **같은 함수 위에 추가 이동**만
# 얹는다(새 축을 만들지 않는다, 설계서 5.3 "무하자 건에도 같은 축의 변동을
# 준다").
# ---------------------------------------------------------------------------


def _apply_qty_sum_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # 흔적 축: dc_qty_deviation_ratio. generator.py 의 무하자 자연 변동
    # (base_hi=0.05)과 같은 함수에 우측 꼬리 이동(extra_hi=0.15)을 더한다 —
    # 하자 최솟값이 무하자 상한과 겹친다(완전분리 방지).
    dev = natural_deviation_ratio(rng, base_hi=0.05, extra_hi=0.15)
    sign = rng.choice((-1, 1))
    s.packing_list_qty_sum = max(0, round(s.package_qty * (1 + sign * dev)))


def _apply_weight_sum_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # 흔적 축: dc_weight_deviation_ratio. 계량 방식 차이(포장명세서 합산 vs
    # B/L 총중량)라는 현실적 서사와 같은 축 — qty 와 동일한 패턴.
    dev = natural_deviation_ratio(rng, base_hi=0.04, extra_hi=0.15)
    sign = rng.choice((-1, 1))
    s.packing_list_weight_sum = max(0.0, round(s.gross_weight_kg * (1 + sign * dev), 1))


def _apply_invoice_amount_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # 흔적 축: dc_amount_deviation_ratio(amount_tolerance_boundary 개명).
    # computed_amount(=package_qty × unit_price_usd, dataset.py 가 재계산)와
    # 대조되는 invoice_amount_usd 를 그 위에서 이동시킨다.
    dev = natural_deviation_ratio(rng, base_hi=0.05, extra_hi=0.08)
    sign = rng.choice((-1, 1))
    computed = s.package_qty * s.unit_price_usd
    s.invoice_amount_usd = round(max(0.01, computed * (1 + sign * dev)), 2)


def _apply_invoice_consignee_mismatch(s: SynthShipment, rng: random.Random) -> None:
    # 흔적 축: dc_party_name_mismatch_count / dc_max_edit_distance_ratio
    # (consignee_mismatch 개명). 송장 수하인만 바꾼다 — B/L consignee 는 그대로라
    # 엔진(D005B)은 못 본다. 예전엔 고정 문자열 " (TRADING DIV.)" 을 100% 확률로
    # 붙였는데, 실측 AUC 0.970(거의 완전분리) — HANDOFF.md 3절이 이미 잡아낸 것과
    # 같은 종류의 워터마크였다. generator.py 의 무하자 자연 변동(vary_company_suffix,
    # strength=0.25)과 같은 vary_wording 계열을 더 큰 강도로 적용해 goods_wording_diff
    # 와 같은 패턴(설계서 5.3 "무하자 건에도 같은 축의 변동을 준다")으로 겹치게 한다.
    # 항상 적용하면(구 코드가 그랬듯) 무하자 건의 goods_description 짝이 이미 자주
    # 임계값(0.15)을 넘는 상태 위에 consignee 짝까지 거의 매번 넘겨 실측 AUC가
    # 0.85 를 넘었다 — 확률적으로만 적용해 무하자 분포와 겹치는 몫을 남긴다.
    if rng.random() < 0.5:
        s.invoice_consignee = vary_wording(s.invoice_consignee, rng, ratio_range=(0.10, 0.30))


def _apply_insufficient_originals(s: SynthShipment, rng: random.Random) -> None:
    # 흔적 없음(설계서 5.3.1 표) — original_bl_count 를 보는 룰이 카탈로그에
    # 없고 Group 2 비교 대상에도 없다. 구조적으로 룰 밖.
    s.original_bl_count = max(0, s.required_original_count - rng.randint(1, s.required_original_count))


# 하자의 검증불가 혼합비 범위(설계서 §5.3.2). generator.CLEAN_47A_UNVERIFIABLE_RATIO_RANGE
# (0.0~0.6)와 0.3~0.6 구간에서 겹친다 — 하자는 혼합비를 "이동"시킬 뿐 "분리"하지
# 않는다(중첩 요건, 설계서 1절). 0.0(전부 검증가능)이나 1.0(전부 검증불가) 같은
# 자연 분포 밖 값으로 클램프하지 않는다 — HANDOFF.md 3절이 이미 세 번 잡아낸
# 워터마크 패턴과 동종.
FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE: tuple[float, float] = (0.3, 0.9)


def _apply_freeform_47a_unmet(s: SynthShipment, rng: random.Random) -> None:
    # 룰엔진은 :47A: 자유서식 조건의 이행 여부를 구조적으로 판단할 수 없다
    # (covered_by_rule=False). 이 하자가 남기는 흔적은 조건 "개수"가 아니라
    # 검증불가 조건의 "혼합비"다(설계서 §5.3.2 — 개수만 바뀌면
    # llm_47a_verifiable_ratio 가 lc_47a_condition_count 의 개명일 뿐이라 무정보가
    # 된다). generator.sample_47a_conditions() 를 그대로 재사용하되 혼합비 범위만
    # FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE 로 이동시킨다 — 조건 개수(무하자 건
    # 생성 시 이미 정해진 1~6개)는 그대로 두고 :47A: 텍스트 전체를 다시 뽑는다
    # (다른 인젝터 함수처럼 필드를 통째로 재계산하는 패턴, 예: _apply_qty_sum_mismatch).
    # 문구는 여전히 무하자 건과 동일한 두 공용 풀에서만 나온다 — 하자에만 등장하는
    # 고정 문자열은 없다(설계서 5.3, HANDOFF.md 3절).
    if not s.lc_present:
        return
    condition_count = len([c for c in s.lc_47a_text.split(";") if c.strip()])
    if condition_count == 0:
        condition_count = rng.randint(1, 6)
    s.lc_47a_text = generator.sample_47a_conditions(
        rng, condition_count, FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE
    )


def _apply_goods_wording_diff(s: SynthShipment, rng: random.Random) -> None:
    # 무하자 건이 이미 갖는 품명 표기 변동(약어·어순·문자 편집, generator.py)을
    # 더 큰 강도로 이어서 적용한다 — 새 토큰이 아니라 같은 축의 이동이다.
    # 결과 dc_max_edit_distance_ratio 는 무하자 분포(약 0.00~0.40)와 겹치는
    # 구간(약 0.15~0.60)에 놓인다(설계서 5.3 표).
    s.invoice_goods_description = vary_wording(
        s.invoice_goods_description, rng, ratio_range=(0.15, 0.55)
    )


def _apply_signer_authority_ambiguous(s: SynthShipment, rng: random.Random) -> None:
    # 룰엔진은 서명 자격을 구조적으로 판단할 수 없다(covered_by_rule=False).
    # 흔적을 아예 남기지 않으면 라벨 노이즈로만 작용하므로(설계서 5.3 요건 3),
    # eq_min_confidence·dc_party_name_mismatch_count 에 약하고 확률적인 하향
    # 이동을 준다 — 두 피처 모두 무하자 건도 자연 변동을 갖는 축이라 겹친다.
    party_fields = [f for f in ("shipper", "consignee") if f in s.field_confidences]
    if party_fields and rng.random() < 0.5:
        field = rng.choice(party_fields)
        s.field_confidences[field] = max(0.0, s.field_confidences[field] - rng.uniform(0.03, 0.12))
    if rng.random() < 0.35:
        s.consignee = generator.vary_company_suffix(s.consignee, rng, strength=0.6)


def _apply_customary_wording_missing(s: SynthShipment, rng: random.Random) -> None:
    # 관행 문구 누락도 룰엔진이 구조적으로 볼 수 없다(covered_by_rule=False).
    # generator.py 가 무하자 건에도 이미 부여한 admin_note_conflict 자연 확률
    # (약 7%)을 이동시킬 뿐이다 — dc_conflict_field_count 는 새 피처가 아니라
    # 기존 포트 불일치 신호와 공유하는 축이라 자연 분포와 겹친다.
    if rng.random() < 0.4:
        s.admin_note_conflict = True


UNCOVERED_SPECS: tuple[DefectSpec, ...] = (
    DefectSpec("qty_sum_mismatch", 1.0, "WARNING", "packing_list_qty_sum", False, _apply_qty_sum_mismatch),
    DefectSpec("weight_sum_mismatch", 1.0, "WARNING", "packing_list_weight_sum", False, _apply_weight_sum_mismatch),
    DefectSpec("invoice_amount_mismatch", 1.0, "WARNING", "invoice_amount_usd", False, _apply_invoice_amount_mismatch),
    DefectSpec("invoice_consignee_mismatch", 1.0, "CRITICAL", "invoice_consignee", False, _apply_invoice_consignee_mismatch),
    DefectSpec("insufficient_originals", 1.0, "CRITICAL", "original_bl_count", False, _apply_insufficient_originals),
    DefectSpec("freeform_47a_unmet", 1.0, "WARNING", "lc_47a_text", False, _apply_freeform_47a_unmet),
    DefectSpec("goods_wording_diff", 1.0, "INFO", "goods_description", False, _apply_goods_wording_diff),
    DefectSpec("signer_authority_ambiguous", 0.8, "WARNING", "signature", False, _apply_signer_authority_ambiguous),
    DefectSpec("customary_wording_missing", 0.8, "INFO", "clause_text", False, _apply_customary_wording_missing),
)

ALL_SPECS: dict[str, DefectSpec] = {s.type: s for s in COVERED_SPECS + UNCOVERED_SPECS}

# 부류 간 목표 비율(설계서 5.3) — 개별 주입 "건수" 기준 65:35.
COVERED_MASS = 0.65
UNCOVERED_MASS = 0.35

_COVERED_WEIGHTS = [s.weight for s in COVERED_SPECS]
_UNCOVERED_WEIGHTS = [s.weight for s in UNCOVERED_SPECS]

# 하자 개수 분포(선적당). 최종 하자율(기획안 2장 실제 수치 65~75%)에 맞도록
# review.py 파라미터(P_DETECT, lenient_rate)와 함께 경험적으로 보정한 값이다
# (설계서 5.5: "전체 하자율이 65~75%에 맞도록 파라미터를 조정한다").
# 하자 개수만으로는 y 가 정해지지 않는다 — 채널 B 가 독립적으로 판정한다.
DEFECT_COUNT_WEIGHTS = {0: 0.10, 1: 0.30, 2: 0.35, 3: 0.25}


def inject_defects(
    shipment: SynthShipment, rng: random.Random
) -> tuple[SynthShipment, list[Defect]]:
    """선적 사본에 0~3건의 하자를 주입하고 (오염된 사본, 주입 내역) 을 반환한다."""
    mutated = shipment.copy()
    n = rng.choices(
        list(DEFECT_COUNT_WEIGHTS.keys()), weights=list(DEFECT_COUNT_WEIGHTS.values()), k=1
    )[0]
    defects: list[Defect] = []
    used_types: set[str] = set()
    for _ in range(n):
        is_covered = rng.random() < COVERED_MASS
        pool = COVERED_SPECS if is_covered else UNCOVERED_SPECS
        weights = _COVERED_WEIGHTS if is_covered else _UNCOVERED_WEIGHTS
        # 같은 종류 중복 주입을 피한다(현실적인 하자 다양성)
        candidates = [s for s in pool if s.type not in used_types] or list(pool)
        cand_weights = [weights[pool.index(c)] for c in candidates]
        spec = rng.choices(candidates, weights=cand_weights, k=1)[0]
        spec.apply(mutated, rng)
        used_types.add(spec.type)
        defects.append(Defect(spec.type, spec.field, spec.severity, spec.covered_by_rule))
    return mutated, defects

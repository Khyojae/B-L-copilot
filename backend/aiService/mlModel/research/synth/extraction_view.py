"""[채널 A] 관측 노이즈 계층 (설계서 5.4).

**왜 이 모듈이 존재하는가.**

v3 의 `rule_sim.py` 는 룰 발화를 흉내 내면서 FN/FP 를 `RULE_FIRE_PROB_RANGE`,
`RULE_SPURIOUS_FIRE_PROB_RANGE` 라는 **임의로 고른 상수 두 개**로 만들었다.
v4 부터는 실제 룰엔진이 돈다. 실제 엔진은 결정론적이므로 그 자체로는 FN/FP 가 없다.

그런데 실무에서 룰엔진은 **진실 위에서 돌지 않는다 — OCR 로 추출한 값 위에서 돈다.**
따라서 FN 과 FP 는 둘 다 "룰이 틀렸다"가 아니라 **"룰이 보는 입력이 틀렸다"** 라는
하나의 메커니즘에서 파생된다. 이 편이 v3 보다 네 가지 면에서 낫다.

1. FN·FP 가 발명한 상수 2개가 아니라 **한 메커니즘**에서 나온다.
2. 노이즈 크기가 **실측치**(`load_field_accuracy()`, AI Hub 평가 리포트)에 근거한다.
3. 판정불가(not-evaluated) 피처가 장식이 아니라 **인과적**이 된다 — 날짜가 뭉개지면
   실제로 파싱에 실패해 룰이 판정불가가 된다.
4. 실서비스와 **같은 구조**라 train/serve 스큐가 사라진다.

**L/C 는 훼손하지 않는다.** 제품에서 L/C 는 MT700 구조화 텍스트로 들어오지 OCR 을
거치지 않는다. L/C 를 훼손하면 일어나지 않는 일을 모델링하게 된다.

**채널 독립(설계서 1절).** 이 모듈은 `review.py` 를 import 하지 않으며 그 반대도
마찬가지다. 주입된 하자 내역(`injected_defects`)도 보지 않는다 — 오직 선적의
필드 신뢰도만 보고 훼손한다.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from f3_research import config
from f3_research.synth.generator import SynthShipment

# 신뢰도 딕셔너리의 키는 B/L 서류 필드명이다. 그 키를 SynthShipment 의 실제
# 속성명으로 옮긴다(어댑터의 매핑과 같은 방향).
_CONF_KEY_TO_ATTR: dict[str, str] = {
    "bl_no": "bl_no",
    "shipper": "shipper",
    "consignee": "consignee",
    "port_of_loading": "port_of_loading",
    "port_of_discharge": "port_of_discharge",
    "date_of_issue": "bl_issue_date",
    "gross_weight": "gross_weight_kg",
}

# 훼손 대상은 B/L 측 필드뿐이다. lc_* 는 절대 건드리지 않는다(위 docstring 참고).
_TEXT_ATTRS = frozenset(
    {"bl_no", "shipper", "consignee", "port_of_loading", "port_of_discharge"}
)
_DATE_ATTRS = frozenset({"bl_issue_date"})
_NUMERIC_ATTRS = frozenset({"gross_weight_kg"})

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _lerp(at_full: float, at_zero: float, confidence: float) -> float:
    """신뢰도 → 확률. 신뢰도 1.0 에서 at_full, 0.0 에서 at_zero 로 선형 보간한다."""
    c = max(0.0, min(1.0, confidence))
    return at_zero + (at_full - at_zero) * c


def _garble_text(value: str, rng: random.Random) -> str:
    """문자 단위 편집을 1~3회 가한다(OCR 오독 모사)."""
    if not value:
        return value
    chars = list(value)
    ops = rng.randint(*config.EXTRACTION_GARBLE_TEXT_OPS_RANGE)
    for _ in range(ops):
        if not chars:
            break
        i = rng.randrange(len(chars))
        kind = rng.random()
        if kind < 0.5:  # 치환 — 가장 흔한 OCR 오류
            chars[i] = rng.choice(_ALPHABET)
        elif kind < 0.8:  # 탈락
            del chars[i]
        else:  # 삽입
            chars.insert(i, rng.choice(_ALPHABET))
    return "".join(chars)


def _garble_date(value: date, rng: random.Random) -> date:
    """날짜를 ±N일 이동시킨다. 0일 이동은 노이즈가 아니므로 제외한다."""
    span = config.EXTRACTION_GARBLE_DATE_MAX_SHIFT_DAYS
    shift = 0
    while shift == 0:
        shift = rng.randint(-span, span)
    return value + timedelta(days=shift)


def _garble_numeric(value: float, rng: random.Random) -> float:
    """수치를 상대 비율로 왜곡한다(자릿수 오독 모사)."""
    lo, hi = config.EXTRACTION_GARBLE_NUMERIC_JITTER_RANGE
    ratio = rng.uniform(lo, hi) * rng.choice([-1, 1])
    return round(value * (1 + ratio), 2)


def _drop_value(attr: str) -> Any:
    """필드를 '추출 실패' 상태로 만든다 — 룰은 이걸 누락/판정불가로 본다."""
    if attr in _DATE_ATTRS or attr in _NUMERIC_ATTRS:
        return None
    return ""


def extraction_view(shipment: SynthShipment, rng: random.Random) -> SynthShipment:
    """진실 선적으로부터 **룰엔진이 실제로 보게 될 관측 사본**을 만든다.

    설계서 5.4: 훼손 확률은 선적이 이미 들고 있는 `field_confidences` /
    `missing_fields` / `no_evidence_fields` 에서 나온다. 이 값들은 생성기가
    **실측 필드별 OCR 정확도**로 채운 것이므로, 노이즈 크기가 발명한 상수가 아니라
    측정치에 근거한다.

    반환된 사본은 채널 A(룰엔진 + LLM 피처) 전용이다. 채널 B(`review.py`)는
    **진실**을 심사한다 — 그래야 "관측이 틀려서 룰이 놓친 하자"가 라벨에는 남는다.
    """
    observed = shipment.copy()

    for conf_key, attr in _CONF_KEY_TO_ATTR.items():
        if not hasattr(observed, attr):
            continue

        value = getattr(observed, attr)
        if value is None or value == "":
            continue  # 이미 비어 있으면 더 훼손할 것이 없다

        # 생성기가 이미 누락으로 표시한 필드는 확정 드랍한다.
        if conf_key in observed.missing_fields:
            setattr(observed, attr, _drop_value(attr))
            continue

        confidence = observed.field_confidences.get(conf_key, 1.0)

        drop_p = _lerp(
            config.EXTRACTION_DROP_PROB_AT_FULL_CONF,
            config.EXTRACTION_DROP_PROB_AT_ZERO_CONF,
            confidence,
        )
        garble_p = _lerp(
            config.EXTRACTION_GARBLE_PROB_AT_FULL_CONF,
            config.EXTRACTION_GARBLE_PROB_AT_ZERO_CONF,
            confidence,
        )
        # 근거 문자열을 못 찾은 필드는 "값은 있으나 신뢰 불가" 상태다 —
        # 드랍보다 왜곡 쪽으로 확률 하한을 둔다(설계서 5.4).
        if conf_key in observed.no_evidence_fields:
            garble_p = max(garble_p, config.EXTRACTION_GARBLE_PROB_NO_EVIDENCE_FLOOR)

        roll = rng.random()
        if roll < drop_p:
            setattr(observed, attr, _drop_value(attr))
        elif roll < drop_p + garble_p:
            if attr in _TEXT_ATTRS:
                setattr(observed, attr, _garble_text(str(value), rng))
            elif attr in _DATE_ATTRS:
                setattr(observed, attr, _garble_date(value, rng))
            elif attr in _NUMERIC_ATTRS:
                setattr(observed, attr, _garble_numeric(float(value), rng))

    return observed

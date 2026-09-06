"""
검사 함수 레지스트리.

각 함수는 `(bl, lc, rule) -> CheckOutcome` 이다. 룰 YAML 의 `check` 값이
여기 등록된 이름을 가리킨다.

세 가지 결과를 돌려줄 수 있다.

- `passed()`        : 검사했고 문제없음
- `violated(...)`   : 검사했고 위반
- `not_evaluated(…)`: 판단할 근거가 없음 (L/C 조건 미명시, 날짜 파싱 실패 등)

세 번째가 핵심이다. 이걸 '통과'로 뭉개면 입력이 나쁠수록 하자가 적어 보이는
역전이 생긴다. 하자 예측 시스템에서 이 역전은 치명적이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .types import LCTerms

# 항구·도시 이명. UN/LOCODE 로 정규화하기 전의 임시 테이블이며
# F2(표준 용어 교정)가 들어오면 그쪽으로 옮긴다.
PORT_SYNONYMS: List[frozenset] = [
    frozenset({"BUSAN", "PUSAN"}),
    frozenset({"INCHEON", "INCHON"}),
    frozenset({"GUANGZHOU", "CANTON"}),
    frozenset({"MUMBAI", "BOMBAY"}),
    frozenset({"CHENNAI", "MADRAS"}),
    frozenset({"KOLKATA", "CALCUTTA"}),
    frozenset({"BEIJING", "PEKING"}),
    frozenset({"TROMSOE", "TROMSO"}),
    frozenset({"JEDDAH", "JEDDA"}),
]

# 회사 형태 표기. 당사자명 비교에서 제거한다 —
# "CO., LTD." 유무로 불일치 판정이 나면 오탐이 폭증한다.
_LEGAL_SUFFIXES = {
    "CO", "LTD", "INC", "CORP", "LLC", "GMBH", "PTE", "PVT",
    "LIMITED", "COMPANY", "CORPORATION", "AG", "SA", "BV", "NV",
}

DATE_FORMATS = (
    "%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y",
    "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    "%d %b %Y", "%d %B %Y",
    "%b %d, %Y", "%B %d, %Y",
    "%b %d %Y", "%B %d %Y",
    "%d-%b-%Y", "%d-%B-%Y",
)

INCOTERMS = (
    "EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
    "CPT", "CIP", "DAP", "DPU", "DDP",
)

# 토큰 겹침이 이 비율 이상이면 일치로 본다. 1.0 으로 잡으면 표기 흔들림에
# 전부 걸리고, 너무 낮추면 다른 항구가 통과한다.
MATCH_THRESHOLD = 0.6


@dataclass
class CheckOutcome:
    """검사 1건의 결과."""

    evaluated: bool
    violated: bool
    reason: str = ""                      # 평가불가 사유
    detail: str = ""                      # 메시지 {detail} 치환값
    observed: Optional[Dict[str, Optional[str]]] = None
    # True면 엔진이 rule의 severity/title/message 대신 고정된 "형식 오류"
    # 경고로 렌더링한다 (P1-15). 룰 본연의 위반(예: 기한 초과)과 섞이면
    # 안 되므로 별도 플래그로 구분한다.
    format_error: bool = False

    @property
    def bl_value(self) -> Optional[str]:
        return (self.observed or {}).get("bl")

    @property
    def lc_value(self) -> Optional[str]:
        return (self.observed or {}).get("lc")


def passed(**observed) -> CheckOutcome:
    return CheckOutcome(evaluated=True, violated=False, observed=_clean(observed))


def violated(detail: str = "", **observed) -> CheckOutcome:
    return CheckOutcome(
        evaluated=True, violated=True, detail=detail, observed=_clean(observed)
    )


def not_evaluated(reason: str, **observed) -> CheckOutcome:
    return CheckOutcome(
        evaluated=False, violated=False, reason=reason, observed=_clean(observed)
    )


def format_error(reason: str, **observed) -> CheckOutcome:
    """날짜처럼 파싱 자체가 실패한 입력을 '평가불가'로 숨기지 않고 형식
    오류 위반(warning)으로 드러낸다.

    OCR 산출물 특성상 형식이 깨진 날짜는 흔한 입력인데, not_evaluated로
    처리하면 SkippedRule로만 남아 리포트 위반 목록에는 아예 안 보인다(P1-15).
    """
    return CheckOutcome(
        evaluated=True, violated=True, format_error=True, reason=reason,
        observed=_clean(observed),
    )


def _clean(observed: dict) -> Dict[str, Optional[str]]:
    return {k: (str(v) if v is not None else None) for k, v in observed.items()}


# ── 값 꺼내기 ────────────────────────────────────────────────────

def field_value(bl, name: str) -> Optional[str]:
    """B/L 필드 하나를 꺼낸다. dict 와 BLFields 를 모두 받는다.

    두 형태가 다 들어온다. F1 파이프라인은 BLFields 객체를 주지만,
    S3 편집기에서 사람이 고친 값과 API 요청 본문은 dict 로 온다.

    getattr 하나로 처리하면 dict 가 들어왔을 때 모든 필드가 None 이 되고,
    그 결과는 예외가 아니라 '전 필드 누락'이라는 **틀린 검증 결과**로 나온다.
    정상 서류에 없는 하자가 날조되므로, 알 수 없는 형태는 조용히 넘기지 않고
    바로 터뜨린다.
    """
    if isinstance(bl, Mapping):
        value = bl.get(name)
    elif hasattr(bl, name) or hasattr(bl, "__dataclass_fields__"):
        value = getattr(bl, name, None)
    else:
        raise TypeError(
            f"B/L 은 dict 또는 BLFields 여야 합니다 (받은 형: {type(bl).__name__})"
        )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_present(bl, names: List[str]) -> tuple[Optional[str], Optional[str]]:
    """룰의 fields 중 값이 있는 첫 필드를 (이름, 값)으로 돌려준다."""
    for name in names:
        value = field_value(bl, name)
        if value:
            return name, value
    return (names[0] if names else None), None


def _rule_fields(rule: dict) -> List[str]:
    return list(rule.get("fields") or [])


# ── 검사 함수 ────────────────────────────────────────────────────

def required(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """필드가 비어 있으면 위반."""
    names = _rule_fields(rule)
    if not names:
        return not_evaluated("룰에 검사 대상 필드가 없습니다")

    name, value = _first_present(bl, names)
    if value:
        return passed(bl=value)
    return violated(detail=name or "", bl=None)


def required_if_lc(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 가 해당 조건을 지정한 경우에만 필수.

    `required` 와 나누는 이유는 통지처 같은 항목 때문이다. B/L 번호나 수하인은
    L/C 와 무관하게 없으면 하자지만, 통지처는 **L/C 가 지정했을 때만** 하자다.
    지정이 없는데도 하자로 세면 정상 서류에 없는 하자를 만들어낸다.

    지정이 없으면 `not_evaluated` 다. `passed` 가 아니다 — 검사한 결과 통과한
    것과 검사 대상이 아니었던 것은 다르고, 그 차이가 리포트에 드러나야 한다.
    """
    names = _rule_fields(rule)
    if not names:
        return not_evaluated("룰에 검사 대상 필드가 없습니다")

    lc_value = lc.get(rule.get("lc_field", ""))
    name, value = _first_present(bl, names)

    if not lc_value:
        return not_evaluated("L/C 에 해당 조건이 명시되지 않았습니다", bl=value)
    if value:
        return passed(bl=value, lc=lc_value)
    return violated(detail=name or "", bl=None, lc=lc_value)


def match_place(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """서류 값이 L/C 지정 값과 맞는지. 항구 이명과 법인격 표기를 흡수한다."""
    names = _rule_fields(rule)
    lc_value = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, names)

    if not lc_value:
        return not_evaluated("L/C 에 해당 조건이 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        # 누락은 required 룰이 따로 잡는다. 여기서 또 세면 이중 계상된다.
        return not_evaluated("서류에 값이 없습니다", lc=lc_value)

    if _tokens_match(bl_value, str(lc_value)):
        return passed(bl=bl_value, lc=lc_value)
    return violated(bl=bl_value, lc=lc_value)


def contains_keywords(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 명세의 키워드가 서류 명세에 모두 있는지."""
    names = _rule_fields(rule)
    lc_value = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, names)

    if not lc_value:
        return not_evaluated("L/C 에 물품 명세가 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        return not_evaluated("서류에 물품 명세가 없습니다", lc=lc_value)

    haystack = bl_value.upper()
    keywords = [k.strip().upper() for k in str(lc_value).split(",") if k.strip()]
    missing = [k for k in keywords if k not in haystack]

    if missing:
        return violated(detail=", ".join(missing), bl=bl_value, lc=lc_value)
    return passed(bl=bl_value, lc=lc_value)


def date_not_after(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """서류 날짜가 L/C 기한을 넘지 않았는지."""
    names = _rule_fields(rule)
    lc_value = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, names)

    if not lc_value:
        return not_evaluated("L/C 에 해당 기한이 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        return not_evaluated("서류에 해당 날짜가 없습니다", lc=lc_value)

    bl_date = parse_date(bl_value)
    lc_date = parse_date(str(lc_value))
    if bl_date is None:
        return format_error(f"서류 날짜를 해석할 수 없습니다: {bl_value}",
                             bl=bl_value, lc=lc_value)
    if lc_date is None:
        return format_error(f"L/C 날짜를 해석할 수 없습니다: {lc_value}",
                             bl=bl_value, lc=lc_value)

    if bl_date > lc_date:
        overdue = (bl_date - lc_date).days
        return violated(detail=str(overdue), bl=bl_value, lc=lc_value)
    return passed(bl=bl_value, lc=lc_value)


def presentation_before_expiry(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 유효기일(31D)이 제시 시점 이전인지 (UCP 600 Art.6(d)·14(a)).

    은행은 서류의 **발행일이 아니라 제시일** 기준으로 유효기일을 본다.
    발행일이 기간 안이어도 제시가 유효기일을 넘기면 하자고, 반대로 발행이
    다소 늦었어도 유효기일 전에 제시하면 문제되지 않는다. 그래서 이 검사는
    서류의 어떤 날짜도 참조하지 않고 L/C 유효기일과 제시 시점(as_of)만
    비교한다 — `fields` 는 화면의 필드 바로가기 용도로만 쓰인다.
    """
    lc_value = lc.expiry_date
    if not lc_value:
        return not_evaluated("L/C 에 유효기일이 명시되지 않았습니다")

    expiry = parse_date(str(lc_value))
    if expiry is None:
        return format_error(
            f"L/C 유효기일을 해석할 수 없습니다: {lc_value}", lc=lc_value
        )

    # 기준 시각을 인자로 받지 않고 now() 를 쓰면 테스트가 날짜에 따라
    # 흔들린다. 엔진이 as_of 를 주입한다.
    as_of = rule.get("_as_of") or datetime.now()

    if as_of.date() > expiry.date():
        elapsed = (as_of.date() - expiry.date()).days
        return violated(detail=str(elapsed), lc=lc_value)
    return passed(lc=lc_value)


def presentation_period(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """선적일로부터 제시기간이 지났는지 (UCP 600 Art.14(c)).

    기한의 정의는 `deadline.due_from` 하나뿐이다. F4 리포트가 같은 날짜를
    따로 계산하다 어긋난 적이 있어 한 곳으로 모았다.

    **유효기일(31D)은 여기서 보지 않는다.** 그쪽은 별도 룰이 잡으므로 함께
    판정하면 같은 하자가 두 번 계상된다. 사용자에게 "언제까지"를 하나로
    답해야 하는 리포트만 둘을 합친다.
    """
    from .deadline import due_from, presentation_days

    names = _rule_fields(rule)
    _, bl_value = _first_present(bl, names)
    if not bl_value:
        return not_evaluated("서류에 선적일이 없습니다")

    shipped = parse_date(bl_value)
    if shipped is None:
        return format_error(f"선적일을 해석할 수 없습니다: {bl_value}", bl=bl_value)

    days = presentation_days(lc)
    # 기준 시각을 인자로 받지 않고 now() 를 쓰면 테스트가 날짜에 따라 흔들린다.
    # 엔진이 as_of 를 주입한다.
    as_of = rule.get("_as_of") or datetime.now()

    if as_of.date() > due_from(shipped, lc):
        # 메시지는 "며칠 지났는지"를 말한다. 기한 날짜보다 경과 일수가
        # 사용자에게 바로 읽힌다.
        elapsed = (as_of - shipped).days
        return violated(detail=str(elapsed), bl=bl_value, lc=str(days))
    return passed(bl=bl_value, lc=str(days))


def date_not_in_future(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """서류 날짜가 제시 시점보다 미래인지 (ISBP 821 — 날짜).

    서류는 제시일보다 늦은 날짜로 발행될 수 없다. 발행일이 미래라는 것은
    오탈자이거나 선일자 발행이며, 어느 쪽이든 은행이 짚는다.

    다른 날짜 룰과 달리 **L/C 를 보지 않는다.** 서류 하나만으로 판정되는
    내부 정합성 검사라 L/C 가 없어도 평가된다 — L/C 없이 돌릴 때 대부분의
    룰이 평가불가로 빠지는 상황에서, 이런 룰이 실제 검사 범위를 넓혀 준다.
    """
    names = _rule_fields(rule)
    _, bl_value = _first_present(bl, names)
    if not bl_value:
        return not_evaluated("서류에 해당 날짜가 없습니다")

    issued = parse_date(bl_value)
    if issued is None:
        return format_error(f"서류 날짜를 해석할 수 없습니다: {bl_value}", bl=bl_value)

    as_of = rule.get("_as_of") or datetime.now()
    if issued > as_of:
        ahead = (issued - as_of).days
        return violated(detail=str(ahead), bl=bl_value, lc=as_of.strftime("%Y-%m-%d"))
    return passed(bl=bl_value)


def numeric_not_above(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """수치가 L/C 한도를 넘지 않았는지."""
    names = _rule_fields(rule)
    limit = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, names)
    unit = rule.get("unit", "")

    if limit is None:
        return not_evaluated("L/C 에 해당 한도가 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        return not_evaluated("서류에 해당 수치가 없습니다", lc=f"{limit} {unit}".strip())

    amount = parse_quantity(bl_value, unit)
    if amount is None:
        return not_evaluated(f"수치를 해석할 수 없습니다: {bl_value}", bl=bl_value)

    lc_display = f"{limit} {unit}".strip()
    if amount > float(limit):
        return violated(detail=f"{amount:g}", bl=bl_value, lc=lc_display)
    return passed(bl=bl_value, lc=lc_display)


def within_tolerance(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """금액이 L/C 허용 오차 범위 안인지 (UCP 600 Art.30)."""
    names = _rule_fields(rule)
    target = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, names)

    if target is None:
        return not_evaluated("L/C 에 해당 금액이 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        return not_evaluated("서류에 해당 금액이 없습니다", lc=str(target))

    amount = parse_amount(bl_value)
    if amount is None:
        return not_evaluated(f"금액을 해석할 수 없습니다: {bl_value}", bl=bl_value)

    tol = lc.tolerance_pct / 100.0
    low, high = float(target) * (1 - tol), float(target) * (1 + tol)
    lc_display = f"{target:,.2f} {lc.currency} ±{lc.tolerance_pct:g}%"

    if not low <= amount <= high:
        return violated(
            detail=f"{low:,.2f}~{high:,.2f}", bl=bl_value, lc=lc_display
        )
    return passed(bl=bl_value, lc=lc_display)


def forbidden_when_prohibited(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 가 금지한 조건의 표시가 서류에 있는지."""
    flag = str(lc.get(rule.get("lc_flag", "")) or "").upper()
    if flag != "PROHIBITED":
        return not_evaluated("L/C 가 금지 조건이 아닙니다")

    haystack = " ".join(
        field_value(bl, name) or "" for name in _rule_fields(rule)
    ).upper()
    if not haystack.strip():
        return not_evaluated("검사할 서류 내용이 없습니다")

    for keyword in rule.get("keywords", []):
        if keyword.upper() in haystack:
            return violated(detail=keyword, bl=keyword)
    return passed()


def contains_forbidden(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """서류에 있어서는 안 되는 문언이 있는지. **L/C 조건을 보지 않는다.**

    `forbidden_when_prohibited` 와 나눈 이유가 여기다. 그쪽은 L/C 가 금지했을
    때만 켜지는 조건부 룰이라 신용장이 침묵하면 평가불가로 빠진다. 이쪽은
    신용장이 무엇을 말하든 서류 자체가 하자인 문언 — 고장 문언(UCP 600
    Art.27), 예정 선박 표시, 특정되지 않은 항구 — 을 잡는다. 조건부 룰로
    만들면 L/C 없이 돌릴 때 통째로 검사되지 않는다.

    **부분 문자열이 아니라 낱말 단위로 본다.** `forbidden_when_prohibited` 는
    "PARTIAL SHIPMENT" 처럼 긴 구를 찾으므로 부분 일치로 충분하지만, 여기
    키워드는 "WET"·"TORN" 처럼 짧다. 부분 일치로 두면 "WETSUIT" 이 고장
    문언으로 잡힌다. 오탐 하나가 정상 서류를 반려시키는 룰이라 좁게 잡는다.
    """
    names = _rule_fields(rule)
    keywords = [str(k).upper() for k in rule.get("keywords", [])]
    if not keywords:
        return not_evaluated("룰에 검사할 문언이 없습니다")

    # 금지어가 있어도 함께 있으면 하자가 아닌 것으로 보는 예외 문구.
    # 예: "MAY BE CARRIED ON DECK"(가능성 표기)는 UCP 600 Art.26(b) 상
    # 허용되지만, 그 문장은 "CARRIED ON DECK" 도 포함하므로 예외가 없으면
    # 정상 서류가 오탐된다. D029 만 이 값을 쓴다.
    unless_keywords = [str(k).upper() for k in rule.get("unless_keywords", [])]

    for name in names:
        value = field_value(bl, name)
        if not value:
            continue
        haystack = value.upper()
        for keyword in keywords:
            if not re.search(rf"\b{re.escape(keyword)}\b", haystack):
                continue
            if any(
                re.search(rf"\b{re.escape(uk)}\b", haystack)
                for uk in unless_keywords
            ):
                continue
            return violated(detail=keyword, bl=value)

    # 대상 필드가 전부 비어 있으면 '문언이 없다'가 아니라 '볼 것이 없다'다.
    # 누락은 required 룰이 따로 잡는다.
    if not any(field_value(bl, name) for name in names):
        return not_evaluated("검사할 서류 내용이 없습니다")
    return passed()


# "선적을 위해 수령함" 문언. 본선적재 부기 없이 이 표현만 있으면 수취식
# B/L(received for shipment B/L)이다.
_RECEIVED_FOR_SHIPMENT_RE = re.compile(
    r"RECEIVED\s+(?:IN\s+APPARENT\s+GOOD\s+ORDER\s+)?FOR\s+SHIPMENT",
    re.IGNORECASE,
)


def on_board_required_when_received(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """수취식 문언이 있는데 본선적재 부기가 없는지 (UCP 600 Art.20(a)(ii)).

    "RECEIVED FOR SHIPMENT" 문언은 화물을 아직 선적하지 않고 수령만 했다는
    뜻이다. 신용장이 선적 선하증권을 요구하는 것이 원칙이므로, 이 문언이
    있는 서류는 별도의 On Board 표기(선적일)로 보완되어야 한다. 문언 자체가
    없으면 이 룰이 판단할 사안이 아니므로 평가불가로 둔다 — 수취식이 아닌
    서류에 "본선적재 부기 없음"을 하자로 세우면 정상 선적 B/L 대다수가
    걸린다.
    """
    clauses = field_value(bl, "bl_clauses")
    if not clauses or not _RECEIVED_FOR_SHIPMENT_RE.search(clauses):
        return not_evaluated("서류에 수취식(Received for Shipment) 문언이 없습니다")

    on_board = field_value(bl, "on_board_date")
    if on_board:
        return passed(bl=on_board)
    return violated(bl=None)


# 운임을 매도인이 부담하는 거래조건. B/L 의 운임 후불 표시와 저촉된다.
# 반대 방향(F·E 조건인데 운임 선불)은 넣지 않는다 — 아래 함수 주석 참고.
_FREIGHT_PREPAID_TERMS = ("CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")

_FREIGHT_COLLECT_WORDS = ("FREIGHT COLLECT", "COLLECT")


def freight_prepaid_required(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 거래조건이 운임 선불인데 서류가 후불로 표시했는지.

    CFR·CIF·CPT·CIP·D 조건은 매도인이 주운송비를 부담한다. 그 거래조건으로
    발행된 신용장에 "FREIGHT COLLECT" 선하증권을 제시하면 서류가 신용장의
    거래조건과 저촉된다.

    **반대 방향은 잡지 않는다.** FOB·FCA·EXW 인데 운임이 선불로 표시된
    경우는 매도인이 편의상 선지급한 것일 수 있고 은행이 이를 이유로 거절하지
    않는 것이 실무다. 대칭이 예뻐 보인다고 넣으면 정상 건이 하자로 잡힌다.
    기획안 9절의 '심각도 보수적 산정'이 이 방향을 가리킨다.
    """
    names = _rule_fields(rule)
    term = str(lc.get(rule.get("lc_field", "")) or "").upper()

    if not term:
        return not_evaluated("L/C 에 거래조건이 명시되지 않았습니다")
    base = next((t for t in _FREIGHT_PREPAID_TERMS if term.startswith(t)), None)
    if base is None:
        return not_evaluated(f"운임 선불 조건이 아닙니다: {term}", lc=term)

    # `_first_present` 를 쓰지 않는다. 운임 후불 표시는 운임란이 아니라 화물
    # 명세·비고에 찍히는 일이 많은데, 첫 필드만 보면 운임란에 금액이 있는 순간
    # 나머지를 보지 않는다. 값이 있을수록 검사가 줄어드는 역전이다.
    values = [(n, field_value(bl, n)) for n in names]
    present = [(n, v) for n, v in values if v]
    if not present:
        return not_evaluated("서류에 운임 표시가 없습니다", lc=term)

    for _, value in present:
        haystack = value.upper()
        for word in _FREIGHT_COLLECT_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", haystack):
                return violated(detail=word, bl=value, lc=term)
    return passed(bl=present[0][1], lc=term)


def contains_incoterms(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 지정 거래조건이 물품 명세에 표시되었는지."""
    lc_value = lc.get(rule.get("lc_field", ""))
    _, bl_value = _first_present(bl, _rule_fields(rule))

    if not lc_value:
        return not_evaluated("L/C 에 거래조건이 명시되지 않았습니다", bl=bl_value)
    if not bl_value:
        return not_evaluated("서류에 물품 명세가 없습니다", lc=lc_value)

    term = str(lc_value).upper()
    base = next((t for t in INCOTERMS if term.startswith(t)), term)
    if base in bl_value.upper():
        return passed(bl=bl_value, lc=lc_value)
    return violated(bl=bl_value, lc=lc_value)


# 지시식(TO ORDER) 문언. `mt700._TO_ORDER_RE` 와 같은 패턴이다 — 파서는
# L/C 46A 에서 요구 방식을 읽고, 여기서는 B/L 의 실제 Consignee 기재가
# 그 방식을 따랐는지 본다. 둘이 어긋나면 한쪽만 고치게 되므로 나란히 둔다.
_TO_ORDER_BL_RE = re.compile(r"\bTO\s+(?:THE\s+)?ORDER\b", re.IGNORECASE)


def bl_consignment_required(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """L/C 가 지시식(TO ORDER) B/L 을 요구하는데 서류가 기명식인지.

    지시식 B/L 은 배서로 유통되어야 신용장의 담보(물품에 대한 권리)가
    성립한다. 기명식으로 발행되면 유통성이 없어 은행이 거절한다.

    **수하인이 비어 있으면 위반으로 잡지 않는다.** 누락은 D005(필수 항목)의
    소관이라 여기서 또 세면 같은 사실로 하자가 두 번 계상된다.
    """
    flag = str(lc.get(rule.get("lc_flag", "")) or "").upper()
    if flag != "TO_ORDER":
        return not_evaluated("L/C 가 지시식 B/L 을 요구하지 않습니다")

    _, consignee = _first_present(bl, _rule_fields(rule))
    if not consignee:
        return not_evaluated("서류에 수하인 정보가 없습니다")

    if _TO_ORDER_BL_RE.search(consignee):
        return passed(bl=consignee)
    return violated(bl=consignee)


def bl_in_documents_required(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """46A 요구 서류 목록에 선하증권이 있는지."""
    documents = lc.documents_required
    if not documents:
        return not_evaluated("L/C 에 요구 서류 목록이 없습니다")

    joined = " ".join(str(d).upper() for d in documents)
    if "BILL OF LADING" in joined or re.search(r"\bB/?L\b", joined):
        return passed()
    return violated(lc=", ".join(str(d) for d in documents))


# ── 파싱 유틸 ────────────────────────────────────────────────────

def parse_date(text: str) -> Optional[datetime]:
    """알려진 형식으로 날짜를 읽는다. 실패하면 None."""
    cleaned = re.sub(r"\s+", " ", str(text).strip().upper())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_quantity(text: str, unit: str) -> Optional[float]:
    """중량·용적을 읽는다. MT 는 KG 으로 환산한다."""
    unit = (unit or "").upper()
    if unit == "KG":
        m = re.search(r"([\d,]+\.?\d*)\s*(?:KGS?|KG)\b", text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
        m = re.search(r"([\d,]+\.?\d*)\s*(?:MT|M\.T\.)\b", text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1)) * 1000
        return None
    if unit == "CBM":
        m = re.search(r"([\d,]+\.?\d*)\s*(?:CBM|M3)\b", text, re.IGNORECASE)
        return _to_float(m.group(1)) if m else None
    return parse_amount(text)


def parse_amount(text: str) -> Optional[float]:
    m = re.search(r"([\d,]+\.?\d*)", str(text))
    return _to_float(m.group(1)) if m else None


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _tokens_match(bl_value: str, lc_value: str) -> bool:
    """토큰 단위 비교. 항구 이명과 법인격 표기를 흡수한다."""
    bl_tokens = _significant_tokens(bl_value)
    lc_tokens = _significant_tokens(lc_value)
    if not lc_tokens:
        return True

    # 신용장은 항구를 "BUSAN, KOREA" 처럼 국가까지 적는 것이 표준(MT700 44E/44F)
    # 이고, 선하증권은 같은 칸에 "BUSAN" 만 인쇄한다. 쉼표 뒤를 대조에 넣으면
    # 정상 서류가 항상 불일치로 잡힌다 — 국가는 항구명의 수식이지 별도 요건이
    # 아니므로 핵심(쉼표 앞)만 본다. "KOREA" 만 적힌 서류는 핵심이 안 맞아
    # 그대로 위반으로 남는다.
    core = _significant_tokens(lc_value.split(",")[0])
    if core:
        lc_tokens = core

    expanded = _with_synonyms(bl_tokens)
    overlap = expanded & lc_tokens
    return len(overlap) / len(lc_tokens) >= MATCH_THRESHOLD


def _with_synonyms(tokens: set) -> set:
    expanded = set(tokens)
    for token in tokens:
        for synonyms in PORT_SYNONYMS:
            if token in synonyms:
                expanded |= synonyms
    return expanded


def _significant_tokens(value: str) -> set:
    tokens = set(re.findall(r"[A-Z]+", value.upper()))
    return tokens - _LEGAL_SUFFIXES


# ── 레지스트리 ───────────────────────────────────────────────────

CheckFn = Callable[[object, LCTerms, dict], CheckOutcome]

REGISTRY: Dict[str, CheckFn] = {
    "required": required,
    "required_if_lc": required_if_lc,
    "match_place": match_place,
    "contains_keywords": contains_keywords,
    "date_not_after": date_not_after,
    "presentation_before_expiry": presentation_before_expiry,
    "presentation_period": presentation_period,
    "date_not_in_future": date_not_in_future,
    "numeric_not_above": numeric_not_above,
    "within_tolerance": within_tolerance,
    "forbidden_when_prohibited": forbidden_when_prohibited,
    "contains_forbidden": contains_forbidden,
    "freight_prepaid_required": freight_prepaid_required,
    "contains_incoterms": contains_incoterms,
    "bl_in_documents_required": bl_in_documents_required,
    "bl_consignment_required": bl_consignment_required,
    "on_board_required_when_received": on_board_required_when_received,
}

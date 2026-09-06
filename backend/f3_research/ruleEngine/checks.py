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
        return not_evaluated(f"서류 날짜를 해석할 수 없습니다: {bl_value}",
                             bl=bl_value, lc=lc_value)
    if lc_date is None:
        return not_evaluated(f"L/C 날짜를 해석할 수 없습니다: {lc_value}",
                             bl=bl_value, lc=lc_value)

    if bl_date > lc_date:
        overdue = (bl_date - lc_date).days
        return violated(detail=str(overdue), bl=bl_value, lc=lc_value)
    return passed(bl=bl_value, lc=lc_value)


def presentation_period(bl, lc: LCTerms, rule: dict) -> CheckOutcome:
    """선적일로부터 제시기간이 지났는지 (UCP 600 Art.14(c))."""
    names = _rule_fields(rule)
    _, bl_value = _first_present(bl, names)
    if not bl_value:
        return not_evaluated("서류에 선적일이 없습니다")

    shipped = parse_date(bl_value)
    if shipped is None:
        return not_evaluated(f"선적일을 해석할 수 없습니다: {bl_value}", bl=bl_value)

    days = lc.presentation_days
    # 기준 시각을 인자로 받지 않고 now() 를 쓰면 테스트가 날짜에 따라 흔들린다.
    # 엔진이 as_of 를 주입한다.
    as_of = rule.get("_as_of") or datetime.now()
    elapsed = (as_of - shipped).days

    if elapsed > days:
        return violated(detail=str(elapsed), bl=bl_value, lc=str(days))
    return passed(bl=bl_value, lc=str(days))


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

    expanded = set(bl_tokens)
    for token in bl_tokens:
        for synonyms in PORT_SYNONYMS:
            if token in synonyms:
                expanded |= synonyms

    overlap = expanded & lc_tokens
    return len(overlap) / len(lc_tokens) >= MATCH_THRESHOLD


def _significant_tokens(value: str) -> set:
    tokens = set(re.findall(r"[A-Z]+", value.upper()))
    return tokens - _LEGAL_SUFFIXES


# ── 레지스트리 ───────────────────────────────────────────────────

CheckFn = Callable[[object, LCTerms, dict], CheckOutcome]

REGISTRY: Dict[str, CheckFn] = {
    "required": required,
    "match_place": match_place,
    "contains_keywords": contains_keywords,
    "date_not_after": date_not_after,
    "presentation_period": presentation_period,
    "numeric_not_above": numeric_not_above,
    "within_tolerance": within_tolerance,
    "forbidden_when_prohibited": forbidden_when_prohibited,
    "contains_incoterms": contains_incoterms,
    "bl_in_documents_required": bl_in_documents_required,
}

"""
서류 간 정합성 검증 (기획안 5절 "L/C 조건 및 서류 간 정합성과 대조").

`engine.RuleEngine` 은 서류 1건을 L/C 에 대조한다. 여기는 **서류끼리** 대조한다.
UCP 600 Art.14(d) 가 요구하는 것이 후자다 — 기재는 그 서류·다른 요구서류·
신용장 어느 것과도 저촉되어서는 안 된다.

## 없는 서류는 저촉이 아니다

이 모듈에서 가장 중요한 규칙이다. 어느 한쪽 서류가 세트에 없으면 결과는
`not_evaluated` 이지 위반이 아니다.

반대로 하면 B/L 한 장만 올린 사용자에게 저촉 하자가 무더기로 뜬다. 그리고
그 하자들은 **고칠 방법이 없다** — 서류를 더 올리는 것 말고는. 사용자가
고칠 수 없는 것을 하자로 표시하면 화면 전체의 신뢰가 떨어진다.

## 정합성은 '같음'이 아니다

Art.14(e) 는 선하증권의 물품 명세가 신용장 명세와 **저촉되지 않는 일반적
용어**로 기재될 수 있다고 한다. 즉 B/L 에 "27 PKG CELL ASSEMBLY", 송장에
"27 PKG CELL ASSEMBLY MACHINE" 이면 정상이다. 문자열 동일성으로 재면 정상
서류가 무더기로 걸린다.

그래서 명세 비교는 토큰 겹침으로, 당사자명은 유의 토큰 겹침으로 본다.

## 판정할 수 없는 것을 판정하지 않는다

명세가 **일반적 용어로만** 쓰인 경우("MACHINERY PARTS")는 겹침이 0 이어도
정상일 수 있다. "MACHINERY" 가 "CELL ASSEMBLY MACHINE" 과 저촉하는지는 무역
실무 판단이고 토큰으로는 답이 안 나온다.

위반으로 두면 정상 서류에 하자를 만들고, 통과로 두면 진짜 저촉을 놓친다.
그래서 세 번째 상태를 쓴다 — `not_evaluated`. 검사하지 못했다는 사실이
리포트에 그대로 실린다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import checks
from .checks import CheckOutcome, not_evaluated, passed, violated
from .engine import RuleCatalogError
from .types import LCTerms, Severity, SkippedRule, Verdict, Violation

DEFAULT_CROSS_RULES_PATH = Path(__file__).with_name("cross_rules.yaml")

# 서류가 아니라 신용장을 가리키는 예약어. 카탈로그에서 다른 서류와 같은
# 자리에 쓸 수 있게 두면 룰 문법이 하나로 유지된다.
LC_DOC = "신용장"

BILL_OF_LADING = "선하증권"

# 명세 비교에서 무시할 포장·수량 용어. 이것만 겹치는 것은 같은 물품의 근거가
# 못 된다 — "27 PKG STEEL" 과 "27 PKG COTTON" 이 통과해 버린다.
_GOODS_STOPWORDS = frozenset({
    "PKG", "PKGS", "PACKAGE", "PACKAGES", "CTN", "CTNS", "CARTON", "CARTONS",
    "PALLET", "PALLETS", "CASE", "CASES", "BOX", "BOXES", "UNIT", "UNITS",
    "TOTAL", "SAY", "ONLY", "AND", "THE", "OF", "IN", "TO", "ITEM", "ITEMS",
    "NET", "GROSS", "WEIGHT", "QTY", "QUANTITY",
    # 선하증권 상용 문구. 품명이 아니라 면책 표시다.
    # "SAID TO CONTAIN" / "SHIPPER'S LOAD AND COUNT".
    "STC", "SHIPPER", "SHIPPERS", "LOAD", "COUNT", "SEAL", "SEALED",
})

# 일반적 상품 용어. Art.14(e) 가 선하증권에 허용하는 표현이다.
# 이것만으로 쓰인 명세는 저촉 여부를 판정할 수 없다(모듈 도입부 참조).
_GENERIC_GOODS = frozenset({
    "MACHINERY", "MACHINE", "MACHINES", "PARTS", "SPARE", "COMPONENTS",
    "GOODS", "CARGO", "MERCHANDISE", "COMMODITY", "COMMODITIES",
    "EQUIPMENT", "MATERIALS", "MATERIAL", "PRODUCTS", "PRODUCE",
    "ARTICLES", "SUNDRIES", "GENERAL", "SAID", "CONTAIN", "CONTAINS",
})

# 명세가 저촉하지 않는다고 볼 최소 겹침 비율(짧은 쪽 기준).
_GOODS_OVERLAP = 0.5

# 수량 비교 허용 오차(비율). 단위 환산·반올림 표기 차이를 흡수한다.
# 0 으로 두면 884 KG 과 884.0 KG 이 어긋난다.
_QUANTITY_TOLERANCE = 0.005


class DocumentSet:
    """검증에 넣을 서류 묶음.

    선하증권은 `BLFields`(속성 접근), 나머지는 `DocumentFields`(dict 접근)라
    형태가 다르다. 여기서 흡수해 룰이 서류 종류를 몰라도 되게 한다.
    """

    def __init__(self, lc: Optional[LCTerms] = None) -> None:
        self._docs: Dict[str, Any] = {}
        self.lc = lc

    def add(self, fields: Any, form_type: Optional[str] = None) -> "DocumentSet":
        """서류 한 건을 넣는다. 종류는 fields 에서 읽거나 인자로 받는다."""
        name = form_type or _form_type_of(fields)
        if name:
            self._docs[name] = fields
        return self

    def has(self, form_type: str) -> bool:
        if form_type == LC_DOC:
            return self.lc is not None
        return form_type in self._docs

    def value(self, form_type: str, field: str) -> Optional[str]:
        """서류의 필드 값. 서류가 없거나 값이 없으면 None."""
        if form_type == LC_DOC:
            raw = self.lc.get(field) if self.lc is not None else None
        else:
            fields = self._docs.get(form_type)
            if fields is None:
                return None
            raw = (
                fields.get(field) if hasattr(fields, "get")
                else getattr(fields, field, None)
            )

        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    @property
    def form_types(self) -> List[str]:
        return sorted(self._docs)


def _form_type_of(fields: Any) -> Optional[str]:
    """서류 객체에서 종류 이름을 읽는다."""
    spec = getattr(fields, "spec", None)
    if spec is not None:
        return getattr(spec, "name", None)
    # BLFields 에는 종류 표시가 없다. 선하증권 전용 형이므로 그렇게 본다.
    if hasattr(fields, "bl_no"):
        return BILL_OF_LADING
    return None


# ── 검사 함수 ────────────────────────────────────────────────────

def same_party(left: str, right: str, rule: dict) -> CheckOutcome:
    """당사자명이 같은지. 법인격 표기와 어순 차이를 흡수한다."""
    lt, rt = checks._significant_tokens(left), checks._significant_tokens(right)
    if not lt or not rt:
        return not_evaluated("비교할 수 있는 토큰이 없습니다", left=left, right=right)

    overlap = len(lt & rt) / min(len(lt), len(rt))
    if overlap >= checks.MATCH_THRESHOLD:
        return passed(left=left, right=right)
    return violated(left=left, right=right)


def goods_compatible(left: str, right: str, rule: dict) -> CheckOutcome:
    """물품 명세가 저촉하지 않는지.

    같을 것을 요구하지 않는다 — Art.14(e) 가 일반적 용어를 허용한다.
    한쪽이 다른 쪽을 충분히 포함하면 통과다.
    """
    lt, rt = _goods_tokens(left), _goods_tokens(right)
    if not lt or not rt:
        return not_evaluated("비교할 수 있는 품명 토큰이 없습니다", left=left, right=right)

    # 일반적 용어로만 쓰인 쪽이 있으면 판정하지 않는다.
    for tokens, text in ((lt, left), (rt, right)):
        if tokens <= _GENERIC_GOODS:
            return not_evaluated(
                f"일반적 용어로만 기재되어 저촉 여부를 판정할 수 없습니다: {text}",
                left=left, right=right,
            )

    overlap = len(lt & rt) / min(len(lt), len(rt))
    if overlap >= _GOODS_OVERLAP:
        return passed(left=left, right=right)
    return violated(left=left, right=right)


def same_quantity(left: str, right: str, rule: dict) -> CheckOutcome:
    """수량·중량·용적이 같은지. 단위는 룰의 unit 을 따른다."""
    unit = rule.get("unit", "")
    lv = checks.parse_quantity(left, unit)
    rv = checks.parse_quantity(right, unit)
    if lv is None or rv is None:
        return not_evaluated(
            f"수량을 해석할 수 없습니다 ({unit})", left=left, right=right
        )

    base = max(abs(lv), abs(rv), 1e-9)
    if abs(lv - rv) / base <= _QUANTITY_TOLERANCE:
        return passed(left=left, right=right)
    return violated(left=left, right=right)


def same_reference(left: str, right: str, rule: dict) -> CheckOutcome:
    """참조 번호·코드가 같은지. 영숫자만 비교한다.

    `LC-2026-101` 과 `LC2026101` 은 같은 번호를 다르게 적은 것이다.
    구분자 차이로 하자를 내면 오탐이 실제 하자를 덮는다.
    """
    lt, rt = _alnum(left), _alnum(right)
    if not lt or not rt:
        return not_evaluated("비교할 값이 없습니다", left=left, right=right)
    if lt == rt:
        return passed(left=left, right=right)
    return violated(left=left, right=right)


def amount_not_above(left: str, right: str, rule: dict) -> CheckOutcome:
    """왼쪽 금액이 오른쪽을 넘지 않는지."""
    lv = checks.parse_amount(left) or checks._to_float(left)
    rv = checks.parse_amount(right) or checks._to_float(right)
    if lv is None or rv is None:
        return not_evaluated("금액을 해석할 수 없습니다", left=left, right=right)

    if lv <= rv * (1 + _QUANTITY_TOLERANCE):
        return passed(left=left, right=right)
    return violated(left=left, right=right)


CROSS_REGISTRY = {
    "same_party": same_party,
    "goods_compatible": goods_compatible,
    "same_quantity": same_quantity,
    "same_reference": same_reference,
    "amount_not_above": amount_not_above,
}


def _goods_tokens(value: str) -> set:
    """품명 토큰. 순수 숫자는 뺀다.

    수량이 같다는 것은 같은 물품의 근거가 못 된다. 넣어 두면
    "27 PKG STEEL" 과 "27 PKG COTTON" 이 겹침 1/2 로 통과한다.
    """
    tokens = {t for t in re.findall(r"[A-Z0-9]{2,}", value.upper()) if not t.isdigit()}
    return tokens - _GOODS_STOPWORDS


def _alnum(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


# ── 엔진 ─────────────────────────────────────────────────────────

class CrossDocumentEngine:
    """서류 간 정합성 룰을 실행한다."""

    def __init__(self, rules: Optional[List[dict]] = None) -> None:
        self.rules = rules if rules is not None else load_cross_rules()
        _validate_cross_catalog(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def verify(self, documents: DocumentSet) -> Verdict:
        """서류 묶음을 대조한다.

        비교 대상 서류가 없으면 **평가불가**로 남긴다. 위반이 아니다.
        """
        verdict = Verdict(model="cross-rules-v1")

        for rule in self.rules:
            left_ref, right_ref = rule["left"], rule["right"]
            missing = [
                ref["doc"] for ref in (left_ref, right_ref)
                if not documents.has(ref["doc"])
            ]
            if missing:
                verdict.skipped.append(SkippedRule(
                    rule_id=rule["id"], title=rule["title"],
                    reason=f"세트에 없는 서류: {', '.join(missing)}",
                ))
                continue

            left = documents.value(left_ref["doc"], left_ref["field"])
            right = documents.value(right_ref["doc"], right_ref["field"])
            if not left or not right:
                # 서류는 있는데 값이 비었다. 누락은 서류별 룰이 잡는다 —
                # 여기서 또 세면 같은 결함이 두 번 계상된다.
                verdict.skipped.append(SkippedRule(
                    rule_id=rule["id"], title=rule["title"],
                    reason="대조할 값이 서류에 없습니다",
                ))
                continue

            outcome = self._run_check(rule, left, right)
            if not outcome.evaluated:
                verdict.skipped.append(SkippedRule(
                    rule_id=rule["id"], title=rule["title"], reason=outcome.reason,
                ))
                continue

            verdict.evaluated_count += 1
            if outcome.violated:
                verdict.violations.append(_to_violation(rule, left, right, outcome))

        return verdict

    @staticmethod
    def _run_check(rule: dict, left: str, right: str) -> CheckOutcome:
        fn = CROSS_REGISTRY.get(rule["check"])
        if fn is None:
            return not_evaluated(f"알 수 없는 검사: {rule['check']}")
        try:
            return fn(left, right, rule)
        except Exception as exc:  # noqa: BLE001 - 룰 하나가 전체를 멈추면 안 된다
            return not_evaluated(f"검사 실패: {exc}")

    def unverified_rules(self) -> List[dict]:
        """조문 인용이 실무 검증을 거치지 않은 룰."""
        return [r for r in self.rules if r.get("verified") is not True]


def _to_violation(rule: dict, left: str, right: str, outcome: CheckOutcome) -> Violation:
    return Violation(
        rule_id=rule["id"],
        severity=Severity(rule["severity"]),
        title=rule["title"],
        message=rule.get("message", "").format(left=left, right=right),
        # S4 의 '해당 필드로 바로가기'가 쓴다. 서류가 둘이므로 종류를 붙인다.
        fields=[
            f"{rule['left']['doc']}.{rule['left']['field']}",
            f"{rule['right']['doc']}.{rule['right']['field']}",
        ],
        source=rule.get("source", ""),
        remedy=rule.get("remedy", ""),
        weight=float(rule.get("weight", 0.0)),
        observed=dict(outcome.observed or {}),
    )


def load_cross_rules(path: Optional[Path] = None) -> List[dict]:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML 이 필요합니다: pip install PyYAML") from exc

    with open(path or DEFAULT_CROSS_RULES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules = (data or {}).get("rules")
    if not rules:
        raise RuleCatalogError("서류 간 정합성 룰이 하나도 없습니다")
    return rules


_REQUIRED = ("id", "title", "severity", "check", "left", "right", "message")


def _validate_cross_catalog(rules: List[dict]) -> None:
    """기동 시 전수 검사한다. 카탈로그 오류를 첫 요청에서 만나면 늦다."""
    problems: List[str] = []
    seen: Dict[str, int] = {}

    for index, rule in enumerate(rules):
        where = rule.get("id") or f"#{index}"

        for key in _REQUIRED:
            if not rule.get(key):
                problems.append(f"{where}: '{key}' 가 없습니다")

        if rule.get("id"):
            if rule["id"] in seen:
                problems.append(f"{where}: id 가 중복입니다")
            seen[rule["id"]] = index

        if rule.get("check") and rule["check"] not in CROSS_REGISTRY:
            problems.append(
                f"{where}: 알 수 없는 check '{rule['check']}' "
                f"(가능: {', '.join(sorted(CROSS_REGISTRY))})"
            )

        if rule.get("severity"):
            try:
                Severity(rule["severity"])
            except ValueError:
                problems.append(f"{where}: 알 수 없는 severity '{rule['severity']}'")

        for side in ("left", "right"):
            ref = rule.get(side)
            if isinstance(ref, dict) and not (ref.get("doc") and ref.get("field")):
                problems.append(f"{where}: {side} 에 doc/field 가 필요합니다")

    if problems:
        raise RuleCatalogError(
            "서류 간 정합성 카탈로그 오류:\n  - " + "\n  - ".join(problems)
        )


__all__ = [
    "CROSS_REGISTRY",
    "CrossDocumentEngine",
    "DocumentSet",
    "LC_DOC",
    "load_cross_rules",
]

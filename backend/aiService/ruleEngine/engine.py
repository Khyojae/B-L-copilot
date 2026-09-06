"""
룰 엔진.

`rules.yaml` 을 읽어 B/L 필드를 L/C 조건에 대조하고 `Verdict` 를 만든다.

로드 시점에 카탈로그를 검증한다 — 모르는 check 이름이나 중복 id 를 실행
시점까지 끌고 가면, 룰이 조용히 건너뛰어져 '하자 없음'으로 보고된다.
하자 검증 시스템에서 조용한 실패는 틀린 답보다 나쁘다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .checks import REGISTRY, CheckOutcome
from .types import HeldRule, LCTerms, Severity, SkippedRule, Verdict, Violation

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")


class RuleCatalogError(ValueError):
    """룰 카탈로그가 잘못되었을 때."""


# ── 카탈로그 신원 ────────────────────────────────────────────────

@dataclass(frozen=True)
class CatalogFingerprint:
    """어떤 룰 카탈로그로 판정했는지를 가리키는 신원.

    기획안 5.8 '판정 재현성'과 5.3 '조문 개정 시 카탈로그 버전을 판정 결과에
    함께 저장한다'가 요구하는 값이다.

    **버전과 다이제스트를 함께 남긴다.** `version` 은 카탈로그가 스스로
    선언한 값이라 룰을 고치면서 올리지 않으면 그대로 거짓말이 된다. 실제로
    8번(ISBP 룰 보강)에서 룰이 24건에서 29건이 되는 동안 version 은 1 이었다.
    그 상태로 version 만 기록하면 서로 다른 카탈로그로 낸 판정이 같은 기준을
    쓴 것으로 남는다 — 재현성이 조용히 깨지고, 조용한 실패는 틀린 답보다 나쁘다.
    """

    version: str
    digest: str   # 카탈로그 내용의 sha256 앞 12자

    @property
    def label(self) -> str:
        return f"v{self.version}+{self.digest}"

    def to_dict(self) -> dict:
        return {"version": self.version, "digest": self.digest, "label": self.label}


# 카탈로그가 버전을 선언하지 않았을 때 쓰는 값. 테스트나 기동 프로브처럼
# 코드에서 룰을 주입한 경우가 여기 해당한다.
#
# 빈 문자열이 아니라 명시적인 값을 쓴다. 빈 문자열이면 label 이 `v+abc123`
# 이 되어 버전 자리가 비었다는 사실이 오탈자처럼 보인다.
UNDECLARED_VERSION = "0"

# 다이제스트 길이. 12자면 39건 규모에서 충돌이 실질적으로 없고,
# 로그·응답에 그대로 실을 만큼 짧다.
_DIGEST_CHARS = 12


def fingerprint_of(
    rules: List[dict], version: Optional[str] = None
) -> CatalogFingerprint:
    """룰 목록에서 신원을 계산한다.

    다이제스트는 **선언된 버전을 재료에 넣지 않는다.** 넣으면 version 만
    올려도 다이제스트가 바뀌어, "내용이 같은지"를 묻는 질문에 답하지
    못하게 된다. 둘은 서로를 감시하는 별개의 값이라 분리해 둔다.

    키 순서와 YAML 들여쓰기에 흔들리지 않도록 정렬된 JSON 으로 직렬화한다.
    주석만 고친 카탈로그가 다른 카탈로그로 잡히면 안 된다.
    """
    canonical = json.dumps(
        rules, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    return CatalogFingerprint(
        version=str(version) if version is not None else UNDECLARED_VERSION,
        digest=digest,
    )


class RuleEngine:
    """조문 코드화된 룰로 하자를 검출한다."""

    def __init__(
        self,
        rules: Optional[List[dict]] = None,
        version: Optional[str] = None,
        path: Optional[Path] = None,
    ) -> None:
        if rules is None:
            rules, declared = read_catalog(path)
            version = version if version is not None else declared
        self.rules: List[dict] = rules
        _validate_catalog(self.rules)
        self.fingerprint = fingerprint_of(self.rules, version)

    # ── 조문 검증 상태 ────────────────────────────────────────────

    def unverified_rules(self) -> List[dict]:
        """조문 인용이 아직 실무 검증을 거치지 않은 룰.

        `verified: true` 를 명시한 룰만 검증된 것으로 본다. 기본값이
        미검증인 이유는 rules.yaml 머리말에 적었다.
        """
        return [r for r in self.rules if r.get("verified") is not True]

    # ── 실행 ──────────────────────────────────────────────────────

    def verify(
        self,
        bl,
        lc: Optional[LCTerms] = None,
        as_of: Optional[datetime] = None,
        held_fields: Optional[Iterable[str]] = None,
    ) -> Verdict:
        """B/L 필드를 L/C 조건에 대조한다.

        bl 은 dict 또는 BLFields 를 받는다.

        as_of 는 제시기간 계산의 기준 시각이다. 주입하지 않으면 테스트가
        실행 날짜에 따라 흔들린다.

        `held_fields` 는 신뢰도가 '필수 확인' 등급이라 값을 믿을 수 없는
        필드다. 이 필드를 참조하는 룰은 **돌리지 않고 판정 보류로 남긴다** —
        기획안 v2 5.3 의 예외 조항이다.

        돌려서 위반으로 세면 못 믿는 값에 근거해 조문을 인용하게 되고,
        돌려서 통과로 세면 확인이 필요한 상태가 '하자 없음'으로 읽힌다.
        둘 다 틀리므로 세 번째 상태로 뺀다.
        """
        # 입력 형 검증은 룰 루프 **앞에서** 한다. 루프 안에서 터지면 룰별
        # 예외 처리에 흡수되어 21건 전부 '평가불가'가 되는데, 그 결과는
        # 위반 0건이라 얼핏 '하자 없음'으로 읽힌다. 호출부의 형 오류는
        # 검증 결과가 아니라 예외로 알려야 한다.
        if not isinstance(bl, Mapping) and not hasattr(bl, "__dataclass_fields__"):
            raise TypeError(
                f"bl 은 dict 또는 BLFields 여야 합니다 (받은 형: {type(bl).__name__})"
            )

        # parse_date()가 만드는 서류상 날짜는 항상 naive(tzinfo 없음)다.
        # as_of가 tz-aware로 들어오면(JS toISOString()의 "Z" 접미 등)
        # 날짜 룰의 aware-naive 뺄셈이 TypeError를 던지고, 룰 루프의
        # 예외 흡수 때문에 조용히 '평가불가'로 사라진다. 여기서 한 번만
        # naive로 맞춰 모든 날짜 룰이 이 문제를 피하게 한다.
        if as_of is not None and as_of.tzinfo is not None:
            as_of = as_of.replace(tzinfo=None)

        lc = lc or LCTerms()
        # 어떤 카탈로그로 판정했는지를 결과에 박아 둔다(기획안 5.3·5.8).
        # 판정 시점에 붙이지 않으면 나중에 되짚을 방법이 없다 — 그때 남아
        # 있는 것은 이미 고쳐진 rules.yaml 뿐이다.
        verdict = Verdict(model="rules-v1", catalog=self.fingerprint.to_dict())

        held = frozenset(held_fields or ())

        for rule in self.rules:
            # 보류 판정을 룰 실행 **앞에서** 한다. 실행 후에 걸러내면 그
            # 사이에 못 믿는 값으로 만든 위반 메시지가 만들어지고, 그 문자열이
            # 로그나 디버그 출력으로 새어 나간다.
            touched = sorted(held.intersection(rule.get("fields") or ()))
            if touched:
                verdict.held.append(
                    HeldRule(
                        rule_id=rule["id"],
                        title=rule["title"],
                        fields=touched,
                        weight=float(rule.get("weight") or 0.0),
                    )
                )
                continue

            check = REGISTRY[rule["check"]]
            # 시각 의존 룰에만 쓰이지만 규약을 단순하게 두려고 전부에 넣는다.
            context = {**rule, "_as_of": as_of}

            try:
                outcome: CheckOutcome = check(bl, lc, context)
            except Exception as exc:  # noqa: BLE001
                # 룰 하나가 죽어도 나머지는 계속 돈다. 다만 통과로 세지 않고
                # 평가불가로 남겨 리포트에 드러낸다.
                verdict.skipped.append(
                    SkippedRule(
                        rule_id=rule["id"],
                        title=rule["title"],
                        reason=f"룰 실행 중 오류: {exc}",
                    )
                )
                continue

            if not outcome.evaluated:
                verdict.skipped.append(
                    SkippedRule(
                        rule_id=rule["id"],
                        title=rule["title"],
                        reason=outcome.reason,
                    )
                )
                continue

            verdict.evaluated_count += 1
            if outcome.violated:
                verdict.violations.append(_to_violation(rule, outcome))

        return verdict

    # ── 조회 ──────────────────────────────────────────────────────

    def rule(self, rule_id: str) -> Optional[dict]:
        return next((r for r in self.rules if r["id"] == rule_id), None)

    @property
    def rule_ids(self) -> List[str]:
        return [r["id"] for r in self.rules]

    def __len__(self) -> int:
        return len(self.rules)


# ── 카탈로그 로드·검증 ───────────────────────────────────────────

def read_catalog(path: Optional[Path] = None) -> tuple:
    """YAML 카탈로그를 읽어 (룰 목록, 선언된 버전) 을 돌려준다.

    `load_rules` 와 나눈 이유는 버전이 필요한 호출부가 생겼기 때문이다.
    `load_rules` 는 룰만 돌려주므로 `version:` 키를 조용히 버렸고, 그래서
    판정 결과에 카탈로그 버전을 실을 수 없었다.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML 이 필요합니다: pip install PyYAML"
        ) from exc

    path = path or DEFAULT_RULES_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "rules" not in data:
        raise RuleCatalogError(f"룰 카탈로그 형식이 잘못되었습니다: {path}")

    declared = data.get("version")
    return list(data["rules"]), (
        str(declared) if declared is not None else UNDECLARED_VERSION
    )


def load_rules(path: Optional[Path] = None) -> List[dict]:
    """YAML 카탈로그의 룰 목록만 읽는다."""
    return read_catalog(path)[0]


_REQUIRED_KEYS = ("id", "title", "severity", "check", "source", "message")


def _validate_catalog(rules: List[dict]) -> None:
    """실행 전에 카탈로그를 전수 검사한다."""
    if not rules:
        raise RuleCatalogError("룰이 하나도 없습니다")

    seen: Dict[str, int] = {}
    problems: List[str] = []

    for index, rule in enumerate(rules):
        where = rule.get("id") or f"#{index}"

        for key in _REQUIRED_KEYS:
            if not rule.get(key):
                problems.append(f"{where}: 필수 항목 '{key}' 누락")

        rule_id = rule.get("id")
        if rule_id:
            if rule_id in seen:
                problems.append(f"{rule_id}: id 가 중복입니다 (#{seen[rule_id]} 와)")
            seen[rule_id] = index

        check = rule.get("check")
        if check and check not in REGISTRY:
            problems.append(
                f"{where}: 알 수 없는 check '{check}' "
                f"(등록된 것: {', '.join(sorted(REGISTRY))})"
            )

        severity = rule.get("severity")
        if severity and severity not in {s.value for s in Severity}:
            problems.append(f"{where}: 알 수 없는 severity '{severity}'")

        weight = rule.get("weight")
        if weight is not None and not 0.0 <= float(weight) <= 1.0:
            problems.append(f"{where}: weight 는 0~1 이어야 합니다 (현재 {weight})")

    if problems:
        raise RuleCatalogError(
            "룰 카탈로그에 문제가 있습니다:\n  - " + "\n  - ".join(problems)
        )


# 형식 오류 위반의 고정 가중치. 룰 자신의 weight(critical 룰은 0.30~0.40)를
# 그대로 쓰면 "날짜를 못 읽었다"는 약한 신호가 실제 위반과 같은 크기로
# defect_probability에 반영된다 — 이 카탈로그의 warning 룰들(0.08~0.15)과
# 같은 대역으로 맞춘다(P1-15).
_FORMAT_ERROR_WEIGHT = 0.10


def _to_violation(rule: dict, outcome: CheckOutcome) -> Violation:
    if outcome.format_error:
        return Violation(
            rule_id=rule["id"],
            severity=Severity.WARNING,
            title="날짜 형식 오류",
            message=outcome.reason,
            fields=list(rule.get("fields") or []),
            source=rule.get("source", ""),
            remedy="날짜 형식을 확인하고 다시 추출하거나 직접 입력하세요.",
            weight=_FORMAT_ERROR_WEIGHT,
            observed=outcome.observed or {},
        )
    return Violation(
        rule_id=rule["id"],
        severity=Severity(rule["severity"]),
        title=rule["title"],
        message=_render(rule["message"], outcome),
        fields=list(rule.get("fields") or []),
        source=rule.get("source", ""),
        remedy=rule.get("remedy", ""),
        weight=float(rule.get("weight") or 0.0),
        observed=outcome.observed or {},
    )


def _render(template: str, outcome: CheckOutcome) -> str:
    """메시지 치환. 값이 없으면 물음표로 둔다 — None 이 그대로 노출되면
    사용자가 읽을 수 없다."""
    values: Dict[str, Any] = {
        "bl": outcome.bl_value or "?",
        "lc": outcome.lc_value or "?",
        "detail": outcome.detail or "",
    }
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        # 카탈로그에 모르는 치환자가 있어도 메시지는 나가야 한다.
        return template

"""
룰 엔진.

`rules.yaml` 을 읽어 B/L 필드를 L/C 조건에 대조하고 `Verdict` 를 만든다.

로드 시점에 카탈로그를 검증한다 — 모르는 check 이름이나 중복 id 를 실행
시점까지 끌고 가면, 룰이 조용히 건너뛰어져 '하자 없음'으로 보고된다.
하자 검증 시스템에서 조용한 실패는 틀린 답보다 나쁘다.
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .checks import REGISTRY, CheckOutcome
from .types import LCTerms, Severity, SkippedRule, Verdict, Violation

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")


class RuleCatalogError(ValueError):
    """룰 카탈로그가 잘못되었을 때."""


class RuleEngine:
    """조문 코드화된 룰로 하자를 검출한다."""

    def __init__(self, rules: Optional[List[dict]] = None) -> None:
        self.rules: List[dict] = rules if rules is not None else load_rules()
        _validate_catalog(self.rules)

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
    ) -> Verdict:
        """B/L 필드를 L/C 조건에 대조한다.

        bl 은 dict 또는 BLFields 를 받는다.

        as_of 는 제시기간 계산의 기준 시각이다. 주입하지 않으면 테스트가
        실행 날짜에 따라 흔들린다.
        """
        # 입력 형 검증은 룰 루프 **앞에서** 한다. 루프 안에서 터지면 룰별
        # 예외 처리에 흡수되어 21건 전부 '평가불가'가 되는데, 그 결과는
        # 위반 0건이라 얼핏 '하자 없음'으로 읽힌다. 호출부의 형 오류는
        # 검증 결과가 아니라 예외로 알려야 한다.
        if not isinstance(bl, Mapping) and not hasattr(bl, "__dataclass_fields__"):
            raise TypeError(
                f"bl 은 dict 또는 BLFields 여야 합니다 (받은 형: {type(bl).__name__})"
            )

        lc = lc or LCTerms()
        verdict = Verdict(model="rules-v1")

        for rule in self.rules:
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

def load_rules(path: Optional[Path] = None) -> List[dict]:
    """YAML 카탈로그를 읽는다."""
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
    return list(data["rules"])


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


def _to_violation(rule: dict, outcome: CheckOutcome) -> Violation:
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

"""F3 하자 예측 — 룰엔진(조문 코드화).

기획안 F3 의 두 축 중 결정론 축이다. 확률 축은 `mlModel` 에 있다.
"""

from .checks import REGISTRY, CheckOutcome
from .engine import RuleCatalogError, RuleEngine, load_catalog, load_rules
from .types import (
    DEFAULT_PRESENTATION_DAYS,
    DEFAULT_TOLERANCE_PCT,
    LCTerms,
    MT700_TAGS,
    Outcome,
    Severity,
    SkippedRule,
    Verdict,
    Violation,
)

__all__ = [
    "CheckOutcome",
    "DEFAULT_PRESENTATION_DAYS",
    "DEFAULT_TOLERANCE_PCT",
    "LCTerms",
    "MT700_TAGS",
    "Outcome",
    "REGISTRY",
    "RuleCatalogError",
    "RuleEngine",
    "Severity",
    "SkippedRule",
    "Verdict",
    "Violation",
    "load_catalog",
    "load_rules",
]

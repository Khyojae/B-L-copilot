"""F2 표준 용어 교정 — 공개 표면.

`ruleEngine/__init__.py` 와 같은 규약이다. 각 하위 모듈이 이미 손으로 쓴
`__all__` 을 갖고 있고(§"모듈별 `__all__`" 규약, `types.py`·`glossary.py` 등
머리말 참고), 여기서는 그 이름들을 패키지 최상위로 다시 노출할 뿐이다 — 새
공개 규칙을 여기서 만들지 않는다. 묶음 순서는 파일명 알파벳순(`apply` →
`cascade` → `glossary` → `keys` → `llm_select` → `policy` → `similarity` →
`types` → `validators`)이고, 묶음 **안**에서는 각 모듈의 `__all__` 이 이미
따르는 정렬(파이썬 기본 문자열 정렬 — 대문자가 소문자보다 먼저)을 그대로
옮긴다. `ruleEngine/__init__.py` 를 눈으로 비교하면 같은 모양이 보일 것이다.

## `normalize_key`·`loose_key` 를 F6 을 위해 여기 명시로 둔다

F6(현실 대조)은 HTTP 를 타지 않는다 — `/normalize` 를 호출하는 게 아니라
`from terms import normalize_key` 로 **같은 비교 키 함수**를 직접 가져다
쓴다(`docs/f2/HANDOFF.md` §6.3, `keys.py` 모듈 docstring "F6 이 이 모듈만
가볍게 끌어 쓸 수 있어야 한다"). 이 캐스케이드(`cascade.py`)의 ①exact·
②alias 단계도 정확히 이 `normalize_key` 로 사전을 조회하고,
`apply.suggestion_id` 도 `as_is` 를 이 함수로 접어 해시 재료에 넣는다 — F2
안에서 "같은 값"을 정의하는 유일한 함수다.

F6 이 자기 나름의 정규화 함수를 새로 짜면(겉보기엔 "대문자로, 공백 정리"라
비슷해 보여도) 두 기능이 서로 다른 키로 같은 값을 접는 순간이 반드시
생긴다 — 예를 들어 점(`.`)을 남기는지가 갈리면 `"8471.30"` 과 `"847130"`
이 F2 에서는 다른 키인데 F6 에서는 같은 키가 되고, F6 이 "이 값은 이미
표준과 일치한다"고 판정한 필드를 F2 는 여전히 교정 대상으로 본다 — 두
기능의 판정이 조용히 어긋나고, 그 어긋남은 예외가 아니라 **매칭 실패**로만
드러나 원인을 추적하기 어렵다. 그래서 `terms.keys` 안에 묻어 두지 않고
패키지 최상위 `__all__` 에 **명시로** 올려 "여기서 가져다 쓰라"는 신호를
남긴다.

## 임포트 비용 — 이 파일은 카탈로그를 읽지 않는다

`import terms` 만으로 YAML 파싱이나 n-gram 인덱스 빌드가 일어나면 안 된다
— 카탈로그 적재(`glossary.load_glossary`/`load_all_glossaries`)는
`api/main.py` 의 지연 싱글턴 `glossary()` 가 기동 시 1회만 한다(`engine()`
과 같은 자리). 이 파일이 재노출하는 하위 모듈들은 전부 그 규약을 이미
지키고 있다:

- `glossary.py` 는 모듈 최상단에서 파일을 읽지 않는다. `_read_yaml` 이
  실제로 파일을 여는 자리이고, 그마저 `import yaml` 을 함수 안에서 지연
  임포트한다 — `terms` 가 PyYAML 없이도 임포트되게 하기 위해서다
  (`glossary.py:_read_yaml` docstring).
- `cascade.py` 는 `ruleEngine` 을 `TYPE_CHECKING` 블록 안에서만 참조한다
  — 런타임에 룰 카탈로그를 끌어오지 않는다.
- `llm_select.py` 는 `report.llm_providers` 를 `LLMSelector._get_completion`
  안에서 지연 임포트한다 — LLM 프로바이더 설정이 없어도 `import terms` 는
  성공해야 한다.

이 파일이 하는 일은 이미 가벼운 이름들을 한 자리로 모으는 것뿐이므로, 이
불변식을 새로 어길 여지가 없다 — 다만 앞으로 하위 모듈에 모듈 최상단
I/O 를 추가하는 사람은 이 문단을 깨는 것임을 알아야 한다.
"""

from .apply import (
    ApplyOutcome,
    SUGGESTION_ID_PREFIX,
    apply_suggestions,
    reject_suggestions,
    suggestion_id,
    verify_suggestion_id,
)
from .cascade import (
    DocumentInput,
    Normalizer,
    SelectionItem,
    SelectionOutcome,
    Selector,
)
from .glossary import (
    DEFAULT_CATALOG_DIR,
    Glossary,
    GlossaryCatalogError,
    GlossaryStack,
    Hit,
    IndexedTerm,
    available_versions,
    build_override,
    load_all_glossaries,
    load_glossary,
)
from .keys import loose_key, normalize_key
from .llm_select import Completion, LLMSelector, default_selector
from .policy import (
    CASCADE_VERSION,
    CLASSES,
    CONF_ALIAS,
    CONF_EXACT,
    CONF_FORMAT,
    CONF_PATTERN,
    CONF_PATTERN_VERIFIED,
    FIELD_CLASS,
    FIELD_SCAN_CLASSES,
    LLM_CONFIDENCE_CAP,
    LLM_FORBIDDEN,
    MIN_CONFIDENCE,
    SIMILARITY_FLOOR,
    SINGLE_CANDIDATE_FLOOR,
    STAGE_ALIAS,
    STAGE_EXACT,
    STAGE_FORMAT,
    STAGE_LLM,
    STAGE_ORDER,
    STAGE_PATTERN,
    STAGE_SIMILARITY,
    TOP_K,
    TermClass,
    allows,
    glossary_version_override,
    llm_max_items,
    llm_select_enabled,
    llm_timeout,
)
from .similarity import NGramRanker, RankResult, Ranker
from .types import (
    Candidate,
    Correction,
    Evidence,
    FieldRef,
    GlossaryTerm,
    Notice,
    NormalizeResult,
    Stats,
    Suggestion,
    Unevaluated,
    Versions,
)
from .validators import (
    CONTAINER_RE,
    ContainerCheck,
    HSCode,
    INCOTERMS_2020,
    LOCODE_RE,
    LocodeCheck,
    PartySuffixCheck,
    PriceTerm,
    UnitCode,
    container_check_digit,
    format_price_term,
    incoterms_consistent_with_checks,
    locode_ok,
    normalize_hs,
    normalize_locode,
    party_suffix,
    parse_price_term,
    split_quantity,
    unit_code,
    validate_container,
    validate_locode,
)

# `CASCADE_VERSION` 은 `cascade.py` 도 자기 `__all__` 에 올려 두지만(원본은
# `policy.py`, `cascade.py` 는 그걸 다시 가져다 씀), 여기서는 `policy` 쪽
# 한 번만 임포트한다 — 두 번 임포트해도 같은 객체라 동작에는 문제가 없지만,
# `__all__` 에 같은 이름을 두 번 올리면 "정렬된 목록"이라는 규약이 흐트러진다.

__all__ = [
    # ── apply.py ──
    "ApplyOutcome",
    "SUGGESTION_ID_PREFIX",
    "apply_suggestions",
    "reject_suggestions",
    "suggestion_id",
    "verify_suggestion_id",
    # ── cascade.py (CASCADE_VERSION 은 policy.py 블록에서 한 번만) ──
    "DocumentInput",
    "Normalizer",
    "SelectionItem",
    "SelectionOutcome",
    "Selector",
    # ── glossary.py ──
    "DEFAULT_CATALOG_DIR",
    "Glossary",
    "GlossaryCatalogError",
    "GlossaryStack",
    "Hit",
    "IndexedTerm",
    "available_versions",
    "build_override",
    "load_all_glossaries",
    "load_glossary",
    # ── keys.py — F6 이 직접 끌어 쓰는 자리(모듈 docstring 참고) ──
    "loose_key",
    "normalize_key",
    # ── llm_select.py ──
    "Completion",
    "LLMSelector",
    "default_selector",
    # ── policy.py ──
    "CASCADE_VERSION",
    "CLASSES",
    "CONF_ALIAS",
    "CONF_EXACT",
    "CONF_FORMAT",
    "CONF_PATTERN",
    "CONF_PATTERN_VERIFIED",
    "FIELD_CLASS",
    "FIELD_SCAN_CLASSES",
    "LLM_CONFIDENCE_CAP",
    "LLM_FORBIDDEN",
    "MIN_CONFIDENCE",
    "SIMILARITY_FLOOR",
    "SINGLE_CANDIDATE_FLOOR",
    "STAGE_ALIAS",
    "STAGE_EXACT",
    "STAGE_FORMAT",
    "STAGE_LLM",
    "STAGE_ORDER",
    "STAGE_PATTERN",
    "STAGE_SIMILARITY",
    "TOP_K",
    "TermClass",
    "allows",
    "glossary_version_override",
    "llm_max_items",
    "llm_select_enabled",
    "llm_timeout",
    # ── similarity.py ──
    "NGramRanker",
    "RankResult",
    "Ranker",
    # ── types.py ──
    "Candidate",
    "Correction",
    "Evidence",
    "FieldRef",
    "GlossaryTerm",
    "Notice",
    "NormalizeResult",
    "Stats",
    "Suggestion",
    "Unevaluated",
    "Versions",
    # ── validators.py ──
    "CONTAINER_RE",
    "ContainerCheck",
    "HSCode",
    "INCOTERMS_2020",
    "LOCODE_RE",
    "LocodeCheck",
    "PartySuffixCheck",
    "PriceTerm",
    "UnitCode",
    "container_check_digit",
    "format_price_term",
    "incoterms_consistent_with_checks",
    "locode_ok",
    "normalize_hs",
    "normalize_locode",
    "party_suffix",
    "parse_price_term",
    "split_quantity",
    "unit_code",
    "validate_container",
    "validate_locode",
]

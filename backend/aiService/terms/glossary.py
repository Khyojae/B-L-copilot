"""
F2 표준 용어사전 로더.

`ruleEngine/engine.py` 를 그대로 본뜬다 — `rules.yaml` 을 읽어 검증하고
`RuleEngine` 을 만드는 자리에, 여기서는 `catalogs/<version>/*.yaml` 을 읽어
검증하고 `Glossary`/`GlossaryStack` 을 만든다. 대응 관계:

    read_catalog/_validate_catalog/RuleCatalogError  ↔  이 파일의 로더·검증·
    GlossaryCatalogError
    RuleEngine(rules=[...])                          ↔  Glossary(terms=[...])

로드 시점에 카탈로그를 전수 검증한다 — 특히 **정규화 키 충돌**을 놓치면,
결과는 예외가 아니라 **조용히 틀린 교정**이다(`HANDOFF.md` §4.6). 별칭 하나가
다른 항목의 정규화 키와 우연히 같아지면, 사전 조회가 엉뚱한 항목을 돌려주고
그 값이 그럴듯한 얼굴로 제안 카드에 실린다. 룰 카탈로그의 "모르는 check
이름"은 실행 즉시 예외로 드러나지만, 사전의 키 충돌은 실행이 **성공**하고
답만 틀린다 — 그래서 이 파일에서 가장 공들인 검사가 키 충돌 검사다.

## `GlossaryTerm` 이 못 담는 필드 — 의도된 손실

`docs/ai-service/f2-standard-terms.md` §스키마가 정한 YAML 항목에는
`lang`·`authority`·`version`(출처 표준의 판)·`effective_date`·`source` 가
있지만, `terms/types.py:GlossaryTerm` 은 이 중 어느 것도 필드로 갖지 않는다
(수정 금지 지시에 따라 이 파일은 `types.py` 를 고치지 않는다). 그래서:

- 필수 키 검사(§스키마 9필드 포함)는 **원본 dict** 단계에서만 가능하다 —
  `GlossaryTerm.from_dict` 로 변환하는 순간 이 정보는 조용히 버려진다
  (`from_dict` 의 "모르는 키는 무시한다" 규약, `types.py` 참고).
- `Evidence.authority` 는 그래서 항목별 `authority` 문자열이 아니라
  `policy.CLASSES[term_class].default_authority` 로 채워야 한다 — 이건
  `glossary.py` 의 책임이 아니라 T9(`cascade.py`)의 책임이지만, 이 손실을
  알고 있어야 T9 가 놀라지 않는다. 최종 보고에도 남긴다.

## 검증을 두 층으로 나눈 이유

1. `_raw_entry_problems` — **원본 dict** 리스트에 대해서만 검사할 수 있는
   것(필수 키 lang/authority/version/effective_date, lang 값, port
   country). YAML 로더와 `build_override` 양쪽에서만 이 층을 탄다.
2. `_term_problems` — 변환된 `GlossaryTerm` 만으로 검사할 수 있는 것
   (term_id 중복, 정규화 키 충돌, 모르는 category, deprecated_by 미존재,
   별칭 자기중복). `Glossary.__init__` 이 **항상** 이 층을 태운다 —
   `RuleEngine(rules=[...])` 가 주입된 룰도 검증하는 것과 같은 이유로,
   테스트가 `Glossary(terms=[...])` 로 직접 넣은 항목도 키 충돌 같은
   불변식에서 자유롭지 않아야 한다.

`load_glossary`/`build_override` 는 1층 문제와 2층 문제를 **먼저 한 번에
모아서** 하나의 `GlossaryCatalogError` 로 던진다(§9 "문제를 전부 모아 한
번에"). `Glossary.__init__` 에서 2층 검사가 다시 도는 것은 중복이지만
싸다(항목 수백 건 규모) — 그 대가로 주입 경로도 같은 보장을 받는다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .keys import loose_key, normalize_key
from .policy import CLASSES
from .types import GlossaryTerm

DEFAULT_CATALOG_DIR = Path(__file__).with_name("catalogs")

# 3-gram 길이. `HANDOFF.md` §4.3 의 `_grams` 와 동일해야 유사도 랭커
# (T8 `similarity.py`)가 이 인덱스를 그대로 재사용할 수 있다.
NGRAM_N = 3


class GlossaryCatalogError(ValueError):
    """용어사전 카탈로그(표준 또는 오버라이드)가 잘못되었을 때.

    `ruleEngine.RuleCatalogError` 와 같은 자리다. 표준 카탈로그가 이 예외를
    내면 기동이 죽어야 하고(서버 구성 오류), 오버라이드가 내면 호출부
    (`api/main.py`)가 400 으로 바꿔야 한다(요청 오류) — `HANDOFF.md` §4.6.
    이 파일은 그 구분을 모른다. 어떤 상태 코드로 바꿀지는 예외를 잡는 쪽의
    몫이다.
    """


# ── 3-gram (유사도 랭커용, T8 이 재사용) ────────────────────────────
#
# `similarity.py`(T8)가 아직 없어 이 함수를 여기 둔다. 이름을 `_grams` 로
# 두지 않고 `build_grams` 로 공개하는 이유: 밑줄 이름은 "이 모듈 전용"이라는
# 신호인데, T8 이 명시적으로 `from terms.glossary import build_grams` 하도록
# 계약을 걸어 둔다(`__all__` 에는 넣지 않는다 — `import *` 로 끌려나올
# 이름이 아니라 정확히 이 이름으로 지정해서 가져오라는 뜻).
def build_grams(key: str, n: int = NGRAM_N) -> Counter:
    """문자 3-gram 다중집합을 만든다. 앞뒤 공백 1개씩 패딩한다.

    패딩하는 이유: 패딩이 없으면 'BUSAN'·'PUSAN' 이 어두 한 글자 차이인데도
    'USAN' 공통 3-gram 비중이 커져 두 항구가 실제보다 유사해 보인다. 앞뒤
    공백을 포함시키면 어두·어말 자체가 구분 신호가 된다(`HANDOFF.md` §4.3).

    **다중집합(Counter)이어야 한다** — `set` 으로 두면 'AAA' 와 'AAAAAA'
    가 공유 3-gram 집합이 완전히 같아져 유사도가 1.0 이 된다. 반복 횟수가
    신호다.
    """
    padded = f" {key} "
    return Counter(padded[i : i + n] for i in range(len(padded) - n + 1))


@dataclass(frozen=True)
class IndexedTerm:
    """유사도 랭커(T8)가 순회하는 후보 풀의 항목 1건.

    `surface` 는 이 항목이 어느 표기에서 나왔는지(canonical 1건 + 별칭
    N건이 각각 별도 `IndexedTerm` 이 된다) — 유사도 최고점을 낸 표기를
    `Candidate.reason` 등에 남길 때 필요하다. `grams` 를 카탈로그 로드
    시점에 미리 계산해 두는 이유는 `rules.yaml` 을 기동 시 1회만 읽는 것과
    같다 — 매 조회마다 문자열을 다시 쪼개면 선적 1건당 3-gram 재계산이
    풀 크기 × 후보 필드 수만큼 반복된다.
    """

    term: GlossaryTerm
    surface: str
    loose: str
    grams: Counter

    def to_dict(self) -> dict:
        return {
            "term_id": self.term.term_id,
            "surface": self.surface,
            "loose": self.loose,
        }


@dataclass(frozen=True)
class Hit:
    """`GlossaryStack.lookup` 조회 결과 1건.

    `term` 은 원본 인덱스의 객체가 아니라 `tier` 만 이 히트를 만든 계층의
    값으로 바꾼 **복사본**이다(`dataclasses.replace`). 원본을 그대로 고쳐
    돌려주면 인덱스가 공유 상태라 다음 조회가 이전 조회의 tier 를 물려받는
    사고가 난다. `diverges_from_standard` 는 하위 계층이 답했고 표준
    계층에도 같은 키가 있으며 canonical 이 다를 때만 채워진다 — 그 외에는
    `None` 이다(`Evidence.diverges_from_standard` 규약과 동일).
    """

    term: GlossaryTerm
    tier: str
    diverges_from_standard: Optional[str] = None


class Glossary:
    """한 카탈로그 버전(또는 한 오버라이드 계층)의 용어사전. 인덱스를 들고 있다.

    `terms=[...]` 로 리스트를 직접 받는 것이 주입 seam 이다
    (`RuleEngine(rules=[...])` 와 같은 이유) — 테스트가 YAML 파일을 만들지
    않고도 키 충돌·동음이의 판별 같은 로직을 검증할 수 있다.
    """

    def __init__(
        self,
        terms: List[GlossaryTerm],
        catalog_version: str,
        effective_date: str,
        tier: str = "standard",
    ) -> None:
        self.terms: List[GlossaryTerm] = list(terms)
        self.catalog_version = catalog_version
        self.effective_date = effective_date
        self.tier = tier

        # 주입 경로도 로더와 같은 불변식을 진다 — 모듈 docstring 의
        # "검증을 두 층으로 나눈 이유" ②.
        problems = _term_problems(self.terms)
        if problems:
            raise GlossaryCatalogError(
                "용어사전에 문제가 있습니다:\n  - " + "\n  - ".join(problems)
            )

        self._by_term_id: Dict[str, GlossaryTerm] = {}
        by_canonical: Dict[Tuple[str, str], List[GlossaryTerm]] = defaultdict(list)
        by_alias: Dict[Tuple[str, str], List[GlossaryTerm]] = defaultdict(list)
        pool: Dict[str, List[IndexedTerm]] = defaultdict(list)

        for term in self.terms:
            self._by_term_id[term.term_id] = term

            canonical_key = normalize_key(term.canonical)
            by_canonical[(term.category, canonical_key)].append(term)
            pool[term.category].append(_indexed(term, term.canonical))

            # 별칭 하나가 같은 키로 두 번 색인되면(중복 별칭) 풀에 같은
            # surface 가 두 번 들어가 유사도 후보 목록에 중복이 뜬다.
            # `_term_problems` 가 이미 이런 카탈로그를 거부하므로 여기서는
            # 방어적으로만 거른다.
            seen_alias_keys = set()
            for alias in term.aliases:
                alias_key = normalize_key(alias)
                if alias_key == canonical_key or alias_key in seen_alias_keys:
                    continue
                seen_alias_keys.add(alias_key)
                by_alias[(term.category, alias_key)].append(term)
                pool[term.category].append(_indexed(term, alias))

        # 인덱스 값은 **리스트**다 — 항구 동음이의가 후보 여러 개로 나와야
        # `HANDOFF.md` §4.8 의 판별 경로(국가 신호 → 인접 필드 → L/C →
        # LLM → requires_choice)가 실제로 발동한다. dict 로 덮어쓰면(마지막
        # 값만 남기면) 그 경로 전체가 죽은 코드가 된다.
        self._by_canonical: Dict[Tuple[str, str], List[GlossaryTerm]] = dict(by_canonical)
        self._by_alias: Dict[Tuple[str, str], List[GlossaryTerm]] = dict(by_alias)
        self._pool: Dict[str, List[IndexedTerm]] = dict(pool)

    # ── 조회 ──────────────────────────────────────────────────────

    def by_term_id(self, term_id: str) -> Optional[GlossaryTerm]:
        return self._by_term_id.get(term_id)

    def by_canonical_key(self, key: str, term_class: str) -> List[GlossaryTerm]:
        """①exact 단계. `key` 는 원문 그대로 넘겨도 된다 — 내부에서
        `normalize_key` 를 적용한다."""
        return list(self._by_canonical.get((term_class, normalize_key(key)), ()))

    def by_alias_key(self, key: str, term_class: str) -> List[GlossaryTerm]:
        """②alias 단계."""
        return list(self._by_alias.get((term_class, normalize_key(key)), ()))

    def pool(self, term_class: str) -> List[IndexedTerm]:
        """④유사도 단계의 후보 풀. 클래스에 항목이 없으면 빈 리스트다 —
        `qty_unit`/`volume_unit` 처럼 애초에 ④가 금지된 클래스라도 풀 자체는
        조회 가능해야 T8 테스트가 "닫힌 집합이라 후보가 없다"를 직접 확인할
        수 있다."""
        return list(self._pool.get(term_class, ()))

    # ── 집계 (GET /glossary · 기동 로그용) ───────────────────────────

    @property
    def term_count(self) -> int:
        return len(self.terms)

    @property
    def alias_count(self) -> int:
        return sum(len(t.aliases) for t in self.terms)

    @property
    def unverified_count(self) -> int:
        """`rules.yaml` 의 `unverified_source_count` 와 같은 모양.
        `verified is not True` 가 아니라 `not t.verified` 를 쓰는 이유:
        `GlossaryTerm.verified` 는 dataclass 필드라 항상 `bool` 이고,
        `rules.yaml` 의 dict `.get("verified")` 처럼 키 자체가 없어
        `None` 이 나오는 경우가 없다."""
        return sum(1 for t in self.terms if not t.verified)

    def by_class(self) -> Dict[str, int]:
        """category → 항목 수. `unverified_count` 와 마찬가지로 canonical
        건수 기준이다(별칭은 세지 않는다) — HANDOFF §4.6 적재량 표의
        "canonical" 열과 같은 셈법이어야 기동 로그 숫자가 그 표와 대조된다."""
        return dict(Counter(t.category for t in self.terms))

    def __len__(self) -> int:
        return len(self.terms)


def _indexed(term: GlossaryTerm, surface: str) -> IndexedTerm:
    loose = loose_key(surface)
    return IndexedTerm(term=term, surface=surface, loose=loose, grams=build_grams(loose))


class GlossaryStack:
    """표준 → 조직 → 선적. 가장 구체적인 계층부터 조회한다.

    `layers` 는 **일반→구체 순서**로 받는다(`GlossaryStack([standard,
    organization, shipment])`, `HANDOFF.md` §4.6) — 생성자 순서와 조회
    순서가 반대인 이유는 "표준이 항상 계층 0번"이라는 가정을 코드 한 곳
    (`layers[0]`)에만 두기 위해서다. `diverges_from_standard` 계산이 바로
    그 가정에 기댄다.
    """

    def __init__(self, layers: List[Glossary]) -> None:
        self.layers: List[Glossary] = list(layers)

    def lookup(self, key: str, term_class: str, *, alias: bool = True) -> List[Hit]:
        """가장 구체적인 계층부터 훑어 **먼저 맞는 계층에서 멈춘다.**

        한 계층 안에서는 canonical 히트를 우선하고, `alias=True` 면 아직
        안 걸린 별칭 히트를 더한다(같은 term 이 canonical 로도 alias 로도
        잡히는 일은 `_term_problems` 가 "별칭이 canonical 과 같음"으로
        이미 막는다). 그 계층에 히트가 하나도 없으면 다음(더 일반적인)
        계층으로 내려간다 — 하위 계층이 "이 값은 모른다"고 답한 것이지
        "표준과 같다"고 답한 게 아니므로 표준으로 대체 조회하는 게 맞다.
        """
        for layer in reversed(self.layers):
            exact = layer.by_canonical_key(key, term_class)
            matched_ids = {t.term_id for t in exact}
            extra = (
                [t for t in layer.by_alias_key(key, term_class) if t.term_id not in matched_ids]
                if alias
                else []
            )
            combined = exact + extra
            if combined:
                return [self._hit(term, layer, key, term_class) for term in combined]
        return []

    def _hit(self, term: GlossaryTerm, layer: Glossary, key: str, term_class: str) -> Hit:
        tiered = replace(term, tier=layer.tier)
        diverges: Optional[str] = None
        # layers[0] 이 표준이라는 계약 — 클래스 docstring 참고. 표준 계층
        # 자신이 답한 경우는 "표준과 다르다"는 말 자체가 성립하지 않는다.
        if self.layers and layer is not self.layers[0]:
            standard = self.layers[0]
            std_hits = standard.by_canonical_key(key, term_class) + standard.by_alias_key(
                key, term_class
            )
            for std_term in std_hits:
                if std_term.canonical != term.canonical:
                    diverges = std_term.canonical
                    break
        return Hit(term=tiered, tier=layer.tier, diverges_from_standard=diverges)

    def pool(self, term_class: str) -> List[IndexedTerm]:
        """전 계층의 후보를 합친다 — 조직·선적 오버라이드로 들어온 표기도
        유사도 후보가 되어야 한다(예: 조직이 추가한 사내 항구 별칭)."""
        combined: List[IndexedTerm] = []
        for layer in self.layers:
            combined.extend(layer.pool(term_class))
        return combined


# ── 검증 ────────────────────────────────────────────────────────────

# §스키마(HANDOFF §4.6, f2-standard-terms.md §스키마)가 정한 9필드 중
# `GlossaryTerm` 이 저장하지 않는 5필드(lang·authority·version·
# effective_date·source)까지 포함한 필수 키. `deprecated_by`·`display`·
# `country` 는 선택 필드라 여기 없다.
_RAW_REQUIRED_KEYS = ("term_id", "canonical", "category", "lang", "authority", "version", "effective_date")
_VALID_LANGS = {"ko", "en", "code"}


def _raw_entry_problems(raw_terms: List[dict]) -> List[str]:
    """원본 YAML/오버라이드 dict 리스트만 볼 수 있는 것을 검사한다.

    `GlossaryTerm` 변환 후에는 `lang`/`authority`/`version`(출처 표준
    판)/`effective_date`/`source` 가 사라지므로(모듈 docstring 참고) 이
    검사는 반드시 변환 **전**에 돈다.
    """
    problems: List[str] = []
    for index, raw in enumerate(raw_terms):
        if not isinstance(raw, dict):
            problems.append(f"#{index}: 항목이 매핑(딕셔너리) 형식이 아닙니다")
            continue

        where = raw.get("term_id") or f"#{index}"

        for key in _RAW_REQUIRED_KEYS:
            if not raw.get(key):
                problems.append(f"{where}: 필수 항목 '{key}' 누락")

        lang = raw.get("lang")
        if lang and lang not in _VALID_LANGS:
            problems.append(f"{where}: lang '{lang}' 은 ko|en|code 중 하나여야 합니다")

        # port 는 country 없이는 동음이의를 하나도 가르지 못한다(값이 있어도
        # 판별 못 하는 것과, 애초에 재료가 없는 것은 다르다) — 충돌 여부와
        # 무관하게 항상 요구한다. 이래야 "지금은 후보가 하나뿐이라 충돌이
        # 안 걸렸는데 나중에 동음이의가 추가되며 조용히 판별 불가"가 되는
        # 상황을 카탈로그 편집 시점에 미리 막는다.
        if raw.get("category") == "port" and not raw.get("country"):
            problems.append(f"{where}: category 가 port 인데 country 가 없습니다")

    return problems


def _term_problems(terms: List[GlossaryTerm]) -> List[str]:
    """변환된 `GlossaryTerm` 리스트만으로 검사할 수 있는 것.

    **정규화 키 충돌이 이 함수의 핵심이다.** 서로 다른 term_id 의
    canonical/별칭이 같은 `normalize_key` 로 접히면, 사전 조회
    (`by_canonical_key`/`by_alias_key`)가 인덱스 마지막에 쓴 값이 아니라
    **후보 리스트**를 돌려주긴 하지만, exact/alias 단계는 후보가
    1건이어야 자동 확정한다(HANDOFF §4.1 "①②③ 은 맞으면 즉시 종결"). 후보가
    여러 건이면 자동 확정이 아니라 판별 단계로 넘어가야 하는데, 이 함수가
    없으면 그 사실 자체를 아무도 모른 채 카탈로그가 로드되고, cascade 가
    "후보 1건"으로 착각해 틀린 canonical 을 확정해 버릴 수 있다.

    `port` 클래스만 동음이의로 허용한다 — 단, 충돌한 term 전부에 `country`
    가 있어야 한다. `country` 는 이미 `_raw_entry_problems` 가 port 전체에
    강제하므로, 이 시점에 도달한 port 충돌은 사실상 항상 country 를 갖고
    있다. 그래도 여기서 다시 확인하는 이유는 이 함수가 `_raw_entry_problems`
    없이 **단독으로**(`Glossary.__init__` 의 주입 경로) 호출될 수 있기
    때문이다 — 테스트가 `country` 를 빠뜨린 채 `GlossaryTerm` 을 직접
    만들 수도 있다.
    """
    problems: List[str] = []
    all_ids = {t.term_id for t in terms}
    seen_ids: Dict[str, int] = {}
    key_owners: Dict[Tuple[str, str], Dict[str, GlossaryTerm]] = defaultdict(dict)

    for index, term in enumerate(terms):
        where = term.term_id or f"#{index}"

        if term.term_id in seen_ids:
            problems.append(f"{where}: term_id 가 중복입니다 (#{seen_ids[term.term_id]} 와)")
        else:
            seen_ids[term.term_id] = index

        if term.category not in CLASSES:
            problems.append(
                f"{where}: 알 수 없는 category '{term.category}' "
                f"(등록된 것: {', '.join(sorted(CLASSES))})"
            )
            # 모르는 클래스는 policy.allows() 가 어차피 모든 단계를
            # 거부하므로(§안전 정책 "모르는 클래스는 무조건 거부") 이 항목을
            # 키 충돌 색인에 넣어 봐야 의미 있는 판정이 안 된다.
            continue

        if term.deprecated_by and term.deprecated_by not in all_ids:
            problems.append(
                f"{where}: deprecated_by '{term.deprecated_by}' 가 가리키는 "
                "term_id 가 카탈로그에 없습니다"
            )

        canonical_key = normalize_key(term.canonical)
        local_alias_keys = set()
        for alias in term.aliases:
            alias_key = normalize_key(alias)
            if alias_key == canonical_key:
                problems.append(f"{where}: 별칭 '{alias}' 이 canonical 과 같습니다(무의미)")
            if alias_key in local_alias_keys:
                problems.append(f"{where}: 별칭 '{alias}' 이 별칭 목록 안에서 중복입니다")
            local_alias_keys.add(alias_key)

        key_owners[(term.category, canonical_key)][term.term_id] = term
        for alias_key in local_alias_keys:
            if alias_key != canonical_key:
                key_owners[(term.category, alias_key)][term.term_id] = term

    for (category, key), owners in key_owners.items():
        if len(owners) <= 1:
            continue  # 충돌 없음 — 같은 term 이 canonical+별칭으로 두 번 잡힌 것뿐

        if category != "port":
            problems.append(
                f"정규화 키 충돌: '{key}' ({category}) 이 서로 다른 항목 "
                f"{', '.join(sorted(owners))} 을 가리킵니다 — port 이외 클래스의 "
                "키 충돌은 허용하지 않는다(별칭 하나가 다른 항목을 조용히 "
                "가리면 예외가 아니라 틀린 교정이 된다)"
            )
            continue

        missing_country = sorted(tid for tid, t in owners.items() if not t.country)
        if missing_country:
            problems.append(
                f"정규화 키 충돌: '{key}' (port) 을 {', '.join(sorted(owners))} 이 "
                f"공유하는데 country 가 없는 항목이 있어 동음이의로 허용할 수 "
                f"없습니다: {', '.join(missing_country)}"
            )
        # country 가 전부 있으면 항구 동음이의로 허용한다 — HANDOFF §4.8의
        # 판별 캐스케이드(국가 신호→인접 필드→L/C→LLM→requires_choice)가
        # 바로 이 다중 후보를 입력으로 받는다.

    return problems


def _coverage_problems(terms: List[GlossaryTerm]) -> List[str]:
    """역방향 검사 — `policy.CLASSES` 중 `needs_glossary=True` 인데 카탈로그에
    항목이 0건인 클래스. 표준 카탈로그(`load_glossary`)에만 적용한다
    (`check_coverage=True` 호출부). 오버라이드·주입 seam 은 정의상 부분
    사전이라 이 검사를 적용하면 조직이 항구 하나만 오버라이드하려 해도
    나머지 9개 클래스가 비었다고 거부당한다 — 그건 이 검사의 목적이 아니다.
    """
    present = {t.category for t in terms}
    problems = []
    for key, cls in CLASSES.items():
        if cls.needs_glossary and key not in present:
            problems.append(
                f"정책상 사전이 필요한 클래스 '{key}'({cls.label}) 에 카탈로그 "
                "항목이 0건입니다 — needs_glossary=True 인데 조회할 것이 없다"
            )
    return problems


def _collect_problems(
    raw_terms: List[dict], *, check_coverage: bool
) -> Tuple[List[str], List[GlossaryTerm]]:
    """1층(원본 dict) + 2층(GlossaryTerm) 검사를 한 번에 모은다.

    일부 항목이 필수 키가 빠져 있어도(예: term_id 누락) **나머지 항목의
    검사를 계속 진행한다** — "문제를 전부 모아 한 번에 던진다" 원칙
    (`HANDOFF.md` §4.6, `f2-standard-terms.md` §용어사전)을 지키려면 첫
    항목에서 멈추면 안 된다. 멈추면 그 뒤에 숨은 키 충돌은 다음 세션이 이
    문제를 하나 고치고 다시 돌렸을 때에야(그것도 새 오류 하나씩만) 드러난다.
    """
    problems = _raw_entry_problems(raw_terms)

    # term_id·canonical·category 셋 중 하나라도 없으면 GlossaryTerm 으로
    # 변환할 수 없다(from_dict 가 ValueError). 그 항목은 위에서 이미
    # "필수 항목 누락"으로 보고했으니 2층 검사 대상에서만 조용히 뺀다 —
    # 두 번 보고하면 "문제가 실제보다 많다"는 착각을 준다.
    convertible = [
        raw
        for raw in raw_terms
        if isinstance(raw, dict) and raw.get("term_id") and raw.get("canonical") and raw.get("category")
    ]
    terms: List[GlossaryTerm] = []
    for raw in convertible:
        try:
            terms.append(GlossaryTerm.from_dict(raw))
        except ValueError as exc:  # pragma: no cover - 방어적: 위 필터와 모순되면 여기 걸린다
            problems.append(str(exc))

    problems += _term_problems(terms)
    if check_coverage:
        problems += _coverage_problems(terms)

    return problems, terms


# ── YAML 입출력 ───────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict:
    """`engine.py:read_catalog` 와 같은 지연 임포트 + 친절한 오류.

    PyYAML 은 `requirements.txt` 에 이미 있는 필수 의존성이지만(HANDOFF
    §3), 임포트를 함수 안으로 미루는 이유는 `terms` 패키지의 다른 모듈
    (`keys.py`·`types.py`·`policy.py`)이 PyYAML 없이도 임포트되게 하기
    위해서다 — F6 이 `from terms import normalize_key` 만 쓸 때 PyYAML
    로드까지 강제하지 않는다.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML 이 필요합니다: pip install PyYAML") from exc

    if not path.is_file():
        raise GlossaryCatalogError(f"카탈로그 파일이 없습니다: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise GlossaryCatalogError(f"카탈로그 파일 형식이 잘못되었습니다(딕셔너리가 아님): {path}")

    return data


def available_versions(base_dir: Optional[Path] = None) -> List[str]:
    """카탈로그 디렉터리 아래에서 유효한 버전 디렉터리 이름을 나열한다.

    `_` 로 시작하는 디렉터리는 무시한다 — `_sample`(T4 자체 검증용 표본)이
    실제 판정에 쓰일 버전 목록에 섞이면 `/glossary/validate` 나 `/normalize`
    가 요청한 `glossary_version` 오류 메시지의 "가용 목록"에 표본이 끼어
    사용자를 헷갈리게 한다.
    """
    base_dir = base_dir or DEFAULT_CATALOG_DIR
    if not base_dir.is_dir():
        return []
    versions = []
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if (entry / "manifest.yaml").is_file():
            versions.append(entry.name)
    return versions


def _pick_latest_version(base_dir: Path) -> str:
    """`version` 을 지정하지 않았을 때 `effective_date` 가 가장 최신인
    버전을 고른다(`TERMS_GLOSSARY_VERSION` 을 비웠을 때의 규약,
    `HANDOFF.md` §6.3)."""
    versions = available_versions(base_dir)
    if not versions:
        raise GlossaryCatalogError(f"용어사전 카탈로그가 하나도 없습니다: {base_dir}")

    dated: List[Tuple[str, str]] = []
    for version in versions:
        try:
            manifest = _read_yaml(base_dir / version / "manifest.yaml")
            dated.append((str(manifest.get("effective_date") or ""), version))
        except GlossaryCatalogError:
            # manifest 가 깨진 버전은 여기서 조용히 최신 후보에서 빼고,
            # 실제로 그 버전이 선택됐을 때(load_glossary 가 다시 읽을 때)
            # 제대로 된 오류로 드러나게 둔다.
            dated.append(("", version))
    dated.sort()
    return dated[-1][1]


def load_glossary(version: Optional[str] = None, base_dir: Optional[Path] = None) -> Glossary:
    """표준 카탈로그 한 버전을 읽어 검증하고 `Glossary` 를 만든다.

    `glossary.yaml`(9클래스) + `locode.yaml`(port) 을 합쳐 **하나의**
    카탈로그로 검증한다 — 파일을 나눈 것은 "출처가 다르고 건수가 많아서"
    (`HANDOFF.md` §4.6 카탈로그 레이아웃)이지 서로 다른 사전이라서가
    아니다. 합치지 않고 따로 검증하면 예를 들어 `port` 와 다른 클래스 사이의
    term_id 중복을 못 잡는다.
    """
    base_dir = base_dir or DEFAULT_CATALOG_DIR
    if version is None:
        version = _pick_latest_version(base_dir)

    catalog_dir = base_dir / version
    if not catalog_dir.is_dir():
        raise GlossaryCatalogError(
            f"알 수 없는 사전 버전입니다: '{version}' "
            f"(가용: {', '.join(available_versions(base_dir)) or '없음'})"
        )

    manifest = _read_yaml(catalog_dir / "manifest.yaml")
    glossary_doc = _read_yaml(catalog_dir / "glossary.yaml")
    locode_doc = _read_yaml(catalog_dir / "locode.yaml")

    problems: List[str] = []

    # catalog_version 이 디렉터리명·파일 간에 어긋나면 안 된다(§검사 7) —
    # 요청이 지정한 glossary_version 으로 고른 디렉터리인데 내용물이 자기가
    # 다른 버전이라고 주장하면, 판정 결과에 박히는 catalog_version 도장이
    # 거짓말이 된다.
    for label, doc in (
        ("manifest.yaml", manifest),
        ("glossary.yaml", glossary_doc),
        ("locode.yaml", locode_doc),
    ):
        cv = doc.get("catalog_version")
        if not cv:
            problems.append(f"{label}: 필수 항목 'catalog_version' 누락")
        elif str(cv) != version:
            problems.append(
                f"{label}: catalog_version '{cv}' 이 디렉터리명 '{version}' 과 다릅니다"
            )

    glossary_cv = glossary_doc.get("catalog_version")
    locode_cv = locode_doc.get("catalog_version")
    if glossary_cv and locode_cv and str(glossary_cv) != str(locode_cv):
        problems.append(
            f"glossary.yaml(catalog_version={glossary_cv}) 과 "
            f"locode.yaml(catalog_version={locode_cv}) 이 서로 다릅니다"
        )

    raw_terms = list(glossary_doc.get("terms") or []) + list(locode_doc.get("terms") or [])
    if not raw_terms:
        problems.append("사전 항목이 하나도 없습니다(glossary.yaml + locode.yaml 합계 0건)")

    entry_problems, terms = _collect_problems(raw_terms, check_coverage=True)
    problems += entry_problems

    if problems:
        raise GlossaryCatalogError(
            f"용어사전 카탈로그({version})에 문제가 있습니다:\n  - " + "\n  - ".join(problems)
        )

    effective_date = str(manifest.get("effective_date") or glossary_doc.get("effective_date") or "")
    return Glossary(terms, catalog_version=version, effective_date=effective_date, tier="standard")


def load_all_glossaries(base_dir: Optional[Path] = None) -> Dict[str, Glossary]:
    """모든 버전을 로드·검증한다(`HANDOFF.md` §4.6 "기동 시 모든 버전을
    검증한다"). 기본 버전만 검증하면 과거 버전이 조용히 썩다가, 그 버전을
    실제로 요청한 재현 요청이 들어온 날에야 깨진 사실이 드러난다.

    `_sample` 처럼 `_` 로 시작하는 디렉터리는 `available_versions` 가 이미
    걸러내므로 여기 섞이지 않는다.
    """
    base_dir = base_dir or DEFAULT_CATALOG_DIR
    return {version: load_glossary(version, base_dir) for version in available_versions(base_dir)}


def build_override(payload: dict, tier: str) -> Glossary:
    """요청 본문의 조직 사전·선적 예외 오버라이드를 표준과 **같은 검증기**로
    만든다(`HANDOFF.md` §4.6). 깨지면 `GlossaryCatalogError` — 서버를 죽이지
    않는다. 호출부(`api/main.py`)가 이 예외를 400 으로 바꾼다(요청 오류이지
    서버 구성 오류가 아니다).

    표준 카탈로그와 다른 점은 `check_coverage=False` 하나뿐이다 — 오버라이드는
    정의상 부분 사전이다(조직이 항구 하나만 등록해도 유효하다).
    """
    if not isinstance(payload, Mapping):
        raise GlossaryCatalogError("오버라이드 사전 형식이 잘못되었습니다: 객체(딕셔너리)가 아닙니다")

    catalog_version = payload.get("version")
    raw_terms = payload.get("terms")

    problems: List[str] = []
    if not catalog_version:
        problems.append("오버라이드: 필수 항목 'version' 누락")
    if not isinstance(raw_terms, list) or not raw_terms:
        problems.append("오버라이드: 'terms' 가 비어 있거나 배열이 아닙니다")
        raw_terms = []

    entry_problems, terms = _collect_problems(raw_terms, check_coverage=False)
    problems += entry_problems

    if problems:
        raise GlossaryCatalogError(
            "오버라이드 사전에 문제가 있습니다:\n  - " + "\n  - ".join(problems)
        )

    effective_date = str(payload.get("effective_date") or "")
    return Glossary(
        terms,
        catalog_version=str(catalog_version),
        effective_date=effective_date,
        tier=tier,
    )


__all__ = [
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
]

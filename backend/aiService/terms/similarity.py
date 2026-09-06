"""
F2 ④유사도 단계 — 문자 3-gram Dice 랭커.

`docs/ai-service/f2-standard-terms.md` §"유사도는 문자 3-gram Dice 다" 의 구현이다.
기획안은 ④를 "유사도 검색(문자 n-gram **+ 임베딩**)"이라 적었지만 임베딩은 넣지
않는다 — 임베딩은 모델 파일이나 네트워크가 필요해 기획안 3.1 ③ 폐쇄망 온프레미스
프로파일이 그 자리에서 깨지고, 완료 기준(필드 1건 2초)도 냉시작 모델 적재를
못 견딘다. 3-gram Dice 는 순수 파이썬 표준 라이브러리만으로 끝난다.

## `Ranker` seam

임베딩이 들어올 자리를 `Ranker` Protocol 하나로 못박아 둔다. 이 파일이 그 유일한
자리이고, 임베딩 구현이 들어와도 의존성은 **그 구현 파일 안에만** 들어간다 —
`f4_report/llm_providers.py` 가 LLM 프로바이더를 `(system, user) -> str` 콜러블
하나로 좁혀 둔 것과 같은 형태다. 폐쇄망 프로파일은 기본 `NGramRanker` 로 계속
돈다. `Versions.ranker`(`types.py`)가 어느 구현이 돌았는지를 응답에 싣는다.

## gram 계산은 왜 `glossary.build_grams` 를 재사용하는가

카탈로그 로더(`glossary.py`)가 이미 각 `IndexedTerm.grams` 를 카탈로그 로드
시점에 `build_grams` 로 1회 계산해 캐시해 둔다. 이 파일이 같은 문자열에 대해
**다른** gram 함수(예: 패딩을 빼먹은 버전)를 새로 짜면, 질의 쪽 gram 과 풀 쪽
gram 이 서로 다른 규칙으로 쪼개져 교집합 계산 자체가 의미를 잃는다 — 캐시가
있으나 마나 해지는 정도가 아니라, 점수가 **조용히** 틀어진다(예외 없이 그럴듯한
숫자만 나온다). 그래서 질의 쪽도 반드시 `build_grams(loose_key(query))` 로
같은 함수를 태운다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Protocol, Sequence, Tuple

from .glossary import IndexedTerm, build_grams
from .keys import loose_key
from .policy import SIMILARITY_FLOOR, TOP_K
from .types import Candidate

__all__ = ["NGramRanker", "RankResult", "Ranker"]


class Ranker(Protocol):
    """질의 문자열 → 후보 상위 K.

    임베딩 구현이 들어올 자리는 이 Protocol 뿐이며, 그때도 의존성은 그
    구현 파일 안에만 들어간다(폐쇄망 프로파일 유지). 시그니처를 `rank()`
    하나로 고정해 두는 이유는 캐스케이드(T9)가 어느 구현이 꽂혀 있는지
    몰라도 되게 하기 위해서다.
    """

    name: str

    def rank(
        self, query: str, pool: Sequence[IndexedTerm], top_k: int = TOP_K
    ) -> List[Candidate]: ...


@dataclass(frozen=True)
class RankResult:
    """`rank_detailed()` 하나의 전체 결과 — 컷오프된 후보 목록 + 컷오프 전 최고점.

    `SIMILARITY_FLOOR` 미만인 candidate 는 `candidates` 에서 빠진다(호출부가
    "후보 없음"과 "점수 낮은 후보 있음"을 구분할 필요가 없도록). 하지만
    `cascade`(T9)가 `Unevaluated(reason="후보 최고 점수 0.42 < 0.55", score=0.42)`
    를 만들려면 컷오프로 사라진 점수가 어딘가엔 남아 있어야 한다 — `rank()` 가
    `List[Candidate]` 만 돌려주면 그 정보가 완전히 사라지므로 별도로 담는다.
    풀이 비어 있으면 `best_score` 는 `0.0` 이다(비교 대상이 없었다는 뜻이지,
    "완전히 다르다"는 판정과는 다르다 — 호출부가 필요하면 풀 크기로 그 둘을
    가른다).
    """

    candidates: List[Candidate]
    best_score: float


def _dice(query_grams: Counter, query_total: int, other_grams: Counter) -> float:
    """`dice(a, b) = 2·|A∩B| / (|A|+|B|)`. 다중집합 교집합은 `(A & B)` 의 값 합.

    **다중집합(`Counter`)이어야 한다** — `set` 으로 재면 `AAA` 와 `AAAAAA` 가
    3-gram 집합(둘 다 `{"AAA"}` 근방)이 같아져 유사도가 1.0 이 되어 버린다.
    반복 횟수 자체가 신호다(컨테이너 번호·수량 표기처럼 같은 문자가 반복되는
    입력에서 실제로 갈린다). `glossary.build_grams` 가 이미 `Counter` 를
    돌려주므로 이 함수는 그걸 그대로 받아 합·교집합만 계산한다.

    분모가 0(양쪽 다 빈 gram, 즉 빈 문자열)이면 비교 불능이지 "완전히 같다"가
    아니므로 0.0 을 돌려준다 — `1.0` 을 돌려주면 빈 질의가 모든 후보와
    만점으로 묶이는 사고가 난다.
    """
    other_total = sum(other_grams.values())
    if query_total == 0 or other_total == 0:
        return 0.0
    intersection = sum((query_grams & other_grams).values())
    return 2 * intersection / (query_total + other_total)


def _to_candidate(score: float, item: IndexedTerm) -> Candidate:
    """`IndexedTerm` 1건 + 점수 → `Candidate` 1건.

    `authority` 는 `item.term.authority` 를 그대로 쓴다 — 항목마다 근거
    표준이 다르므로(`types.py:GlossaryTerm` 의 `authority` 필드 설명 참고)
    클래스 공통 기본값으로 대신하면 카드가 출처를 지어내는 것과 같다.
    """
    term = item.term
    return Candidate(
        to_be=term.display or term.canonical,
        term_id=term.term_id,
        authority=term.authority,
        score=round(score, 4),
        # 화면이 동음이의 후보(예: PORTLAND US vs AU)를 구분할 짧은 문자열.
        # country 가 없는 클래스(transport_doc 등)는 애초에 구분할 신호가
        # 없으므로 빈 문자열 그대로 둔다 — 지어내지 않는다(§1 원칙).
        reason=term.country or "",
    )


class NGramRanker:
    """`Ranker` 기본 구현. 문자 3-gram Dice, 순수 파이썬.

    `Versions.ranker` 에 실릴 이름이 `name` 이다 — 클래스 이름이 아니라
    알고리즘을 가리키는 문자열로 둔다(향후 n 을 바꾸거나 임베딩 구현이
    들어와도 이 이름은 그 변경을 반영해 갈아 끼울 수 있는 문자열이다).
    """

    name = "ngram-dice-3"

    def rank(
        self, query: str, pool: Sequence[IndexedTerm], top_k: int = TOP_K
    ) -> List[Candidate]:
        """`Ranker` Protocol 시그니처. `rank_detailed()` 의 얇은 래퍼다."""
        return self.rank_detailed(query, pool, top_k).candidates

    def rank_detailed(
        self, query: str, pool: Sequence[IndexedTerm], top_k: int = TOP_K
    ) -> RankResult:
        """전체 계산 — 컷오프 전 최고점까지 함께 돌려준다(`RankResult` 참고).

        term 당 점수는 그 term 의 모든 surface(canonical + 전 별칭) 중
        **최대값**이다. 평균을 쓰면 별칭을 많이 채운 항목이 평균 때문에
        오히려 불리해진다 — 사전을 잘 채운 항목이 벌을 받는 지표는 사전을
        안 채우게 만든다(§유사도 스펙 문서). 풀에는 surface 단위로
        `IndexedTerm` 이 여러 개 들어 있으므로 `term_id` 로 묶어 최대값을
        취한다.
        """
        query_grams = build_grams(loose_key(query))
        query_total = sum(query_grams.values())

        # term_id → (그 term 이 낸 최고 점수, 그 점수를 낸 IndexedTerm).
        # 어느 surface 가 최고점을 냈는지는 Candidate 에 안 쓰지만(reason 은
        # country 기반이지 surface 기반이 아니다), 같은 term_id 의 모든
        # IndexedTerm 은 같은 GlossaryTerm 객체를 공유하므로 어느 쪽을
        # 남겨도 term 필드(display/authority/country)는 동일하다.
        best_per_term: Dict[str, Tuple[float, IndexedTerm]] = {}
        best_score = 0.0

        for item in pool:
            score = _dice(query_grams, query_total, item.grams)
            if score > best_score:
                best_score = score
            term_id = item.term.term_id
            current = best_per_term.get(term_id)
            if current is None or score > current[0]:
                best_per_term[term_id] = (score, item)

        # SIMILARITY_FLOOR 미만은 결과에서 제외한다 — 호출부가 "후보 없음"과
        # "점수 낮은 후보 있음"을 구분할 필요가 없도록. 점수 내림차순, 동점이면
        # term_id 오름차순으로 완전 결정론을 만든다: 같은 입력에 같은 순서가
        # 나와야 suggestion_id 해시가 재현된다(`HANDOFF.md` §4.7).
        ranked: List[Tuple[float, IndexedTerm]] = [
            (score, item)
            for score, item in best_per_term.values()
            if score >= SIMILARITY_FLOOR
        ]
        ranked.sort(key=lambda pair: (-pair[0], pair[1].term.term_id))

        candidates = [_to_candidate(score, item) for score, item in ranked[:top_k]]
        return RankResult(candidates=candidates, best_score=round(best_score, 4))

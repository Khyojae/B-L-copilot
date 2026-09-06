"""
F2 6단계 캐스케이드 — 서류 필드 → 교정 제안.

`docs/ai-service/f2-standard-terms.md` §"6단계 캐스케이드"·§"예외"·§"결정론
검증기" 의 구현이다. **이 파일은 값을 고치지 않는다.** 무엇을 어떻게 고칠지
`Suggestion` 으로 제안할 뿐이고, 실제 치환은 사람이 승인한 뒤 `apply`(T11)가
한다. 두 경로가 갈라져 있는 것 자체가 승인 게이트다.

## 이 파일이 지는 책임 (다른 모듈이 대신 못 하는 것)

1. **단계 진입은 반드시 `policy.allows()` 를 통해서만 묻는다.** 클래스별 허용
   표를 여기 다시 쓰지 않는다 — 두 곳에 있으면 한 곳만 고치는 날이 오고,
   그 날 컨테이너 번호가 외부 API 로 나가는데 아무 데도 보이지 않는다.
2. **정지 조건.** ①②③ 즉시 종결 · `to_be == as_is` 면 제안 없음 · ④ 최고점
   미달 → `Unevaluated` · 후보 2건 이상 → ⑤ 또는 `requires_choice` ·
   최종 신뢰도 < `MIN_CONFIDENCE` → 제안 없음.
3. **`span`.** 자유서식 안의 조각(관행 문구·컨테이너 번호·HS 코드·상호
   접미·단위 토큰)은 `FieldRef.span` 을 반드시 채운다. span 이 없으면
   `apply` 가 자유서식 필드를 통째로 갈아 끼워 본문을 파괴한다. 같은 필드
   안에서 span 이 겹치면 두 제안을 동시에 승인할 때 치환이 서로를 덮어쓰므로
   `_resolve_overlaps()` 가 겹침을 미리 제거한다.
4. **침묵 금지.** 클래스를 판별 못 한 필드, 유사도 미달, L/C 로 판단을
   유보한 필드는 전부 `Unevaluated` 로 남긴다. 룰엔진의 `not_evaluated` 규약과
   같다 — "검사하고 통과"와 "검사하지 않음"은 다르다.

## 단계 라벨을 정하는 규칙 (⓪format 과 ①exact 의 경계)

문서의 ⓪ 은 "값이 **이미 표준인데** NFKC·대소문자·연속 공백만 다름"이고
①②③ 은 "표준 표기를 찾아 바꾼다"이다. 두 정의는 `" KRPUS "` 같은 값에서
동시에 참이 된다. 그래서 이 파일은 **먼저 어느 경로가 답을 냈는지 계산하고,
그 답이 원본과 `normalize_key` 수준에서 같으면(=글자는 그대로이고 대소문자·
공백·NFKC 만 달랐으면) 단계 라벨을 `format` 으로 낮춘다**(`_relabel_format`).
반대로 하면 — 즉 ⓪ 을 먼저 무조건 종결시키면 — `"부산  "` 처럼 공백이 섞인
값이 `"부산"` 으로만 정리되고 `KRPUS` 제안은 영원히 나오지 않는다. ⓪ 이
"고유명사도 이중 공백은 고친다"를 위해 존재한다는 §6단계 캐스케이드의 논거를
지키면서 ①②③ 을 죽이지 않는 유일한 배치다.

`format` 이 금지된 클래스(`container_no`·`hs_code`)는 이 강등을 타지 않는다 —
`policy.allows(cls, STAGE_FORMAT)` 로 먼저 묻기 때문이다.

## 의존성 제약

표준 라이브러리만 쓴다. `ruleEngine` 은 `LCTerms` 타입 힌트와 MT700 파싱에만
필요하고 **전부 지연 임포트**다(`TYPE_CHECKING` + 함수 안 import) —
`terms` 는 F6 이 `ruleEngine` 을 몰라도 가볍게 끌어 써야 하는 자리다
(`keys.py`·`policy.py`·`validators.py` 와 같은 논거).

## 주입 seam

`Normalizer(stack=..., ranker=..., selector=...)` 로 사전·랭커·⑤ 선정기를
전부 주입받는다. 테스트가 파일도 네트워크도 건드리지 않는다.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field as dc_field
from typing import (
    TYPE_CHECKING,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
)

from . import policy, validators
from .glossary import GlossaryStack, Hit, IndexedTerm
from .keys import loose_key, normalize_key
from .policy import (
    CASCADE_VERSION,
    CONF_ALIAS,
    CONF_EXACT,
    CONF_FORMAT,
    CONF_PATTERN,
    CONF_PATTERN_VERIFIED,
    LLM_CONFIDENCE_CAP,
    MIN_CONFIDENCE,
    SIMILARITY_FLOOR,
    SINGLE_CANDIDATE_FLOOR,
    STAGE_ALIAS,
    STAGE_EXACT,
    STAGE_FORMAT,
    STAGE_LLM,
    STAGE_PATTERN,
    STAGE_SIMILARITY,
    TOP_K,
)
from .similarity import NGramRanker, Ranker
from .types import (
    Candidate,
    Evidence,
    FieldRef,
    GlossaryTerm,
    NormalizeResult,
    Notice,
    Stats,
    Suggestion,
    Unevaluated,
    Versions,
)

if TYPE_CHECKING:  # pragma: no cover - 타입 힌트 전용. 런타임에 ruleEngine 을 끌지 않는다.
    from f3_rules.types import LCTerms


# ════════════════════════════════════════════════════════════════
# 입력
# ════════════════════════════════════════════════════════════════


@dataclass
class DocumentInput:
    """`/normalize` 요청에 실린 서류 1건.

    `fields` 는 F1 산출물이든 S3 편집기에서 사람이 고친 dict 이든 **형태가
    같다** — `/verify` 가 두 경로를 가르지 않는 것과 같은 이유다. 값이
    `None` 인 필드는 "추출 실패"이지 "빈 값"이 아니므로 판정 대상에서 뺀다.

    `doc_id` 는 게이트웨이가 붙이는 서류 식별자다. 같은 종류의 서류가 한
    요청에 둘 이상 실릴 수 있고(선하증권 2장), 그때 `impact` 의 `FieldRef`
    가 어느 장을 가리키는지 이것 없이는 구분되지 않는다.
    """

    doc: str  # "선하증권" | "상업송장" | "포장명세서"
    fields: Dict[str, Optional[str]]
    doc_id: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# ⑤단계 경계 — T10(`llm_select.py`)이 구현할 계약
# ════════════════════════════════════════════════════════════════
#
# 이 세 타입을 `types.py` 가 아니라 여기에 두는 이유: `types.py` 는 **API 응답
# 스키마**다(게이트웨이·화면이 그 dict 를 그대로 읽는다). 반면 `SelectionItem`/
# `SelectionOutcome` 은 캐스케이드가 ⑤단계 구현에게 넘기는 **내부 계약**이고
# 응답에 나가지 않는다. 응답 스키마 파일에 섞어 두면 "이 필드도 게이트웨이가
# 받는 것"으로 읽히고, 한 번 그렇게 읽히면 실제로 응답에 실리는 날이 온다.
#
# ⑤ 는 **선택기이지 생성기가 아니다.** 그래서 `SelectionOutcome` 은 자유
# 문자열 `to_be` 가 아니라 **후보 번호(1-based)** 만 돌려준다. 주입이 100%
# 성공해도 모델이 할 수 있는 최대치가 "우리가 만든 후보 중 잘못된 것 고르기"
# 로 묶이는 것이 주입 방어의 본체이며, 그 방어는 프롬프트가 아니라 이 자료
# 구조가 한다.


@dataclass
class SelectionItem:
    """⑤ 에 넘길 항목 1건.

    `neighbors` 는 같은 서류의 다른 필드다 — 동음이의 판별의 유일한 문맥
    재료다. 크기 상한(인접 4개·값 200자)은 이 파일이 채워서 넘긴다:
    프롬프트 길이가 입력에 비례해 늘면 지연도 비용도 예측할 수 없고, 그
    한계는 프롬프트를 쓰는 쪽이 아니라 **항목을 만드는 쪽**이 지켜야 한다.
    """

    item_id: str
    term_class: str
    doc: str
    field: str
    value: str
    neighbors: Dict[str, str] = dc_field(default_factory=dict)
    candidates: List[Candidate] = dc_field(default_factory=list)


@dataclass
class SelectionOutcome:
    """⑤ 호출 1회의 결과.

    `choices` 는 `item_id → 후보 번호(1-based)` 다. 범위 밖 번호·모르는
    `item_id` 는 캐스케이드가 **폐기**한다(다른 값으로 고치지 않는다 — 규약을
    어긴 응답을 해석해 주면 규약이 없는 것과 같다).

    `llm_path` 는 `not_called | called | failed` 셋 중 하나다. `evidence.stage`
    만으로는 "⑤를 아예 안 태웠다"와 "태웠는데 실패했다"가 구분되지 않는다 —
    둘 다 최종 stage 가 `similarity` 로 남기 때문이다(`LLMNarrator` 폴백이
    `source="template"` 를 남기는 것과 같은 이유).

    `notices` 를 여기 둔 이유: 주입 마커 탐지(`Notice(kind="injection")`)는
    ⑤ 프롬프트를 만드는 쪽이 하는 일이라 T10 안에서 발생하는데, 그 결과는
    응답에 실려야 한다. 돌려줄 자리가 없으면 T10 이 로그로만 남기고 화면은
    아무것도 모른다.
    """

    choices: Dict[str, int] = dc_field(default_factory=dict)
    llm_path: str = "not_called"
    llm_model: Optional[str] = None
    llm_calls: int = 0
    reasons: Dict[str, str] = dc_field(default_factory=dict)
    notices: List[Notice] = dc_field(default_factory=list)


class Selector(Protocol):
    """⑤단계 구현(T10 `llm_select.py`)이 만족해야 하는 유일한 시그니처.

    호출은 **선적 1건당 1회**다(항목을 배치로 묶어 넘긴다). 필드마다 부르면
    8건 × 2초로 10초 예산을 넘긴다.
    """

    def select(self, items: List["SelectionItem"]) -> "SelectionOutcome": ...


# ════════════════════════════════════════════════════════════════
# 상수
# ════════════════════════════════════════════════════════════════

# 서류 필드 → 대응하는 `LCTerms` 필드명. **`f3_rules/types.py:LCTerms` 의
# 실제 필드명을 확인하고 썼다.** 이 표에 있는 필드는 L/C 값이 존재하기만 하면
# 사전 기반 교정(①②③④⑤)을 전부 끄고 ⓪format 만 남긴다.
_LC_FIELD_MAP: Dict[str, str] = {
    "port_of_loading": "port_of_loading",      # 44E
    "port_of_discharge": "port_of_discharge",  # 44F
    "consignee": "consignee",
    "notify_party": "notify_party",
    "description_of_goods": "description_of_goods",  # 45A
    "incoterms": "incoterms",
}

# 안내 메시지에 인용할 MT700 태그. 태그가 없는 필드(consignee 등)는 태그명을
# 지어내지 않는다 — 카드가 출처를 지어내는 것과 같은 실패다.
_LC_TAG: Dict[str, str] = {
    "port_of_loading": "44E",
    "port_of_discharge": "44F",
    "description_of_goods": "45A",
}

# 동음이의 판별 ①단계(값 안의 국가 신호)용 최소 국가명 표.
#
# **이 표는 원래 `locode.yaml` 에 있어야 한다.** 사전 항목처럼 인용되는
# 데이터이고, 국가·미국 주 약어를 늘리는 것은 코드 변경이 아니라 사전 편집
# 이어야 한다. 지금 카탈로그에 그 표가 없어(그리고 이 브랜치는 `terms/` 의
# 다른 파일을 고치지 않기로 했다) 후보 항목의 `country`(ISO2)와 대조할 수
# 있는 최소한만 코드에 둔다. **미국 주 약어(`PORTLAND, OR`)는 구현하지
# 않았다** — 50개 표를 코드에 하드코딩하는 것은 이 표가 데이터여야 한다는
# 판단과 정면으로 어긋나고, 절반만 채우면 "OR 은 걸러지고 WA 는 안 걸러지는"
# 조용한 비대칭이 생긴다.
_COUNTRY_NAME_ISO2: Dict[str, str] = {
    "KOREA": "KR",
    "SOUTH KOREA": "KR",
    "REPUBLIC OF KOREA": "KR",
    "한국": "KR",
    "대한민국": "KR",
    "USA": "US",
    "U.S.A": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "AMERICA": "US",
    "미국": "US",
    "AUSTRALIA": "AU",
    "호주": "AU",
    "CHINA": "CN",
    "중국": "CN",
    "JAPAN": "JP",
    "일본": "JP",
    "SINGAPORE": "SG",
    "싱가포르": "SG",
    "VIETNAM": "VN",
    "VIET NAM": "VN",
    "베트남": "VN",
    "GERMANY": "DE",
    "독일": "DE",
    "NETHERLANDS": "NL",
    "네덜란드": "NL",
    "UNITED KINGDOM": "GB",
    "ENGLAND": "GB",
    "영국": "GB",
    "CANADA": "CA",
    "캐나다": "CA",
    "SPAIN": "ES",
    "스페인": "ES",
    "CHILE": "CL",
    "칠레": "CL",
}

# 동음이의 판별에 쓸 인접 필드. 상대 항구를 먼저 본다 — 서류 안에서 가장
# 강한 신호이고(작성자가 같은 운송 건을 두고 쓴 값이다) 주소보다 잡음이 적다.
_NEIGHBOR_PORT_FIELDS: Tuple[str, ...] = (
    "port_of_loading",
    "port_of_discharge",
    "place_of_issue",
)
_NEIGHBOR_ADDRESS_FIELDS: Tuple[str, ...] = (
    "shipper",
    "consignee",
    "notify_party",
    "seller",
    "buyer",
)

# 자유서식 안에서 문구를 찾는 클래스. `container_no`/`hs_code` 는 전용
# 검증기가 따로 있고, `goods` 는 사전이 없어(needs_glossary=False) 문구
# 스캔 대상이 아니다.
_PHRASE_CLASSES: Tuple[str, ...] = ("practice_phrase", "transport_doc", "delivery")

# 자유서식 문구 스캔의 최소 길이(정규화 키 기준).
#
# `D/O`·`A/N`·`SUR` 같은 2~3자 약어는 자유서식 본문에서 평범한 영어 단어·
# 화인 문자열과 그대로 충돌한다("...do not stack..." 의 `do`). 정밀도를
# 재현율보다 우선한다는 원칙(§정밀도)에서, 이런 조각은 **제안하지 않는 쪽**이
# 옳다. 전용 필드가 생기면 그 필드는 `FIELD_CLASS` 경로(값 전체)로 가므로 이
# 하한의 영향을 받지 않는다.
_MIN_SCAN_SURFACE_LEN = 4

# HS 코드 스캔.
#
# 두 갈래인 이유: `HS` 라벨이 붙으면 점 없는 6자리(`847130`)도 HS 로 볼 수
# 있지만, 라벨이 없으면 **점이 찍힌 형태만** 본다. 라벨 없는 6자리 숫자를 HS
# 로 보면 컨테이너 일련번호·수량·금액이 전부 HS 코드가 된다.
_HS_SCAN_RE = re.compile(
    r"\bHS(?:\s*CODE)?\s*[:.\-]?\s*(?P<labelled>\d{4}[.\s]?\d{2}(?:[-\s]?\d{4})?)\b"
    r"|(?<![\d.])(?P<bare>\d{4}\.\d{2}(?:[-\s]?\d{4})?)(?![\d.])",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")

# 값 안의 국가 신호를 찾을 때 쓰는 토큰 분리기. 쉼표·괄호·슬래시까지 경계로
# 본다 — `"BUSAN, KOREA"` 의 `KOREA` 를 토큰으로 떼어내야 대조가 된다.
_TOKEN_SPLIT_RE = re.compile(r"[^0-9A-Za-z가-힣.]+")

# ⑤ 에 넘길 때의 크기 상한(§4.4 "크기 상한").
_LLM_MAX_NEIGHBORS = 4
_LLM_MAX_VALUE_CHARS = 200


# ════════════════════════════════════════════════════════════════
# 순수 헬퍼
# ════════════════════════════════════════════════════════════════


def _format_clean(text: str) -> str:
    """⓪format 이 허용하는 연산 **전부**: NFKC · 연속 공백 축약 · 앞뒤 공백 제거.

    대소문자를 바꾸지 않는 것이 핵심이다. 고유명사·품명(`party_name`·`goods`)
    이 타는 유일한 단계가 이것인데, 여기서 대소문자를 손대면 `"GAE WOON"` 이
    `"Gae Woon"` 이 되어 §고유명사 절제의 "허용: NFKC·공백" 을 넘는다. 표준
    표기의 대소문자로 맞추는 일은 사전이 답을 가진 ①②③ 의 몫이다.
    """
    s = unicodedata.normalize("NFKC", text or "")
    return _WHITESPACE_RE.sub(" ", s).strip()


def _is_cosmetic_change(as_is: str, to_be: str) -> bool:
    """두 값의 차이가 대소문자·공백·NFKC 뿐인가.

    `normalize_key` 는 NFKC → 대문자 → (한글·숫자·점 이외를 공백으로) →
    공백 축약이므로, 이 함수가 참이면 **글자 자체는 그대로**라는 뜻이다.
    단계 라벨을 `format` 으로 강등할지 판정하는 데 쓴다(모듈 docstring).
    """
    return normalize_key(as_is) == normalize_key(to_be)


def _skeleton_preserved(as_is: str, to_be: str) -> bool:
    """format 이 의미를 바꾸지 않았는가 — 글자·숫자 뼈대가 그대로인가.

    `policy.allows()` 가 "고유명사에 사전 조회를 허용하지 않는다"를 막지만,
    format 처리가 **실제로** 글자를 건드리지 않았는지는 이 파일의 책임이다
    (지시사항 §고유명사·품명 절제). NFKC 가 호환 문자를 펼치면서(`㎏`→`kg`)
    뼈대가 달라질 수 있는데, 그때는 제안을 만들지 않는다 — 형식 정리라고
    말하면서 값을 바꾸는 것이 이 기능에서 가장 위험한 실패 방향이다.
    """
    return loose_key(as_is) == loose_key(to_be)


def _port_face_already_covers(as_is: str, to_be: str) -> bool:
    """항구 클래스 전용: 원본 표기의 토큰이 `bl_form` 토큰을 이미 다 담고 있는가.

    `"BUSAN, KOREA"` 의 토큰 집합 `{BUSAN, KOREA}` 가 `bl_form` `"BUSAN"`
    의 토큰 `{BUSAN}` 을 포함하므로, 굳이 `"BUSAN"` 으로 줄이자는 카드를
    또 띄울 이유가 없다 — 이미 맞는 서류 면 표기를 건드리는 무의미한 카드가
    승인 게이트를 형식으로 만든다(모듈 상단 "정밀도" 원칙). `"PUSAN"` →
    `"BUSAN"` 처럼 토큰이 다르면 여전히 정상적으로 제안된다.
    """
    upper_as_is = unicodedata.normalize("NFKC", as_is or "").upper()
    upper_to_be = unicodedata.normalize("NFKC", to_be or "").upper()
    as_is_tokens = {t for t in _TOKEN_SPLIT_RE.split(upper_as_is) if t}
    to_be_tokens = {t for t in _TOKEN_SPLIT_RE.split(upper_to_be) if t}
    return bool(to_be_tokens) and to_be_tokens.issubset(as_is_tokens)


def _truncate(text: str, limit: int = _LLM_MAX_VALUE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit]


def _spans_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _country_tokens(text: str) -> Set[str]:
    """값 안에서 읽어낼 수 있는 국가 신호(ISO2 후보 + 국가명)를 모은다.

    ISO2 는 **2글자 토큰 전부**를 후보로 올린다 — 실제 판정은 "후보 항목의
    `country` 와 같은가"로만 하므로, 여기서 ISO 3166 전체 표를 들 필요가 없다
    (`_COUNTRY_NAME_ISO2` 주석의 "표는 데이터여야 한다" 논거와 같은 자리다).
    """
    upper = unicodedata.normalize("NFKC", text or "").upper()
    tokens = [t for t in _TOKEN_SPLIT_RE.split(upper) if t]
    found: Set[str] = set()
    for token in tokens:
        stripped = token.strip(".")
        if len(stripped) == 2 and stripped.isalpha():
            found.add(stripped)
        if stripped in _COUNTRY_NAME_ISO2:
            found.add(_COUNTRY_NAME_ISO2[stripped])
    # 두 단어 국가명("UNITED STATES", "SOUTH KOREA")은 토큰 단위로는 안 잡힌다.
    compact = " ".join(tokens)
    for name, iso2 in _COUNTRY_NAME_ISO2.items():
        if " " in name and name in compact:
            found.add(iso2)
    return found


# ════════════════════════════════════════════════════════════════
# 내부 자료구조
# ════════════════════════════════════════════════════════════════


@dataclass
class _Decision:
    """한 단계가 낸 결론. `Suggestion` 으로 조립되기 전의 중간 형태다.

    단계마다 `Suggestion` 을 직접 만들면 신뢰도 하한·`to_be == as_is` 정지·
    단계 라벨 강등·`impact` 부착 같은 **모든 단계에 공통인 규칙**이 단계 수만큼
    복제된다. 그중 하나가 빠지는 날 그 단계만 조용히 게이트를 통과한다.
    """

    stage: str
    to_be: Optional[str] = None
    confidence: float = 0.0
    hit: Optional[Hit] = None
    authority: Optional[str] = None
    candidates: List[Candidate] = dc_field(default_factory=list)
    requires_choice: bool = False
    # ⑤ 로 보낼 항목인가. `requires_choice=True` 인 채로 만들어 두고, 선정기가
    # 답을 주면 그때 확정으로 바꾼다(실패해도 카드는 남는다).
    llm_pending: bool = False
    score: float = 0.0
    message_extra: str = ""
    # 이 단계가 답을 낸 자리가 `_evaluate` 가 미리 계산해 둔 `ref.span` 과
    # 다를 때만 채운다(`qty_unit`/`volume_unit` — 필드 값 **전체**를 받았지만
    # 실제로 고치는 자리는 그 안의 단위 토큰뿐이다). `_evaluate` 가 이 값을
    # 보고 `ref` 를 다시 만든다 — span 을 여기서 못 넘기면 `_build` 는 필드
    # 전체를 span 으로 삼고, 그 상태로 나간 제안을 승인하면 `apply` 가 수치를
    # 포함해 값 전체를 갈아 끼운다.
    span: Optional[Tuple[int, int]] = None


@dataclass
class _Pending:
    """⑤ 대기 항목 — 만들어 둔 카드와 넘길 항목을 짝지어 둔다."""

    item: SelectionItem
    suggestion: Suggestion
    score: float


@dataclass
class _Run:
    """요청 1건의 누적 상태.

    `Normalizer` 인스턴스에 담지 않는 이유: 같은 `Normalizer` 를 여러 요청이
    재사용한다(사전·인덱스가 무거워 요청마다 만들 수 없다). 인스턴스에 쌓으면
    두 번째 요청이 첫 번째 요청의 제안을 물려받는다.
    """

    documents: List[DocumentInput]
    lc: Optional["LCTerms"] = None
    lc_raw_tags: Dict[str, str] = dc_field(default_factory=dict)
    suggestions: List[Suggestion] = dc_field(default_factory=list)
    notices: List[Notice] = dc_field(default_factory=list)
    unevaluated: List[Unevaluated] = dc_field(default_factory=list)
    pending: List[_Pending] = dc_field(default_factory=list)
    # normalize_key(값) → 그 값이 나타난 자리들. `impact` 의 재료다.
    occurrences: Dict[str, List[FieldRef]] = dc_field(default_factory=dict)
    stage_counts: Dict[str, int] = dc_field(default_factory=dict)

    def occurrence(self, as_is: str, ref: FieldRef) -> None:
        key = normalize_key(as_is)
        if not key:
            return
        refs = self.occurrences.setdefault(key, [])
        if ref not in refs:
            refs.append(ref)


# ════════════════════════════════════════════════════════════════
# Normalizer
# ════════════════════════════════════════════════════════════════


class Normalizer:
    """6단계 캐스케이드 본체.

    사전(`GlossaryStack`)·랭커(`Ranker`)·⑤ 선정기(`Selector`)를 전부
    주입받는다 — 테스트가 파일도 네트워크도 건드리지 않는다.
    `rules_catalog_version` 은 `Versions` 에 그대로 실린다(F3 룰 카탈로그와
    같은 시점의 판정이었음을 사후 대조하기 위한 값이고, F3 를 안 탄 요청은
    `None` 이다).
    """

    def __init__(
        self,
        stack: GlossaryStack,
        ranker: Optional[Ranker] = None,
        selector: Optional[Selector] = None,
        *,
        rules_catalog_version: Optional[str] = None,
    ) -> None:
        self.stack = stack
        self.ranker: Ranker = ranker or NGramRanker()
        self.selector = selector
        self.rules_catalog_version = rules_catalog_version
        # 표준 계층이 `layers[0]` 이라는 계약은 `GlossaryStack` 이 세운 것이다.
        self.glossary_version = (
            stack.layers[0].catalog_version if stack.layers else ""
        )
        # 자유서식 문구 스캔용 정규식 캐시. 사전 항목 수백 건 × 별칭이라
        # 요청마다 컴파일하면 그 자체가 예산을 먹는다(카탈로그를 기동 시 1회만
        # 읽는 것과 같은 이유).
        self._phrase_cache: Dict[str, List[Tuple[re.Pattern, IndexedTerm]]] = {}

    # ── 공개 진입점 ──────────────────────────────────────────────

    def normalize(
        self,
        documents: List[DocumentInput],
        lc: Optional["LCTerms"] = None,
        lc_raw_tags: Optional[Dict[str, str]] = None,
        llm: bool = False,
    ) -> NormalizeResult:
        """서류 묶음 → 제안·안내·유보.

        `elapsed_ms` 는 `time.perf_counter()` 로 잰다. **`datetime.now()` 를
        부르지 않는다** — 이 저장소는 시각을 주입받는 규약이고(`Correction.
        decided_at` 이 요청에서 오는 것과 같은 이유), 단조 시계로 재는 경과
        시간은 벽시계와 달리 판정에 섞이지 않는다.
        """
        started = time.perf_counter()

        raw_tags = dict(lc_raw_tags or {})
        if lc is None and raw_tags:
            lc = self._terms_from_tags(raw_tags)

        run = _Run(documents=list(documents), lc=lc, lc_raw_tags=raw_tags)

        for document in run.documents:
            self._process_document(run, document)

        self._resolve_llm(run, llm)
        self._attach_impact(run)

        # 같은 필드·같은 사유의 유보가 단계마다(①②③...) 쌓인다 — 예를 들어
        # bl_form 누락은 alias 단계가 실패해도 계속 내려가 similarity 단계도
        # 같은 이유로 또 남긴다. 화면에 같은 사유가 두 번 반복될 이유가
        # 없으니 여기서 한 건으로 접는다. `FieldRef` 는 frozen dataclass라
        # 해시 가능하다.
        seen_unevaluated: set = set()
        deduped_unevaluated: List[Unevaluated] = []
        for item in run.unevaluated:
            key = (item.field, item.reason)
            if key in seen_unevaluated:
                continue
            seen_unevaluated.add(key)
            deduped_unevaluated.append(item)
        run.unevaluated = deduped_unevaluated

        # `by_stage` 는 최종 `run.suggestions` 에서 한 번에 센다(집계 시점을
        # 등록 시점으로 앞당기지 않는 이유는 `_register` docstring 참고) —
        # ⑤ 확정이 stage 를 바꾸거나 제안을 지운 **뒤의** 상태라야 합계가
        # `len(suggestions)` 와 어긋나지 않는다.
        run.stage_counts = {}
        for suggestion in run.suggestions:
            stage = suggestion.evidence.stage
            run.stage_counts[stage] = run.stage_counts.get(stage, 0) + 1

        versions = Versions(
            glossary_version=self.glossary_version,
            cascade_version=CASCADE_VERSION,
            rules_catalog_version=self.rules_catalog_version,
            llm_model=None,
            ranker=getattr(self.ranker, "name", type(self.ranker).__name__),
        )
        stats = Stats(
            by_stage=dict(sorted(run.stage_counts.items())),
            llm_path=run_llm_path(run),
            llm_calls=getattr(run, "_llm_calls", 0),
            elapsed_ms=int(round((time.perf_counter() - started) * 1000)),
        )
        # ⑤ 를 실제로 탔을 때만 모델명을 싣는다 — 안 탔으면 `None` 이어야
        # "어느 모델이 판정했는가"를 화면이 지어내지 않는다.
        model = getattr(run, "_llm_model", None)
        if model:
            versions.llm_model = model

        return NormalizeResult(
            suggestions=run.suggestions,
            notices=run.notices,
            unevaluated=run.unevaluated,
            versions=versions,
            stats=stats,
        )

    # ── 서류 · 필드 ──────────────────────────────────────────────

    def _process_document(self, run: _Run, document: DocumentInput) -> None:
        neighbors = {
            name: value
            for name, value in (document.fields or {}).items()
            if isinstance(value, str) and value.strip()
        }
        for name, value in (document.fields or {}).items():
            self._process_field(run, document, name, value, neighbors)

    def _process_field(
        self,
        run: _Run,
        document: DocumentInput,
        name: str,
        value: Optional[str],
        neighbors: Dict[str, str],
    ) -> None:
        if not isinstance(value, str) or not value.strip():
            # 값이 없는 필드는 "판단 유보"가 아니라 판단할 대상 자체가 없다.
            # 여기서 `Unevaluated` 를 만들면 빈 서류 하나가 유보 20건을 낳고,
            # 그 순간 유보 목록이 신호가 아니라 잡음이 된다.
            return

        whole_class = policy.FIELD_CLASS.get(name)
        scan_classes = policy.FIELD_SCAN_CLASSES.get(name, ())
        field_ref = FieldRef(doc=document.doc, field=name, doc_id=document.doc_id)

        # 값 전체가 이미 어떤 클래스의 표준 표기라면 **그 안을 조각내지 않는다.**
        #
        # `"Original B/L"` 은 `transport_doc` 의 canonical 이라 고칠 것이 없는데,
        # `practice_phrase` 의 canonical `"ORIGINAL"` 이 그 안의 `"Original"` 에
        # 걸려 대문자 교정을 제안했다. 서류에는 아무 문제가 없는데 카드가 하나
        # 뜬다. 이런 카드가 쌓이면 사람이 카드를 읽지 않게 되고, 그 순간 승인
        # 게이트가 형식이 된다(§정밀도를 재현율보다 우선한다).
        #
        # 클래스를 가리지 않고 검사하는 이유: 어느 클래스의 표준이든 **이미
        # 표준인 값**이라는 사실은 같고, 한 클래스의 표준 안에서 다른 클래스의
        # 조각을 찾는 것은 정의상 오탐이다.
        if scan_classes and self._is_canonical_value(value):
            scan_classes = ()

        if not whole_class and not scan_classes:
            # 침묵하지 않는다 — "검사하고 통과"와 "검사하지 않음"은 다르다.
            run.unevaluated.append(
                Unevaluated(
                    field=field_ref,
                    reason="클래스를 판별할 수 없습니다",
                    score=None,
                    as_is=value,
                )
            )
            return

        run.occurrence(value, field_ref)

        guard = self._lc_guard(run, name, value)
        if guard:
            lc_value, tag = guard
            run.notices.append(
                Notice(
                    kind="lc_wording",
                    severity="info",
                    field=field_ref,
                    message=self._lc_message(tag, lc_value),
                )
            )

        produced: List[Suggestion] = []

        # ── 경로 1: 필드 값 **전체**가 한 클래스 (span=None) ──
        whole_suggestion: Optional[Suggestion] = None
        if whole_class:
            whole_suggestion = self._evaluate(
                run,
                document,
                field_ref,
                whole_class,
                value,
                neighbors,
                lc_guarded=bool(guard),
            )
            if whole_suggestion:
                produced.append(whole_suggestion)

        # ── 경로 2: 자유서식 안의 **조각** (span 필수) ──
        span_suggestions: List[Suggestion] = []
        full_span_suggestions: List[Suggestion] = []
        for term_class in scan_classes:
            for suggestion in self._scan(
                run,
                document,
                field_ref,
                term_class,
                value,
                neighbors,
                lc_guarded=bool(guard),
            ):
                span = suggestion.field.span or (0, len(value))
                if span == (0, len(value)):
                    full_span_suggestions.append(suggestion)
                else:
                    span_suggestions.append(suggestion)

        span_suggestions = _resolve_overlaps(span_suggestions)

        # 값 **전체**를 덮는 제안(`goods` 의 format, `party_name` 의 format)은
        # 조각 제안과 함께 적용될 수 없다. 둘 다 승인되면 전체 치환이 먼저
        # 일어나 조각의 span 오프셋이 어긋나고, `apply` 가 엉뚱한 자리를
        # 갈아 끼운다. 조각 쪽이 더 구체적인 판단이므로 전체 쪽이 양보한다.
        if span_suggestions:
            full_span_suggestions = []
            if whole_suggestion is not None and whole_suggestion.evidence.stage == STAGE_FORMAT:
                produced = [s for s in produced if s is not whole_suggestion]

        produced.extend(full_span_suggestions)
        produced.extend(span_suggestions)

        for suggestion in produced:
            self._register(run, suggestion)

        if not produced and guard:
            # L/C 로 사전 경로를 끈 필드는 "검사하고 통과"가 아니다.
            run.unevaluated.append(
                Unevaluated(
                    field=field_ref,
                    reason="L/C 문언이 지정되어 있어 사전 기반 교정을 하지 않았습니다",
                    score=None,
                    as_is=value,
                )
            )

    # ── 경로 1: 값 전체 ─────────────────────────────────────────

    def _evaluate(
        self,
        run: _Run,
        document: DocumentInput,
        field_ref: FieldRef,
        term_class: str,
        as_is: str,
        neighbors: Dict[str, str],
        *,
        lc_guarded: bool,
        span: Optional[Tuple[int, int]] = None,
    ) -> Optional[Suggestion]:
        """한 대상(필드 전체 또는 조각) 하나에 캐스케이드를 돌린다."""
        ref = (
            field_ref
            if span is None
            else FieldRef(
                doc=field_ref.doc,
                field=field_ref.field,
                doc_id=field_ref.doc_id,
                span=span,
            )
        )
        decision = self._decide(
            run, document, ref, term_class, as_is, neighbors, lc_guarded=lc_guarded
        )
        if decision is None:
            return None
        if decision.span is not None and decision.span != ref.span:
            # `_decide_unit_quantity` 처럼 단계가 `ref` 보다 더 좁은 자리
            # (단위 토큰만)에 답을 냈다 — `_build` 에 넘기는 `ref` 를 그
            # 자리로 좁힌다. 그러지 않으면 `_build` 는 필드 전체를 span 으로
            # 삼고, `apply` 가 수치까지 포함해 값 전체를 갈아 끼운다.
            ref = FieldRef(
                doc=ref.doc, field=ref.field, doc_id=ref.doc_id, span=decision.span
            )
            # span 계약: `span` 이 있으면 `as_is` 는 **그 자리의 부분 문자열**이다.
            # 좁힌 span 에 넓은 `as_is` 를 그대로 물리면 카드가 "1,234.50 KGS →
            # KGM" 으로 보이고, 그 쌍만 보고 치환하면 수치가 사라진다.
            start, end = decision.span
            as_is = as_is[start:end]
        return self._build(run, ref, term_class, as_is, decision, neighbors)

    def _decide(
        self,
        run: _Run,
        document: DocumentInput,
        ref: FieldRef,
        term_class: str,
        as_is: str,
        neighbors: Dict[str, str],
        *,
        lc_guarded: bool,
    ) -> Optional[_Decision]:
        """단계를 순서대로 물어 첫 결론을 돌려준다. 진입은 `policy.allows()` 로만."""
        clean = _format_clean(as_is)

        # ⓪ format — 사전을 못 쓰는 클래스(party_name·goods)와 L/C 고정 필드는
        # 여기서 끝난다. 그 밖의 클래스는 아래 단계가 낸 답이 대소문자·공백만
        # 다를 때 `_relabel_format` 이 사후에 이 단계로 강등한다.
        format_only = lc_guarded or not policy.CLASSES.get(term_class, None) or not (
            policy.CLASSES[term_class].needs_glossary
        )
        if format_only:
            if not policy.allows(term_class, STAGE_FORMAT):
                return None
            if clean == as_is or not _skeleton_preserved(as_is, clean):
                return None
            return _Decision(stage=STAGE_FORMAT, to_be=clean, confidence=CONF_FORMAT)

        # price_term 은 ①②③ 순서를 따르지 않는다 — 아래 함수의 docstring 참고.
        if term_class == "price_term":
            return self._decide_price_term(run, ref, clean, neighbors)

        if term_class in ("qty_unit", "volume_unit"):
            return self._decide_unit_quantity(run, ref, term_class, as_is)

        # ① exact
        if policy.allows(term_class, STAGE_EXACT):
            hits = self.stack.lookup(clean, term_class, alias=False)
            decision = self._from_hits(
                run, ref, term_class, clean, hits, neighbors, STAGE_EXACT, CONF_EXACT
            )
            if decision:
                return decision

        # ② alias
        if policy.allows(term_class, STAGE_ALIAS):
            hits = self.stack.lookup(clean, term_class, alias=True)
            decision = self._from_hits(
                run, ref, term_class, clean, hits, neighbors, STAGE_ALIAS, CONF_ALIAS
            )
            if decision:
                return decision

        # ③ pattern — 클래스별 결정론 검증기.
        if policy.allows(term_class, STAGE_PATTERN):
            decision = self._decide_pattern(run, ref, term_class, clean, neighbors)
            if decision:
                return decision

        # ④ similarity
        if policy.allows(term_class, STAGE_SIMILARITY):
            return self._decide_similarity(run, ref, term_class, clean, as_is, neighbors)

        return None

    # ── 단계 구현 ────────────────────────────────────────────────

    def _from_hits(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        query: str,
        hits: Sequence[Hit],
        neighbors: Dict[str, str],
        stage: str,
        confidence: float,
    ) -> Optional[_Decision]:
        """①/② 의 조회 결과를 결론으로 바꾼다.

        **히트가 2건 이상이면 자동 확정하지 않는다.** 항구 동음이의(PORTLAND)
        가 정확히 이 모양으로 들어오며, 여기서 "첫 번째"를 고르면 기획안이
        못박은 임의 선택 금지가 조용히 깨진다. 판별 순서(값 안의 국가 신호 →
        인접 필드 → L/C → ⑤)를 태우고, 그래도 하나로 못 줄이면
        `requires_choice` 다.
        """
        if not hits:
            return None
        if len(hits) == 1:
            hit = hits[0]
            to_be = self._applied_form(hit.term)
            if to_be is None:
                self._unevaluated_missing_bl_form(run, ref, confidence, query)
                return None
            return _Decision(
                stage=stage, to_be=to_be, confidence=confidence, hit=hit
            )

        resolved = self._disambiguate(run, ref, term_class, query, hits, neighbors)
        if resolved is not None:
            to_be = self._applied_form(resolved.term)
            if to_be is None:
                self._unevaluated_missing_bl_form(run, ref, confidence, query)
                return None
            return _Decision(
                stage=stage,
                to_be=to_be,
                confidence=confidence,
                hit=resolved,
            )

        candidates = [_candidate_of(hit.term, score=1.0) for hit in hits]
        candidates = [c for c in candidates if c is not None]
        if not candidates:
            self._unevaluated_missing_bl_form(run, ref, 1.0, query)
            return None
        candidates.sort(key=lambda c: (c.term_id or ""))
        return _Decision(
            stage=stage,
            to_be=None,
            confidence=confidence,
            candidates=candidates,
            requires_choice=True,
            llm_pending=policy.allows(term_class, STAGE_LLM),
            score=1.0,
        )

    def _decide_pattern(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        clean: str,
        neighbors: Dict[str, str],
    ) -> Optional[_Decision]:
        """③ — 값 **전체**에 대한 결정론 검증기.

        `container_no`/`hs_code` 는 값 전체가 아니라 자유서식 조각으로만
        들어오므로(`FIELD_CLASS` 에 없다) 여기 오지 않는다. 오더라도 `_scan`
        과 같은 검증기를 태운다.
        """
        if term_class == "port":
            check = validators.validate_locode(clean)
            if not check.ok:
                return None
            # 형식만 맞다 — `check.normalized` 는 코드지 서류 면 표기가
            # 아니다. ①exact 와 같은 사전 역조회(canonical=코드)를 태워야
            # `to_be` 가 코드 그대로 나가지 않는다("KR PUS" → "KRPUS" 로
            # 끝내면 사전에 있는 항구인데도 코드가 서류에 박힌다). `_from_hits`
            # 가 동음이의·bl_form 누락까지 ①②와 같은 규칙으로 처리해 준다.
            hits = self.stack.lookup(check.normalized, term_class, alias=False)
            if not hits:
                # 형식은 맞지만 사전 어디에도 없는 코드(예: "US SEA" →
                # "USSEA")다. 형식만 맞다고 없는 표기를 지어내지 않는다 —
                # bl_form 누락과는 다른 사유라 별도로 남긴다.
                run.unevaluated.append(
                    Unevaluated(
                        field=ref,
                        reason="사전에 없는 항구 코드라 선하증권 표기를 알 수 없습니다",
                        score=CONF_PATTERN,
                        as_is=clean,
                    )
                )
                return None
            return self._from_hits(
                run, ref, term_class, check.normalized, hits, neighbors, STAGE_PATTERN, CONF_PATTERN
            )
        if term_class == "container_no":
            return self._container_decision(clean)
        if term_class == "hs_code":
            return self._hs_decision(clean)
        if term_class == "party_suffix":
            return self._suffix_decision(clean)
        return None

    def _decide_similarity(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        clean: str,
        as_is: str,
        neighbors: Dict[str, str],
    ) -> Optional[_Decision]:
        """④ — 3-gram Dice 상위 K.

        `rank_detailed()` 를 쓰는 이유는 컷오프로 사라진 최고점을 `Unevaluated`
        에 실어야 하기 때문이다 — "0.41 이라 안 했다"와 "사전에 없어 못 했다"는
        서로 다른 후속 작업을 가리킨다.
        """
        pool = self.stack.pool(term_class)
        result = self.ranker.rank_detailed(clean, pool, TOP_K) if hasattr(
            self.ranker, "rank_detailed"
        ) else None
        if result is None:
            candidates = list(self.ranker.rank(clean, pool, TOP_K))
            best = max((c.score for c in candidates), default=0.0)
        else:
            candidates = list(result.candidates)
            best = result.best_score

        if not candidates:
            run.unevaluated.append(
                Unevaluated(
                    field=ref,
                    reason=(
                        f"유사도 최고 점수 {best:.2f} < {SIMILARITY_FLOOR}"
                        if pool
                        else "이 클래스의 후보 풀이 비어 있습니다"
                    ),
                    score=best,
                    as_is=as_is,
                )
            )
            return None

        # 랭커의 `Candidate.to_be` 는 `display or canonical` 이다. 적용되는 값은
        # **언제나 `_applied_form()`**(항구는 bl_form, 그 밖은 canonical)이어야
        # 하므로(display 는 메시지 전용) 여기서 되돌린다 — 섞이면 적용되는
        # 값이 카드 문구에 따라 달라진다. 항구인데 bl_form 이 없는 후보는
        # `None` 이 되어 목록에서 빠진다(조용히 코드로 되돌리지 않는다).
        candidates = [self._canonicalize(c) for c in candidates]
        candidates = [c for c in candidates if c is not None]
        if not candidates:
            self._unevaluated_missing_bl_form(run, ref, best, as_is)
            return None

        if len(candidates) == 1 and candidates[0].score >= SINGLE_CANDIDATE_FLOOR:
            # 고를 것이 하나뿐인데 "고르라"고 물으면 답은 정해져 있고 비용·
            # 지연·주입면만 늘어난다.
            top = candidates[0]
            hit = self._hit_by_term_id(top.term_id)
            return _Decision(
                stage=STAGE_SIMILARITY,
                to_be=top.to_be,
                confidence=min(0.88, 0.55 + 0.35 * top.score),
                hit=hit,
                score=top.score,
            )

        if term_class == "port":
            hits = [h for h in (self._hit_by_term_id(c.term_id) for c in candidates) if h]
            resolved = self._disambiguate(run, ref, term_class, clean, hits, neighbors)
            if resolved is not None:
                score = next(
                    (c.score for c in candidates if c.term_id == resolved.term.term_id),
                    candidates[0].score,
                )
                # `hits`/`resolved` 는 위에서 이미 bl_form 필터를 통과한
                # `candidates` 에서만 파생되므로 여기서 None 이 될 수 없지만,
                # 침묵 금지 원칙을 지키려고 방어적으로 확인한다.
                to_be = self._applied_form(resolved.term)
                if to_be is None:
                    self._unevaluated_missing_bl_form(run, ref, score, as_is)
                    return None
                return _Decision(
                    stage=STAGE_SIMILARITY,
                    to_be=to_be,
                    confidence=min(0.88, 0.55 + 0.35 * score),
                    hit=resolved,
                    score=score,
                )

        top_score = candidates[0].score
        return _Decision(
            stage=STAGE_SIMILARITY,
            to_be=None,
            confidence=min(0.88, 0.55 + 0.35 * top_score),
            candidates=candidates,
            requires_choice=True,
            llm_pending=policy.allows(term_class, STAGE_LLM),
            score=top_score,
        )

    # ── 클래스별 전용 경로 ───────────────────────────────────────

    def _decide_price_term(
        self,
        run: _Run,
        ref: FieldRef,
        clean: str,
        neighbors: Dict[str, str],
    ) -> Optional[_Decision]:
        """가격조건 — ③ 을 ①② 보다 **먼저** 본다.

        Incoterms 2020 의 표준형은 조건 코드 단독이 아니라 `조건 + 장소 병기`
        (`FOB Busan (Incoterms 2020)`)다. 그래서 값이 사전의 canonical(`FOB`)
        과 같다는 사실이 "이미 표준"을 뜻하지 않는다. ① 을 먼저 돌리면
        `"FOB"` 가 `to_be == as_is` 로 즉시 종결해 **장소 병기 규칙이 절대
        발동하지 않는 죽은 코드**가 된다. 단계 라벨(`pattern`)은 그대로 두고
        평가 순서만 바꾼다.
        """
        parsed = validators.parse_price_term(clean)
        code: Optional[str] = parsed.code if parsed else None
        place: Optional[str] = parsed.place if parsed else None
        place_field: Optional[str] = parsed.place_side_field if parsed else None
        hit: Optional[Hit] = None

        if code is None:
            # `EX WORKS`·`공장인도` 처럼 코드 형태가 아닌 표기는 사전이 안다.
            for stage, allow in ((STAGE_EXACT, False), (STAGE_ALIAS, True)):
                if not policy.allows("price_term", stage):
                    continue
                hits = self.stack.lookup(clean, "price_term", alias=allow)
                if len(hits) == 1:
                    hit = hits[0]
                    code = hit.term.canonical
                    place_field = validators.parse_price_term(code)
                    place_field = place_field.place_side_field if place_field else None
                    break
            if code is None:
                return None

        if place:
            return _Decision(
                stage=STAGE_PATTERN,
                to_be=validators.format_price_term(code, place),
                confidence=CONF_PATTERN,
                hit=hit,
                authority=policy.CLASSES["price_term"].default_authority,
            )

        # 장소가 없다. **지어내지 않는다** — `_PLACE_SIDE` 가 가리키는 인접
        # 필드에서 후보 1건을 만들어 사람에게 넘긴다. 조건마다 장소의 의미가
        # 다르므로(적출지 vs 도착지) 아무 항구나 끌어오면 가격 조건의 실질이
        # 바뀐다.
        neighbor_value = (neighbors.get(place_field or "") or "").strip()
        if not neighbor_value:
            run.notices.append(
                Notice(
                    kind="not_covered",
                    severity="warning",
                    field=ref,
                    message=(
                        f"가격조건 '{clean}' 에 장소가 없고 인접 필드"
                        f"({place_field or '해당 없음'})도 비어 있어 장소를 만들 수 없습니다. "
                        "Incoterms 2020 은 장소 병기가 필수입니다."
                    ),
                )
            )
            return None

        candidate = Candidate(
            to_be=validators.format_price_term(code, _format_clean(neighbor_value)),
            term_id=hit.term.term_id if hit else None,
            authority=policy.CLASSES["price_term"].default_authority,
            score=0.0,
            reason=f"인접 {place_field}",
        )
        return _Decision(
            stage=STAGE_PATTERN,
            to_be=None,
            confidence=CONF_PATTERN,
            hit=hit,
            candidates=[candidate],
            requires_choice=True,
            # price_term 의 ⑤ 는 "장소 병기 판별만" 허용된다. 후보가 1건뿐이라
            # 고를 것이 없으므로 여기서는 넘기지 않는다.
            llm_pending=False,
            message_extra="장소 병기가 필요합니다.",
        )

    def _decide_unit_quantity(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        as_is: str,
    ) -> Optional[_Decision]:
        """`qty_unit`/`volume_unit` 필드 값 **전체**(`"1,234.50 KGS"`)에서
        단위 토큰만 갈라 `_decide_unit_token` 에 넘긴다.

        `_decide_unit_token` 은 토큰(`"KGS"`)을 기대하는데 이 클래스는 값
        전체가 필드로 들어온다(`policy.FIELD_CLASS` — 수치와 단위가 한
        문자열이다). 값 전체를 그대로 넘기면 조회가 전부 빗나가 조용히
        `None` 이 되고, 제안도 유보도 없이 사라진다 — 정밀도를 재현율보다
        우선한다는 원칙(§정밀도)에 정면으로 어긋난다. **`as_is` 는 원문
        그대로**(⓪format 정리 전) 써야 한다 — `_Decision.span` 이 가리키는
        오프셋이 `apply`(T11)가 실제로 치환할 문자열과 같은 좌표계여야
        하기 때문이다.
        """
        split = validators.split_quantity(as_is)
        if split is None:
            run.unevaluated.append(
                Unevaluated(
                    field=ref,
                    reason="단위 토큰을 찾을 수 없습니다",
                    score=None,
                    as_is=as_is,
                )
            )
            return None

        _number, token, span = split
        token_decision = self._decide_unit_token(term_class, token)
        if token_decision is None:
            # Rec 20 은 닫힌 집합이다 — "비슷한 단위"를 추측하지 않는다
            # (`_decide_unit_token` docstring). 토큰은 찾았으니 침묵하지
            # 않고 안내한다.
            start, end = span
            token_ref = FieldRef(doc=ref.doc, field=ref.field, doc_id=ref.doc_id, span=span)
            run.notices.append(
                Notice(
                    kind="not_covered",
                    severity="info",
                    field=token_ref,
                    message=(
                        f"단위 '{as_is[start:end]}' 은 UN/ECE Rec 20 표준 단위 집합에 "
                        "없습니다. 집합이 닫혀 있어 비슷한 단위로 추측하지 않습니다."
                    ),
                )
            )
            return None

        start, end = span
        # **`span` 과 `to_be` 는 같은 좌표계여야 한다.**
        #
        # 이 파일의 span 계약은 하나다 — `span` 이 있으면 `as_is` 는 그 자리의
        # 부분 문자열이고 `to_be` 는 **그 자리만** 대신한다. `apply`(T11)는
        # `value[:start] + to_be + value[end:]` 를 할 뿐이다.
        #
        # 한때 여기서 `to_be` 에 필드 값 전체(`"1,234.50 KGM"`)를 담으면서
        # `span` 은 단위 토큰만 가리켰다. 그러면 치환 결과가
        # `"1,234.50 1,234.50 KGM"` 이 된다 — 수치가 복제된다. 화면 표기가
        # 친절한지는 UI 가 `field` 와 함께 렌더링해 해결할 문제이고, 치환
        # 계약을 흔들어 살 것이 아니다.
        #
        # 토큰만 담으면 **수치는 구조적으로 보존된다.** span 이 숫자를 덮지
        # 않으므로 `apply` 가 아무리 잘못 짜여도 수치를 건드릴 수 없다.
        # 규칙으로 막는 것과 구조로 막는 것의 차이다(§고유명사·품명 절제의
        # `party_suffix` 와 같은 논리).
        if token_decision.to_be == as_is[start:end]:
            # 단위가 이미 표준(KGM 등)이었다 — 제안도 유보도 만들지 않는다.
            return None

        return _Decision(
            stage=token_decision.stage,
            to_be=token_decision.to_be,
            confidence=token_decision.confidence,
            hit=token_decision.hit,
            authority=token_decision.authority,
            span=span,
        )

    def _decide_unit_token(self, term_class: str, token: str) -> Optional[_Decision]:
        """수량·용적 단위 토큰 하나를 Rec 20 코드로.

        ④유사도가 금지된 클래스다 — Rec 20 집합은 **닫혀 있어** 사전에 없으면
        "비슷한 단위"가 아니라 **모르는 단위**다. 사전(①②)에도 검증기(③)에도
        없으면 `Notice(not_covered)` 를 만들 수 있도록 `None` 을 돌려준다.
        """
        for stage, allow, conf in (
            (STAGE_EXACT, False, CONF_EXACT),
            (STAGE_ALIAS, True, CONF_ALIAS),
        ):
            if not policy.allows(term_class, stage):
                continue
            hits = self.stack.lookup(token, term_class, alias=allow)
            if len(hits) == 1:
                # 이 클래스(qty_unit/volume_unit)는 절대 "port" 가 아니므로
                # `_applied_form` 은 항상 canonical 을 그대로 돌려준다 —
                # 그래도 단일 진입점을 통과시켜 두는 게 일관적이다.
                return _Decision(
                    stage=stage,
                    to_be=self._applied_form(hits[0].term),
                    confidence=conf,
                    hit=hits[0],
                )
        if policy.allows(term_class, STAGE_PATTERN):
            unit = validators.unit_code(token)
            if unit:
                # 닫힌 집합 조회를 통과했다 — 결정론 검증 통과이므로 0.97.
                return _Decision(
                    stage=STAGE_PATTERN,
                    to_be=unit.code,
                    confidence=CONF_PATTERN_VERIFIED,
                    authority=policy.CLASSES[term_class].default_authority,
                )
        return None

    def _container_decision(self, text: str) -> Optional[_Decision]:
        """ISO 6346 — 체크디지트가 맞을 때만 제안이 된다.

        틀리면 **교정 제안을 만들지 않는다.** 어느 자리(소유자·구분자·일련·
        체크디지트 자신)가 틀렸는지 알 수 없으므로 고치는 것은 추측이다.
        호출부가 `Notice(kind="deterministic_error")` 를 만든다.
        """
        check = validators.validate_container(text)
        if not check.matched or not check.ok or not check.normalized:
            return None
        return _Decision(
            stage=STAGE_PATTERN,
            to_be=check.normalized,
            confidence=CONF_PATTERN_VERIFIED,
            authority=policy.CLASSES["container_no"].default_authority,
        )

    def _hs_decision(self, text: str) -> Optional[_Decision]:
        code = validators.normalize_hs(text)
        if code is None:
            return None
        return _Decision(
            stage=STAGE_PATTERN,
            to_be=code.hsk or code.normalized,
            confidence=CONF_PATTERN_VERIFIED,
            authority=policy.CLASSES["hs_code"].default_authority,
        )

    def _suffix_decision(self, text: str) -> Optional[_Decision]:
        """상호 접미 — 표 치환이라 결정론 검증이랄 것이 없어 0.90 이다."""
        check = validators.party_suffix(text)
        if not check.matched or not check.to_be:
            return None
        # 사전 조회가 아니라 **근거 부착**이다. `party_suffix` 는 ①② 가
        # 금지된 클래스이고 값은 이미 `validators` 가 정했다 — 여기서 사전을
        # 보는 것은 카드에 실을 `term_id`·`authority` 를 진짜 항목에서
        # 가져오기 위해서다(없으면 카드가 출처를 지어낸다).
        hit: Optional[Hit] = None
        hits = self.stack.lookup(check.to_be, "party_suffix", alias=True)
        if len(hits) == 1:
            hit = hits[0]
        return _Decision(
            stage=STAGE_PATTERN,
            to_be=check.to_be,
            confidence=CONF_PATTERN,
            hit=hit,
            authority=policy.CLASSES["party_suffix"].default_authority,
        )

    # ── 경로 2: 자유서식 스캔 ────────────────────────────────────

    def _scan(
        self,
        run: _Run,
        document: DocumentInput,
        field_ref: FieldRef,
        term_class: str,
        value: str,
        neighbors: Dict[str, str],
        *,
        lc_guarded: bool,
    ) -> List[Suggestion]:
        """자유서식 값 안에서 `term_class` 의 조각을 찾는다.

        **스캔은 언제나 원본 문자열 위에서 한다.** 정리된 사본에서 span 을
        재면 오프셋이 원본과 어긋나 `apply` 가 엉뚱한 자리를 갈아 끼운다.
        """
        if term_class in ("party_name", "goods"):
            return self._scan_whole_format(run, field_ref, term_class, value, lc_guarded)

        if lc_guarded:
            # L/C 가 고정한 필드에서는 ①②③④⑤ 를 전부 끈다 — ③(결정론 검증기)
            # 도 포함이다. 서류 값이 L/C 와 어긋나는지는 이미 F3 의
            # `match_place` 가 잡으므로, F2 가 같은 자리에 다른 판단을 내면
            # 화면에 서로 모순되는 두 카드가 뜬다.
            return []

        if term_class == "party_suffix":
            return self._scan_party_suffix(run, field_ref, value)
        if term_class == "container_no":
            return self._scan_container(run, field_ref, value)
        if term_class == "hs_code":
            return self._scan_hs(run, field_ref, value)
        if term_class in _PHRASE_CLASSES:
            return self._scan_phrases(run, document, field_ref, term_class, value, neighbors)
        return []

    def _scan_whole_format(
        self,
        run: _Run,
        field_ref: FieldRef,
        term_class: str,
        value: str,
        lc_guarded: bool,
    ) -> List[Suggestion]:
        """`party_name`·`goods` — 값 전체의 형식 정리(⓪만).

        span 은 `(0, len(value))` 로 값 전체를 가리킨다. 조각 제안과 함께
        승인될 수 없다는 사실은 `_process_field` 가 처리한다.
        """
        if not policy.allows(term_class, STAGE_FORMAT):
            return []
        clean = _format_clean(value)
        if clean == value or not _skeleton_preserved(value, clean):
            return []
        ref = FieldRef(
            doc=field_ref.doc,
            field=field_ref.field,
            doc_id=field_ref.doc_id,
            span=(0, len(value)),
        )
        suggestion = self._build(
            run,
            ref,
            term_class,
            value,
            _Decision(stage=STAGE_FORMAT, to_be=clean, confidence=CONF_FORMAT),
        )
        return [suggestion] if suggestion else []

    def _scan_party_suffix(
        self, run: _Run, field_ref: FieldRef, value: str
    ) -> List[Suggestion]:
        check = validators.party_suffix(value)
        if not check.matched or not check.span or not check.as_is:
            return []
        ref = FieldRef(
            doc=field_ref.doc,
            field=field_ref.field,
            doc_id=field_ref.doc_id,
            span=check.span,
        )
        run.occurrence(check.as_is, ref)
        decision = self._suffix_decision(check.as_is)
        if decision is None:
            return []
        suggestion = self._build(run, ref, "party_suffix", check.as_is, decision)
        return [suggestion] if suggestion else []

    def _scan_container(
        self, run: _Run, field_ref: FieldRef, value: str
    ) -> List[Suggestion]:
        out: List[Suggestion] = []
        for match in validators.CONTAINER_RE.finditer(value):
            as_is = match.group(0)
            ref = FieldRef(
                doc=field_ref.doc,
                field=field_ref.field,
                doc_id=field_ref.doc_id,
                span=match.span(),
            )
            run.occurrence(as_is, ref)
            check = validators.validate_container(as_is)
            if check.matched and check.ok is False:
                run.notices.append(
                    Notice(
                        kind="deterministic_error",
                        severity="warning",
                        field=ref,
                        message=(
                            f"컨테이너 번호 '{as_is}' 의 체크디지트가 맞지 않습니다"
                            f"(계산값 {check.expected_digit}, 표기 {check.found_digit}). "
                            "어느 자리가 틀렸는지 알 수 없어 교정을 제안하지 않습니다."
                        ),
                    )
                )
                continue
            decision = self._container_decision(as_is)
            if decision is None:
                continue
            suggestion = self._build(run, ref, "container_no", as_is, decision)
            if suggestion:
                out.append(suggestion)
        return out

    def _scan_hs(self, run: _Run, field_ref: FieldRef, value: str) -> List[Suggestion]:
        out: List[Suggestion] = []
        for match in _HS_SCAN_RE.finditer(value):
            group = "labelled" if match.group("labelled") else "bare"
            as_is = match.group(group)
            # span 은 **코드 부분만** 가리킨다. `HS ` 라벨까지 포함하면 승인 시
            # 라벨이 사라져 본문이 바뀐다.
            ref = FieldRef(
                doc=field_ref.doc,
                field=field_ref.field,
                doc_id=field_ref.doc_id,
                span=match.span(group),
            )
            run.occurrence(as_is, ref)
            code = validators.normalize_hs(as_is)
            if code is None:
                continue
            if not code.hsk_present:
                # 관세율표를 적재하지 않았으므로 뒤 4자리를 만들어내지 않는다.
                # 그 자리는 관세율을 가르는 자리라 추측이 곧 금액 오류가 된다.
                run.notices.append(
                    Notice(
                        kind="not_covered",
                        severity="info",
                        field=ref,
                        message=(
                            f"HS '{code.normalized}' 은 국제 6단위까지만 확인했습니다. "
                            "HSK 10단위는 관세율표를 적재하지 않아 뒤 4자리를 만들지 않습니다."
                        ),
                    )
                )
            decision = self._hs_decision(as_is)
            if decision is None:
                continue
            suggestion = self._build(run, ref, "hs_code", as_is, decision)
            if suggestion:
                out.append(suggestion)
        return out

    def _scan_phrases(
        self,
        run: _Run,
        document: DocumentInput,
        field_ref: FieldRef,
        term_class: str,
        value: str,
        neighbors: Dict[str, str],
    ) -> List[Suggestion]:
        """관행 문구·운송서류 용어·인도 용어를 본문에서 찾는다.

        찾는 대상이 **사전에 등재된 표기**뿐이라 ④유사도를 돌리지 않는다.
        자유서식 안에서 "어디부터 어디까지가 하나의 용어인가"를 정하지 않은
        채 유사도를 재면 임의로 자른 조각이 후보를 얻고, 그 조각의 span 이
        본문의 다른 말을 삼킨다.
        """
        out: List[Suggestion] = []
        for pattern, item in self._phrase_index(term_class):
            for match in pattern.finditer(value):
                as_is = match.group(0)
                ref = FieldRef(
                    doc=field_ref.doc,
                    field=field_ref.field,
                    doc_id=field_ref.doc_id,
                    span=match.span(),
                )
                run.occurrence(as_is, ref)
                decision = self._decide(
                    run,
                    document,
                    ref,
                    term_class,
                    as_is,
                    neighbors,
                    lc_guarded=False,
                )
                if decision is None:
                    continue
                suggestion = self._build(run, ref, term_class, as_is, decision, neighbors)
                if suggestion:
                    out.append(suggestion)
        return out

    def _phrase_index(self, term_class: str) -> List[Tuple[re.Pattern, IndexedTerm]]:
        cached = self._phrase_cache.get(term_class)
        if cached is not None:
            return cached
        built: List[Tuple[re.Pattern, IndexedTerm]] = []
        for item in self.stack.pool(term_class):
            surface = item.surface
            if len(loose_key(surface)) < _MIN_SCAN_SURFACE_LEN:
                continue
            words = [re.escape(part) for part in surface.split()]
            if not words:
                continue
            body = r"\s+".join(words)
            # 어두·어말 경계. 한글도 `가-힣` 로 함께 막아 `"서렌더"` 가
            # `"서렌더링"` 안에서 잡히지 않게 한다.
            pattern = re.compile(
                rf"(?<![0-9A-Za-z가-힣]){body}(?![0-9A-Za-z가-힣])", re.IGNORECASE
            )
            built.append((pattern, item))
        # 긴 표기부터 — 짧은 별칭이 긴 문구의 일부를 먼저 채가면 겹침 해소가
        # 매번 뒤늦게 되돌려야 한다. 동률은 surface 사전순으로 고정해 완전
        # 결정론을 만든다(같은 입력 → 같은 순서 → 같은 suggestion_id).
        built.sort(key=lambda pair: (-len(pair[1].surface), pair[1].surface))
        self._phrase_cache[term_class] = built
        return built

    # ── 동음이의 판별 ────────────────────────────────────────────

    def _disambiguate(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        value: str,
        hits: Sequence[Hit],
        neighbors: Dict[str, str],
    ) -> Optional[Hit]:
        """동음이의 후보를 하나로 줄인다. **먼저 맞는 것에서 멈춘다.**

        신호의 강도 순이다: 값 안의 국가 → 인접 필드의 국가 → L/C 44E/44F.
        ⑤(LLM)는 비결정론이라 마지막이고 이 함수 밖에서 처리한다.
        **하나로 못 줄이면 아무것도 고르지 않는다**(임의 선택 금지).
        """
        if term_class != "port" or len(hits) < 2:
            return None

        countries = {h.term.country for h in hits if h.term.country}
        if len(countries) < 2:
            # 국가가 같은 동음이의는 국가 신호로 가를 수 없다. `subdivision`
            # (미국 주 등)이 필요한 자리인데 카탈로그에 그 값이 없다.
            return None

        # ① 값 안의 국가 신호 — 작성자가 직접 쓴 것이라 가장 강하다.
        signals = _country_tokens(value)
        matched = [h for h in hits if h.term.country and h.term.country in signals]
        if len(matched) == 1:
            return matched[0]

        # ② 인접 필드의 국가 — 후보 중 **다른** 국가인 것을 남긴다.
        #    같은 국가로 좁히는 게 아니라 반대다. 선적항과 양하항이 같은
        #    나라인 경우가 오히려 드물어, 방향을 반대로 잡으면 국제 운송
        #    서류 대부분에서 틀린 후보를 고른다.
        neighbor_countries = self._neighbor_countries(ref.field, neighbors)
        if neighbor_countries:
            remaining = [
                h
                for h in hits
                if h.term.country and h.term.country not in neighbor_countries
            ]
            if len(remaining) == 1:
                return remaining[0]

        # ③ L/C 44E/44F 가 지정한 항구의 국가. L/C 는 서류가 아니라 조건이라
        #    서류 문맥보다 뒤에 둔다.
        lc_countries = self._lc_countries(run, ref.field)
        if lc_countries:
            remaining = [
                h for h in hits if h.term.country and h.term.country not in lc_countries
            ]
            if len(remaining) == 1:
                return remaining[0]

        return None

    def _neighbor_countries(
        self, field_name: str, neighbors: Dict[str, str]
    ) -> Set[str]:
        found: Set[str] = set()
        for name in _NEIGHBOR_PORT_FIELDS:
            if name == field_name:
                continue
            value = neighbors.get(name)
            if value:
                found |= self._country_of_port_value(value)
        for name in _NEIGHBOR_ADDRESS_FIELDS:
            value = neighbors.get(name)
            if value:
                # 주소에서는 사전 조회를 하지 않는다 — 상호 안의 단어가 항구
                # 이름과 우연히 같은 경우가 흔하다(`VICTORIA TRADING`).
                found |= _country_tokens(value)
        return found

    def _lc_countries(self, run: _Run, field_name: str) -> Set[str]:
        if run.lc is None:
            return set()
        found: Set[str] = set()
        for name in ("port_of_loading", "port_of_discharge"):
            if name == field_name:
                continue
            value = getattr(run.lc, name, None)
            if value:
                found |= self._country_of_port_value(str(value))
        return found

    def _country_of_port_value(self, value: str) -> Set[str]:
        """항구 표기 하나에서 국가를 뽑는다. 사전 조회 → 값 안의 신호 순."""
        clean = _format_clean(value)
        hits = self.stack.lookup(clean, "port", alias=True)
        if len(hits) == 1 and hits[0].term.country:
            return {hits[0].term.country}
        check = validators.validate_locode(clean)
        if check.ok and check.country:
            return {check.country}
        return _country_tokens(value)

    # ── L/C 문언 우선 ────────────────────────────────────────────

    def _lc_guard(
        self, run: _Run, field_name: str, value: str
    ) -> Optional[Tuple[str, Optional[str]]]:
        """이 필드가 L/C 문언에 고정되어 있는가. `(L/C 값, 태그)` 또는 `None`.

        **충돌할 때만이 아니라 L/C 값이 있기만 하면** 끈다. 기획안보다
        보수적인데 근거가 둘이다.

        1. 충돌 여부를 판정하는 순간 F3 와 같은 자리에 두 번째 판단이 생긴다.
           서류 값이 L/C 와 어긋나는지는 **이미 `checks.py` 의 `match_place`
           가 잡는다**(D003 선적항 불일치 등). F2 가 같은 자리에 다른 기준으로
           판단하면 화면에 서로 모순되는 두 카드가 뜬다 — F3 는 "L/C 와 다르니
           하자"라 하고 F2 는 "표준과 다르니 교정"이라 한다. 사용자는 어느
           쪽을 따를지 모른다.
        2. 교정이 하자를 만들 수 있다. L/C 가 `BUSAN` 이라 적었고 서류도
           `BUSAN` 인데 F2 가 `KRPUS` 로 표준화하면 표기는 표준에 맞아지고
           **L/C 와는 어긋난다.** 은행은 표준이 아니라 L/C 를 본다.
        """
        lc_field = _LC_FIELD_MAP.get(field_name)
        if lc_field and run.lc is not None:
            lc_value = getattr(run.lc, lc_field, None)
            if lc_value:
                return str(lc_value), _LC_TAG.get(field_name)

        # 매핑 밖 필드라도 45A/47A 원문에 서류 값이 문자 그대로 들어 있으면
        # 같은 처리를 한다. 자유서식 조건이 그 값을 지정한 것과 다름없다.
        needle = normalize_key(value)
        if needle:
            for tag, raw in sorted(run.lc_raw_tags.items()):
                if not isinstance(raw, str):
                    continue
                if needle in normalize_key(raw):
                    return value, tag
        return None

    def _lc_message(self, tag: Optional[str], lc_value: str) -> str:
        where = f"L/C {tag}" if tag else "L/C"
        return (
            f"{where} 문언('{_truncate(lc_value, 60)}')이 지정되어 있습니다. "
            "표준 표기로 바꾸면 L/C 와 저촉될 수 있어 교정을 제안하지 않습니다."
        )

    def _terms_from_tags(self, tags: Dict[str, str]) -> Optional["LCTerms"]:
        """MT700 태그 dict → `LCTerms`. `ruleEngine` 은 여기서만 지연 임포트한다.

        `/verify` 와 **완전히 같은 코드**를 탄다 — 게이트웨이가 F2 와 F3 에
        다른 형태로 L/C 를 넘겨야 한다면 두 곳의 해석이 갈라지고, 갈라진
        뒤에는 위 §L/C 문언 우선 1번의 모순이 형태 차이에서 새로 생긴다.
        """
        try:
            from f3_rules.types import LCTerms
        except ImportError:  # pragma: no cover - ruleEngine 없이 terms 만 쓰는 배포
            return None
        return LCTerms.from_tags(tags)

    # ── 제안 조립 ────────────────────────────────────────────────

    def _build(
        self,
        run: _Run,
        ref: FieldRef,
        term_class: str,
        as_is: str,
        decision: _Decision,
        neighbors: Optional[Dict[str, str]] = None,
    ) -> Optional[Suggestion]:
        """`_Decision` → `Suggestion`. 모든 단계에 공통인 정지 조건이 여기 모여 있다."""
        stage = decision.stage
        confidence = decision.confidence
        to_be = decision.to_be

        if decision.requires_choice and len(decision.candidates) >= 2:
            # 후보 전원의 서류 면 표기(bl_form/canonical)가 같으면 어느 쪽을
            # 골라도 결과가 같다 — 사람에게 고르라 할 이유가 없다. 이럴 땐
            # `requires_choice` 를 접어 표기 하나짜리 결정으로 만들고, 아래의
            # 일반 정지 조건(원본과 동일하면 무카드, 항구 토큰 부분집합 …)에
            # 그대로 흘려보낸다 — 별도 특례를 두지 않는다. `_disambiguate`
            # 자체는 손대지 않는다 — 다른 경로가 계속 쓴다. 후보가 1건뿐인
            # requires_choice(예: price_term 의 인접 필드 추정)는 대상이
            # 아니다 — "후보가 하나라 같다"는 이 규칙의 취지가 아니다.
            applied = {c.to_be for c in decision.candidates}
            if len(applied) == 1:
                decision.to_be = applied.pop()
                decision.requires_choice = False
                decision.candidates = []
                decision.llm_pending = False
                to_be = decision.to_be

        if decision.requires_choice and decision.llm_pending:
            # ⑤ 대기 상태다 — `llm_pending=True` 는 ④유사도 이후에만 서는
            # 문(§6단계 캐스케이드 "④ 후보 2건 이상 → ⑤로")이라, ①②exact/
            # alias 동음이의로 왔더라도 확정된 것은 아무것도 없다. 원래 단계
            # (exact/alias)를 그대로 남기면 "확정 안 된 값인데 exact 라고
            # 표시"가 되어 `Evidence.stage` 규약("어느 경로로 나온 값인지가
            # 값을 따라다닌다")을 어긴다. ⑤ 가 실제로 답을 내면
            # `_resolve_llm` 이 `STAGE_LLM` 으로 다시 덮어쓴다.
            stage = STAGE_SIMILARITY

        if not decision.requires_choice:
            if to_be is None:
                return None
            # 무의미한 카드가 목록을 채우면 사람이 카드를 읽지 않게 되고, 그
            # 순간 승인 게이트가 형식이 된다.
            if to_be == as_is:
                return None
            # 항구 클래스 한정: 원본이 이미 `bl_form` 토큰을 담고 있으면
            # (예: "BUSAN, KOREA" ⊇ "BUSAN") 제안하지 않는다 — 이미 맞는
            # 서류 면 표기를 굳이 줄이자는 무의미한 카드를 없앤다. "PUSAN"
            # 처럼 토큰 자체가 다르면 이 조건에 걸리지 않고 정상 제안된다.
            # `STAGE_FORMAT` 은 예외다 — 그 단계의 `to_be` 는 사전 조회가
            # 아니라 원본을 그대로 공백만 정리한 값이라(§⓪format) bl_form
            # 대조 대상이 아니다. 여기서 걸면 "BUSAN   KOREA" 의 공백 정리
            # 카드까지 조용히 사라진다.
            if term_class == "port" and stage != STAGE_FORMAT and _port_face_already_covers(as_is, to_be):
                return None
            # 답이 원본과 대소문자·공백·NFKC 만 다르면 ⓪ 이다(모듈 docstring).
            if stage != STAGE_FORMAT and _is_cosmetic_change(as_is, to_be):
                if policy.allows(term_class, STAGE_FORMAT):
                    stage, confidence = STAGE_FORMAT, CONF_FORMAT

        if confidence < MIN_CONFIDENCE:
            run.unevaluated.append(
                Unevaluated(
                    field=ref,
                    reason=(
                        f"최종 신뢰도 {confidence:.2f} < {MIN_CONFIDENCE} 라 제안하지 않았습니다"
                    ),
                    score=decision.score or confidence,
                    as_is=as_is,
                )
            )
            return None

        term = decision.hit.term if decision.hit else None
        evidence = Evidence(
            authority=(
                (term.authority if term and term.authority else None)
                or decision.authority
                or policy.CLASSES[term_class].default_authority
            ),
            term_id=term.term_id if term else None,
            glossary_version=(term.version if term and term.version else self.glossary_version),
            tier=decision.hit.tier if decision.hit else "standard",
            stage=stage,
            verified=bool(term.verified) if term else False,
            diverges_from_standard=(
                decision.hit.diverges_from_standard if decision.hit else None
            ),
        )

        suggestion = Suggestion(
            suggestion_id="",
            field=ref,
            # `requires_choice` 일 때 `to_be` 는 반드시 `None` 이다. 상위 후보를
            # 넣어 두면 UI 가 그걸 기본값으로 적용해 버리고 "임의 선택 금지"가
            # 그 지점에서 깨진다. 규칙을 문서가 아니라 데이터 형태로 강제한다.
            to_be=None if decision.requires_choice else to_be,
            as_is=as_is,
            term_class=term_class,
            evidence=evidence,
            confidence=round(confidence, 4),
            candidates=list(decision.candidates),
            requires_choice=decision.requires_choice,
            message=self._message(term_class, as_is, to_be, decision, term, evidence),
        )

        if decision.requires_choice and decision.llm_pending and suggestion.candidates:
            # ⑤ 로 넘길 카드다 — 여기서 실제로 `run.pending` 에 쌓지 않으면
            # `_resolve_llm` 은 매번 빈 리스트만 보고, T10 이 `Selector` 를
            # 끼워도 아무 항목도 받지 못한다(§⑤단계 경계). 선정기가 없거나
            # `llm=False` 면 `_resolve_llm` 이 그냥 건드리지 않고 지나간다 —
            # 이 카드는 `requires_choice=True` 로 남는다.
            item = SelectionItem(
                item_id=f"item{len(run.pending) + 1}",
                term_class=term_class,
                doc=ref.doc,
                field=ref.field,
                value=_truncate(as_is),
                neighbors=self._llm_neighbors(neighbors or {}, ref.field),
                candidates=list(suggestion.candidates),
            )
            run.pending.append(_Pending(item=item, suggestion=suggestion, score=decision.score))

        return suggestion

    def _llm_neighbors(self, neighbors: Dict[str, str], field_name: str) -> Dict[str, str]:
        """⑤ 에 넘길 인접 필드 — 크기 상한(§4.4 "크기 상한")을 여기서 지킨다."""
        out: Dict[str, str] = {}
        for name, value in neighbors.items():
            if name == field_name:
                continue
            out[name] = _truncate(value)
            if len(out) >= _LLM_MAX_NEIGHBORS:
                break
        return out

    def _message(
        self,
        term_class: str,
        as_is: str,
        to_be: Optional[str],
        decision: _Decision,
        term: Optional[GlossaryTerm],
        evidence: Evidence,
    ) -> str:
        label = policy.CLASSES[term_class].label
        if decision.requires_choice:
            body = (
                f"{label} '{as_is}' 은 후보가 {len(decision.candidates)}건이라 "
                "자동으로 고르지 않습니다. 후보 중 하나를 선택하세요."
            )
        else:
            # 항구는 `display` 에 UN/LOCODE 코드가 박혀 있다(예: "KRPUS
            # (Busan)"). 메시지 문자열 안에도 코드가 절대 보이면 안 되므로
            # (§ as_is/to_be 뿐 아니라 카드 전체에 코드 노출 금지) 항구
            # 클래스는 이 괄호 병기를 아예 붙이지 않는다.
            display = (
                term.display if term and term.display and term.category != "port" else None
            )
            shown = f" ({display})" if display and display != to_be else ""
            body = (
                f"{label} '{as_is}' 을(를) {evidence.authority} 표준 표기 "
                f"'{to_be}'{shown} 로 정렬합니다."
            )
        if decision.message_extra:
            body = f"{body} {decision.message_extra}"
        # 미검증 표시는 **문자열 안에** 넣는다. 응답 필드로만 두면 화면이 그
        # 필드를 렌더링하지 않았을 때 표기가 사라진다. 사전 항목을 인용하지
        # 않은 제안(검증기 단독)에는 붙이지 않는다 — 인용한 출처가 없으니
        # "출처 미검증"이라는 말 자체가 성립하지 않는다.
        if term is not None and not evidence.verified:
            body += " (출처 미검증)"
        return body

    def _register(self, run: _Run, suggestion: Suggestion) -> None:
        """제안을 확정 목록에 싣는다.

        `stats.by_stage` 는 여기서 누적하지 않는다 — `_resolve_llm` 이 ⑤
        확정 시 같은 제안의 `evidence.stage` 를 바꾸고(`requires_choice` 도
        `False` 로), to_be 가 원본과 같아지면 `run.suggestions` 에서 제안
        **자체를 지운다.** 등록 시점에 세면 그 뒤의 변경·삭제와 어긋나
        `by_stage` 합계가 `len(suggestions)` 와 맞지 않는다(실측: 제안 5건에
        by_stage 합 4건 — `requires_choice` 제안이 세지 않는 채로 빠져
        있었다). `normalize()` 가 `_resolve_llm` 이 끝난 뒤 `run.suggestions`
        를 한 번에 훑어 계산한다 — 그래야 최종 상태와 항상 일치한다.
        """
        run.suggestions.append(suggestion)

    # ── ⑤ 배치 · 영향 범위 ──────────────────────────────────────

    def _resolve_llm(self, run: _Run, llm: bool) -> None:
        """⑤ 를 태울 항목을 한 번에 묶어 선정기에 넘긴다.

        선정기가 없거나 `llm=False` 면 아무것도 하지 않는다 — 후보들은 이미
        `requires_choice=True` 로 만들어져 있고 `stats.llm_path` 는
        `"not_called"` 다. **평소 상태이며 실패가 아니다**: 결정론 제안은 그대로
        나가고 ④ 후보는 사용자가 직접 고른다.
        """
        setattr(run, "_llm_path", "not_called")
        setattr(run, "_llm_calls", 0)
        setattr(run, "_llm_model", None)

        pending = [p for p in run.pending if p.item.candidates]
        if not pending or not llm or self.selector is None:
            return

        limit = policy.llm_max_items()
        selected = pending[:limit]
        for extra in pending[limit:]:
            # 조용히 자르면 "LLM 이 판단했다"와 "예산 때문에 못 물었다"가
            # 구분되지 않는다. 앞은 판정이고 뒤는 미판정이다.
            run.notices.append(
                Notice(
                    kind="not_covered",
                    severity="info",
                    field=extra.suggestion.field,
                    message=(
                        f"한 번에 물을 수 있는 항목 수({limit})를 넘어 이 항목은 "
                        "LLM 판별을 건너뛰었습니다. 후보 중 직접 선택하세요."
                    ),
                )
            )

        try:
            outcome = self.selector.select([p.item for p in selected])
        except Exception:  # pragma: no cover - 선정기 구현의 어떤 실패도 200 을 지킨다
            setattr(run, "_llm_path", "failed")
            return

        setattr(run, "_llm_path", outcome.llm_path or "called")
        setattr(run, "_llm_calls", outcome.llm_calls)
        setattr(run, "_llm_model", outcome.llm_model)
        run.notices.extend(outcome.notices)

        by_id = {p.item.item_id: p for p in selected}
        for item_id, choice in (outcome.choices or {}).items():
            target = by_id.get(item_id)
            if target is None:
                continue  # 모르는 item_id 는 폐기한다.
            candidates = target.suggestion.candidates
            if not isinstance(choice, int) or not 1 <= choice <= len(candidates):
                continue  # 범위 밖 응답도 폐기한다(해석해 주면 규약이 없는 것과 같다).
            picked = candidates[choice - 1]
            suggestion = target.suggestion
            suggestion.to_be = picked.to_be
            suggestion.requires_choice = False
            suggestion.evidence.stage = STAGE_LLM
            suggestion.evidence.term_id = picked.term_id
            suggestion.evidence.authority = picked.authority or suggestion.evidence.authority
            suggestion.confidence = round(
                min(LLM_CONFIDENCE_CAP, 0.55 + 0.30 * target.score), 4
            )
            reason = (outcome.reasons or {}).get(item_id, "")
            suffix = f" 근거: {reason}" if reason else ""
            suggestion.message = (
                f"{policy.CLASSES[suggestion.term_class].label} '{suggestion.as_is}' 은 "
                f"후보 중 '{picked.to_be}' 로 판별했습니다.{suffix}"
            )
            if suggestion.to_be == suggestion.as_is:
                # 확정했더니 원본과 같다 — 카드를 남길 이유가 없다.
                run.suggestions.remove(suggestion)
                continue
            # `by_stage` 집계는 여기서 하지 않는다 — `_register` docstring 참고.

    def _attach_impact(self, run: _Run) -> None:
        """같은 값이 요청에 실린 **다른** 자리에도 있으면 그 목록을 싣는다.

        요청 밖은 볼 수 없다. 무상태라 선적의 일부만 실어 보내면 `impact` 는
        **조용히 짧아지고**, 화면은 그것을 "이 값은 여기에만 쓰였다"로 읽는다.
        선적 전 서류를 한 요청에 싣는 것이 게이트웨이의 계약이다
        (§무상태의 한계).
        """
        for suggestion in run.suggestions:
            suggestion.impact = self._occurrences_of(run, suggestion)
            suggestion.suggestion_id = _suggestion_id(suggestion)

    def _is_canonical_value(self, value: str) -> bool:
        """값 전체가 어떤 클래스의 canonical 표기와 같은가.

        `_process_field` 가 자유서식 조각 스캔을 건너뛸지 정할 때 쓴다.
        대소문자·공백 차이는 무시한다(`normalize_key`) — `"original b/l"` 도
        이미 그 용어를 쓴 것이지 고칠 대상이 아니다. 다만 표기 정리는
        필요할 수 있으므로 **값 전체 경로(`FIELD_CLASS`)는 막지 않는다.**
        여기서 끄는 것은 조각 스캔뿐이다.
        """
        key = normalize_key(value)
        if not key:
            return False
        for term_class in policy.CLASSES:
            for hit in self.stack.lookup(key, term_class, alias=False):
                if normalize_key(hit.term.canonical) == key:
                    return True
        return False

    def _occurrences_of(self, run: _Run, suggestion: Suggestion) -> List[FieldRef]:
        """`suggestion.as_is` 가 실제로 쓰인 **다른** 자리를 찾는다.

        `run.occurrences` 만 보면 안 된다. 그건 **필드 값 전체**로 등록되는데
        (`_process_field` 의 `run.occurrence(value, ...)`), span 제안의 `as_is`
        는 자유서식 **안의 조각**이다(span 계약 — §4.5). `'CO.,LTD'` 로 조회하면
        `'GAE WOON CO.,LTD'` 로 등록된 자리를 못 찾아 영향 범위가 **조용히
        비고**, 화면은 그걸 "이 값은 여기에만 쓰였다"로 읽는다. 일괄 적용
        ("전체 적용")이 근거를 잃는 것도 같은 이유다.

        그래서 조각일 때는 요청에 실린 모든 필드 값을 뒤져 그 조각이 든 자리를
        모은다. 필드 수가 서류당 10~15 라 비용은 무시할 만하다.

        찾은 자리에는 **그 필드에서의 오프셋**을 span 으로 달아 준다. 같은
        조각이라도 필드마다 위치가 다르므로 원 제안의 span 을 재사용할 수 없고,
        span 을 비워 두면 `apply` 가 "필드 전체를 `as_is` 로 갈아 끼우라"로
        읽어 `'CO.,LTD'` 가 `'GAE WOON CO.,LTD'` 와 다르다며 전부 stale 로
        떨어진다. 정규화 이후 값이 바뀌었다면 `apply` 의
        `value[start:end] == as_is` 검사가 잡아 `unapplied` 로 돌린다 —
        여기서 굳어진 오프셋이 위험해지는 경우를 그쪽이 막는다.
        """
        key = normalize_key(suggestion.as_is)
        if not key:
            return []

        if suggestion.field.span is None:
            refs = run.occurrences.get(key, [])
            return [r for r in refs if r != suggestion.field]

        found: List[FieldRef] = []
        for document in run.documents:
            for name, value in document.fields.items():
                if not isinstance(value, str):
                    continue
                # 자기 자신이 있던 필드는 제외한다. span 이 달라 `!=` 로는
                # 걸러지지 않으므로 (doc, doc_id, field) 로 비교한다.
                if (
                    document.doc == suggestion.field.doc
                    and document.doc_id == suggestion.field.doc_id
                    and name == suggestion.field.field
                ):
                    continue
                start = value.find(suggestion.as_is)
                if start < 0:
                    continue
                found.append(
                    FieldRef(
                        doc=document.doc,
                        field=name,
                        doc_id=document.doc_id,
                        span=(start, start + len(suggestion.as_is)),
                    )
                )
        return found

    # ── 잡동사니 ────────────────────────────────────────────────

    def _canonicalize(self, candidate: Candidate) -> Optional[Candidate]:
        """랭커가 만든 후보의 `to_be` 를 서류 면 표기로 되돌린다.

        `similarity._to_candidate` 는 `display or canonical` 을 넣는데,
        **적용되는 값은 언제나 `_applied_form()`(항구는 `bl_form`, 그 밖은
        canonical) 이어야 한다**(`display` 는 메시지 전용). 섞이면 사람이
        승인한 값이 `"KRPUS (Busan)"` 처럼 사람이 읽으라고 만든 문자열이 되어
        서류에 박힌다. `similarity.py` 를 고치지 않고 여기서 되돌리는 이유는
        이번 작업의 수정 범위가 이 파일 하나이기 때문이다 — 최종 보고에 남긴다.

        항구인데 `bl_form` 이 없으면 `None` 을 돌려준다 — 이 후보는 목록에서
        빠진다. 조용히 canonical(코드)로 되돌리지 않는다: 호출부가 필터링하고,
        비었으면 `Unevaluated` 로 남긴다.
        """
        term = self._term_by_id(candidate.term_id)
        if term is None:
            return candidate
        to_be = self._applied_form(term)
        if to_be is None:
            return None
        if to_be == candidate.to_be:
            return candidate
        return Candidate(
            to_be=to_be,
            term_id=candidate.term_id,
            authority=candidate.authority or term.authority,
            score=candidate.score,
            reason=candidate.reason,
        )

    def _applied_form(self, term: GlossaryTerm) -> Optional[str]:
        """서류에 실제로 박히는 표기. 항구는 코드가 아니라 항구명이다.

        UCP 600 제20조는 서류가 L/C 문언과 일치해야 한다고 요구하는데, 선박
        회사가 발행하는 B/L 면에는 UN/LOCODE 코드가 아니라 항구 **이름**이
        인쇄된다(코드는 EDIFACT·세관 매니페스트·DCSA eBL 데이터 레이어에만
        쓰인다). 그래서 `category == "port"` 는 `canonical`(코드) 대신
        `bl_form`(이름)을 돌려준다 — 그 밖의 클래스는 지금까지처럼 canonical
        그대로다.

        `bl_form` 이 비어 있으면 `None` 을 돌려준다. 호출부는 이걸 절대 조용히
        canonical 로 되돌리면 안 된다 — 사전 누락이 조용히 KRPUS 제안으로
        되돌아가는 게 이번에 없애려는 실패 방향이다. `Unevaluated` 로 남긴다.

        `_candidate_of`(모듈 함수, self 없이 호출됨)도 같은 판단이 필요해서
        실제 로직은 모듈 레벨 `_applied_form_of()` 에 두고 여기서는 그걸 부른다
        — 판단 기준이 두 곳에 따로 살면 하나만 고치고 잊는 사고가 난다.
        """
        return _applied_form_of(term)

    def _unevaluated_missing_bl_form(
        self, run: _Run, ref: FieldRef, score: Optional[float], as_is: str
    ) -> None:
        """항구 `bl_form` 미등록을 `Unevaluated` 로 남긴다(침묵 금지)."""
        run.unevaluated.append(
            Unevaluated(
                field=ref,
                reason="이 항구의 선하증권 표기가 사전에 없습니다",
                score=score,
                as_is=as_is,
            )
        )

    def _term_by_id(self, term_id: Optional[str]) -> Optional[GlossaryTerm]:
        if not term_id:
            return None
        for layer in reversed(self.stack.layers):
            term = layer.by_term_id(term_id)
            if term is not None:
                return term
        return None

    def _hit_by_term_id(self, term_id: Optional[str]) -> Optional[Hit]:
        if not term_id:
            return None
        for layer in reversed(self.stack.layers):
            term = layer.by_term_id(term_id)
            if term is not None:
                return Hit(term=term, tier=layer.tier, diverges_from_standard=None)
        return None


def run_llm_path(run: _Run) -> str:
    """`stats.llm_path`. `_Run` 에 필드로 두지 않고 함수로 읽는 이유는
    `_resolve_llm` 이 호출되기 전에도 안전한 기본값(`not_called`)을 주기
    위해서다."""
    return getattr(run, "_llm_path", "not_called")


# ════════════════════════════════════════════════════════════════
# 겹침 해소 · suggestion_id
# ════════════════════════════════════════════════════════════════


def _resolve_overlaps(suggestions: List[Suggestion]) -> List[Suggestion]:
    """같은 필드 안에서 span 이 겹치는 제안을 정리한다.

    겹친 채로 두면 **두 제안을 동시에 승인할 때 치환이 서로를 덮어쓴다** —
    앞의 치환이 문자열 길이를 바꾸면 뒤의 span 은 이미 다른 곳을 가리킨다.
    더 구체적인(긴) span 을 남긴다: `"MSKU 123456 5"`(컨테이너)와 그 안의
    `"123456"`(HS 오인) 중 남겨야 하는 것은 앞이다.

    동률 정렬 키를 끝까지 채우는 이유는 결정론이다 — 같은 입력에 같은 결과가
    나와야 `suggestion_id` 가 재현된다.
    """
    ordered = sorted(
        suggestions,
        key=lambda s: (
            -((s.field.span or (0, 0))[1] - (s.field.span or (0, 0))[0]),
            (s.field.span or (0, 0))[0],
            s.term_class,
            s.to_be or "",
        ),
    )
    kept: List[Suggestion] = []
    for suggestion in ordered:
        span = suggestion.field.span
        if span is None:
            kept.append(suggestion)
            continue
        if any(
            k.field.span is not None and _spans_overlap(span, k.field.span) for k in kept
        ):
            continue
        kept.append(suggestion)
    # 화면·적용 순서는 본문 순서가 자연스럽다.
    kept.sort(key=lambda s: ((s.field.span or (0, 0))[0], s.term_class))
    return kept


def _applied_form_of(term: GlossaryTerm) -> Optional[str]:
    """`Normalizer._applied_form()` 과 `_candidate_of()`(모듈 함수)가 같이 쓰는
    판단 로직. `Normalizer._applied_form()` 의 docstring 참고."""
    if term.category != "port":
        return term.canonical
    return term.bl_form or None


def _candidate_of(term: GlossaryTerm, score: float) -> Optional[Candidate]:
    """사전 항목 → 후보. `to_be` 는 서류 면 표기다(항구는 bl_form, 그 밖은 canonical).

    항구인데 `bl_form` 이 없으면 `None` — 호출부가 목록에서 걸러내고, 비면
    `Unevaluated` 로 남긴다(조용히 canonical(코드)로 되돌리지 않는다).
    """
    to_be = _applied_form_of(term)
    if to_be is None:
        return None
    return Candidate(
        to_be=to_be,
        term_id=term.term_id,
        authority=term.authority or "",
        score=round(score, 4),
        # 화면이 동음이의 후보(PORTLAND US vs AU)를 구분할 짧은 문자열.
        # display 는 코드를 담고 있어(예: "KRPUS (Busan)") 후보 목록에 코드가
        # 노출된다 — country 로 대체한다.
        reason=term.country or "",
    )


def _suggestion_id(suggestion: Suggestion) -> str:
    """`suggestion_id` 는 T11(`apply.py`)의 규약이다 — 있으면 쓰고 없으면 빈 값.

    파생식(재료·해시 함수·접두)을 여기 복사하면 `apply` 가 재파생해 대조할 때
    **두 곳의 식이 갈라질 수 있고**, 갈라지면 `/normalize/apply` 가 정상
    제안을 400 으로 거절한다. 그래서 식은 한 곳(T11)에만 두고 이 파일은 지연
    임포트로 빌려 쓴다. T11 이 아직 없으면 빈 문자열이며, 그때는 T11 이
    채운다 — 어느 쪽이든 파생식은 한 벌이다.
    """
    try:
        from .apply import suggestion_id as derive  # type: ignore[attr-defined]
    except Exception:
        return ""
    try:
        return derive(suggestion)
    except Exception:  # pragma: no cover - apply 가 깨져도 /normalize 는 살아야 한다
        return ""


__all__ = [
    "CASCADE_VERSION",
    "DocumentInput",
    "Normalizer",
    "SelectionItem",
    "SelectionOutcome",
    "Selector",
]

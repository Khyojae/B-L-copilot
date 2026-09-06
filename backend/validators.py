"""
F2 결정론 검증기 — ISO 6346·Rec 20·Incoterms 2020·HS/HSK·UN/LOCODE·상호 접미.

## 이 파일이 하는 일과 하지 않는 일

`f2-standard-terms.md` §"결정론 검증기"의 계약을 코드로 옮긴다. 여기 있는
모든 함수는 **사실만 돌려준다** — 무엇이 맞는지·틀렸는지·형식이 맞는지를
판정할 뿐, 값을 "고쳐서" 돌려주지 않는다. 교정 제안 카드(`Suggestion`)를
조립하는 것은 캐스케이드(`cascade.py`, T9)의 일이고, 이 파일은 그 재료가
되는 결정론적 사실만 만든다.

`f2-standard-terms.md` §"무엇에 100% 를 주장할 수 있고 무엇에 못 하는가"
표를 그대로 따른다.

| 항목 | 100% | 조건과 한계 |
|---|:-:|---|
| 단위 토큰의 Rec 20 소속 여부 | O | 집합 조회. 집합이 닫혀 있다 |
| HS 코드 형식(자릿수·구분자) | O | **형식만.** 품목 실재는 판정 대상이 아니다 |
| LOCODE 코드 형식 | O | **형식만.** 실재 여부는 사전 커버리지에 달렸다 |
| 컨테이너 체크디지트 | 조건부 O | 아래 `container_check_digit` docstring 의 접힘 사각지대만큼 못 미친다 |
| Incoterms 장소 적정성 | X | 장소 **누락** 검출은 O, 장소가 **옳은지**는 X |
| 상호 표기 | X | 접미 정규화만 결정론. 본체는 판정 대상이 아니다 |

## 의존성 제약

표준 라이브러리(`re`·`unicodedata`·`dataclasses`·`typing`)만 쓴다.
`ruleEngine`·`ocr`·`yaml` 을 모듈 최상단에서 임포트하지 않는다 —
`f2_terms/keys.py` 모듈 docstring 과 같은 이유로, F6 이 `terms` 를 가볍게
끌어 쓸 수 있어야 한다. 유일한 예외는
`incoterms_consistent_with_checks()` 인데, 이 함수는 T13 테스트가 두
INCOTERMS 튜플의 정합성을 잡기 위해서만 존재하고 함수 안에서 지연
임포트한다 — 평소 경로(캐스케이드가 이 파일을 쓰는 경로)에는 영향이
없다.

## `_LEGAL_SUFFIXES` 를 복사하는 이유

`f3_rules/checks.py:_LEGAL_SUFFIXES` 를 **임포트하지 않고 복사**한다.
`ruleEngine` 을 임포트하면 그 파일이 끌고 오는 `.types`(`LCTerms`) 등이
`terms` 에도 딸려 오는데, `terms` 는 F6 이 `ruleEngine` 을 몰라도 가볍게
끌어 쓸 자리다(`keys.py`·`policy.py` 와 같은 논거). 20단어 남짓의 상수
중복이 패키지 간 결합보다 싸다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

# ════════════════════════════════════════════════════════════════
# ISO 6346 — 컨테이너 번호
# ════════════════════════════════════════════════════════════════

#: 형식 `AAA U|J|Z NNNNNN N` — 소유자 3자 + 장비 구분자 1자 + 일련 6자리 +
#: 체크디지트 1자리. 장비 구분자가 U(화물)·J(분리형 장비)·Z(트레일러/섀시)
#: 가 아니면 이 정규식 자체가 매칭에 실패한다 — 다른 번호 체계를 컨테이너
#: 번호로 오인해 "체크디지트가 틀렸다"고 말하는 것이 침묵보다 나쁘기
#: 때문이다(클래스 오판은 판정하지 않는다).
CONTAINER_RE = re.compile(r"\b([A-Z]{3})\s*([UJZ])\s*(\d{6})\s*(\d)\b", re.IGNORECASE)


def _build_container_letter_values() -> Dict[str, int]:
    """A=10 에서 시작해 11의 배수(11·22·33)를 건너뛰며 Z=38 까지 채운다."""
    values: Dict[str, int] = {}
    v = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        values[ch] = v
        v += 1
    return values


#: 문자 → 체크디지트 계산용 값. 숫자는 자기 자신의 값을 쓴다(여기 없음).
_CONTAINER_LETTER_VALUES: Dict[str, int] = _build_container_letter_values()


def _container_char_value(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    return _CONTAINER_LETTER_VALUES[ch.upper()]


def container_check_digit(code10: str) -> int:
    """앞 10자(소유자 3 + 장비 구분자 1 + 일련 6)에서 체크디지트를 계산한다.

    `total = Σ value(chᵢ) · 2^i` (i=0..9, 왼쪽부터 0), `check = (total % 11) % 10`.

    ## 사각지대 — 10 과 0 의 접힘

    `total % 11` 은 0..10 의 열한 가지 값을 갖지만 체크디지트는 0..9 의 열
    가지뿐이다. 마지막 `% 10` 때문에 **나머지 10 과 나머지 0 이 둘 다
    체크디지트 0 으로 접힌다.** 이것은 이 구현의 버그가 아니라 ISO 6346
    자체가 안고 있는 성질이다.

    결과로, 체크디지트 1~9 는 각각 `total % 11` 의 값 하나에만 대응하지만
    체크디지트 0 은 **두 값(0 과 10)에 대응한다.** 잔여를 0 과 10 사이로
    옮기는 단일 문자 오류는 검사를 통과할 수 있다. **그러므로 "단일 문자
    오류 검출률 100%" 는 이 함수에 대해서도 사실이 아니다** — 체크디지트가
    0 인 번호는 다른 아홉 경우보다 검출력이 구조적으로 낮다. 미검출
    비율의 구체적인 수치는 실측이 없어 여기 적지 않는다
    (`f2-standard-terms.md` §"ISO 6346 의 사각지대").
    """
    code10 = code10.upper()
    total = sum(_container_char_value(ch) * (2**i) for i, ch in enumerate(code10))
    return (total % 11) % 10


@dataclass(frozen=True)
class ContainerCheck:
    """`validate_container` 의 결과 — 사실만 담는다.

    체크디지트가 안 맞아도 이 타입은 "고친 값"을 만들지 않는다. 어느
    자리(소유자·장비 구분자·일련번호·체크디지트 자신)가 틀렸는지 이
    검사만으로는 알 수 없으므로, 고쳐서 돌려주는 것은 추측이다. 호출부는
    `ok is False` 를 근거로 `Notice(kind="deterministic_error")` 를 만들
    뿐, 이 타입에서 교정값을 읽지 않는다.
    """

    matched: bool  # 컨테이너 번호 형식(장비 구분자 U|J|Z 포함)에 맞았는가
    normalized: Optional[str]  # 공백 제거·대문자 11자. matched=False 면 None
    ok: Optional[bool]  # 체크디지트 일치 여부. matched=False 면 None
    expected_digit: Optional[int]
    found_digit: Optional[int]


def validate_container(text: str) -> ContainerCheck:
    """텍스트에서 컨테이너 번호를 찾아 체크디지트를 검증한다.

    장비 구분자가 `U|J|Z` 가 아니면 `CONTAINER_RE` 자체가 매칭하지 않으므로
    `matched=False` 로 돌아간다 — "판정하지 않는다"가 정규식 수준에서
    구조적으로 강제된다.
    """
    m = CONTAINER_RE.search(text or "")
    if not m:
        return ContainerCheck(False, None, None, None, None)
    owner, category, serial, digit = m.groups()
    code10 = f"{owner}{category}{serial}".upper()
    found_digit = int(digit)
    expected_digit = container_check_digit(code10)
    normalized = f"{code10}{found_digit}"
    return ContainerCheck(
        matched=True,
        normalized=normalized,
        ok=(expected_digit == found_digit),
        expected_digit=expected_digit,
        found_digit=found_digit,
    )


# ════════════════════════════════════════════════════════════════
# UN/ECE Recommendation 20 — 수량·용적 단위
# ════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UnitCode:
    """Rec 20 단위 코드 1건. `verified=True` 는 핵심 6개(질량·용적·길이류)만."""

    code: str
    name: str
    verified: bool


def _unit(code: str, name: str, verified: bool) -> UnitCode:
    return UnitCode(code=code, name=name, verified=verified)


# 핵심 6개 — 실무에서 가장 자주 쓰이는 단위이고, `verified` 후보로 표시한다.
_KGM = _unit("KGM", "kilogram", True)
_TNE = _unit("TNE", "tonne", True)
_LBR = _unit("LBR", "pound", True)
_MTQ = _unit("MTQ", "cubic metre", True)
_LTR = _unit("LTR", "litre", True)
_MTR = _unit("MTR", "metre", True)

# 포장 단위 — Stage A 에 넣되 전부 미검증. 관세율·중량 단위처럼 표준 코드
# 하나로 수렴하는 성질이 약해(포장 관행이 업체마다 다르다) 검증을 주장하지
# 않는다.
_CT = _unit("CT", "carton", False)
_PK = _unit("PK", "package", False)
_BX = _unit("BX", "box", False)
_PCE = _unit("PCE", "piece", False)

# 팔레트(`PLT`/`PALLET` → `PF`)를 **일부러 뺐다.**
#
# 출처 검증(T20b)에서 현행 UN/ECE Rec 21 알파벳 코드의 `PF` 가 "Pen"(가축우리)
# 이고 팔레트는 `PX` 라는 소견이 나왔다. 사실이라면 이 매핑은 포장명세서의
# "100 PALLETS" 를 가축우리로 바꾸면서 **"UN/ECE Rec 20 근거"라는 틀린 인용까지
# 붙여** 내보낸다 — 값과 근거가 동시에 틀리는, 이 프로젝트가 최악으로 치는 모양이다.
#
# 어느 쪽이 맞는지 확정하지 못했으므로 **제안하지 않는 쪽**을 골랐다. 팔레트를
# 정규화하지 못해 잃는 것은 편의뿐이고, 틀리게 정규화해 잃는 것은 서류의 의미다
# (§정밀도를 재현율보다 우선한다). 표준을 확인한 뒤 `PX` 로 되살릴 것.
#
# 이 매핑은 T7 사양이 처음부터 잘못 지시한 것이라 구현자 잘못이 아니다.

# 별칭 → UnitCode. 키는 `_unit_lookup_key` 로 정규화된 형태(대문자, 점·
# 공백 제거, NFKC)여야 한다. **부분 일치가 아니라 이 dict 의 정확한 키
# 일치로만 조회한다** — `M`(MTR)과 `M3`(MTQ)의 접두 충돌을 막는 유일한
# 방법이다. 점을 지우고 조회하므로 "K.G.S"→"KGS", "M.T."→"MT",
# "C.B.M."→"CBM" 처럼 점이 있는 변형은 점 없는 별칭과 자동으로 합쳐진다
# (별도 항목을 두지 않아도 된다).
_UNIT_ALIASES: Dict[str, UnitCode] = {}


def _register(unit: UnitCode, *aliases: str) -> None:
    for alias in (unit.code, *aliases):
        _UNIT_ALIASES[alias] = unit


_register(_KGM, "KG", "KGS", "KILO", "KILOS", "KILOGRAM", "KILOGRAMS", "킬로그램", "킬로")
_register(_TNE, "MT", "TON", "TONS", "TONNE", "TONNES", "톤", "메트릭톤")
_register(_LBR, "LB", "LBS", "POUND", "POUNDS")
_register(_MTQ, "CBM", "M3", "CUM", "세제곱미터", "입방미터")
_register(_LTR, "L", "LITER", "LITERS", "LITRE", "LITRES")
_register(_MTR, "M", "METER", "METERS", "METRE", "METRES")
_register(_CT, "CTN", "CTNS", "CARTON", "CARTONS")
_register(_PK, "PKG", "PKGS", "PACKAGE", "PACKAGES")
_register(_BX, "BOX", "BOXES")
_register(_PCE, "PCS", "PC", "PIECE", "PIECES")

_UNIT_LOOKUP_STRIP = re.compile(r"[.\s]+")


def _unit_lookup_key(token: str) -> str:
    """단위 토큰 조회용 정규화 — NFKC(윗첨자 ³→3) 뒤 대문자화, 점·공백 제거."""
    s = unicodedata.normalize("NFKC", token or "").upper()
    return _UNIT_LOOKUP_STRIP.sub("", s)


def unit_code(token: str) -> Optional[UnitCode]:
    """단위 토큰을 Rec 20 코드로 조회한다. 없으면 `None`(모르는 단위, 추측 금지).

    토큰 **전체** 일치로만 판정한다. 부분 일치를 쓰면 `M3`(MTQ)가 `M`(MTR)
    으로 먼저 잡히므로, 이 함수는 정규화된 키로 dict 를 한 번만 조회한다.
    """
    return _UNIT_ALIASES.get(_unit_lookup_key(token))


_QUANTITY_RE = re.compile(r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>[A-Za-z0-9가-힣./³]+)")


def split_quantity(text: str) -> Optional[Tuple[str, str, Tuple[int, int]]]:
    """"1,234.50 KGS" 를 (수치 텍스트, 단위 토큰, 단위 span) 으로 가른다.

    **수치는 그대로 돌려준다** — 콤마·자릿수 등 어떤 형태 변환도 하지
    않는다. `span` 은 원문 안에서 단위 토큰이 시작·끝나는 문자 오프셋
    (반열림 구간)이며, `apply` 가 단위 토큰만 갈아 끼우고 수치를 건드리지
    않도록 하는 유일한 방법이다. 매칭 실패 시 `None`.
    """
    m = _QUANTITY_RE.search(text or "")
    if not m:
        return None
    return m.group("number"), m.group("unit"), (m.start("unit"), m.end("unit"))


# ════════════════════════════════════════════════════════════════
# Incoterms 2020
# ════════════════════════════════════════════════════════════════

INCOTERMS_2020: Tuple[str, ...] = (
    "EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
    "CPT", "CIP", "DAP", "DPU", "DDP",
)

# 조건마다 장소가 가리키는 것이 다르다 — 적출지(loading) vs 도착지
# (discharge). 방향을 반대로 잡으면 가격 조건의 실질이 바뀐다.
_PLACE_SIDE: Dict[str, str] = {
    "EXW": "loading", "FCA": "loading", "FAS": "loading", "FOB": "loading",
    "CFR": "discharge", "CIF": "discharge", "CPT": "discharge", "CIP": "discharge",
    "DAP": "discharge", "DPU": "discharge", "DDP": "discharge",
}

# `_PLACE_SIDE` 가 가리키는 값을 인접 필드 이름으로 바꾼다. 장소가
# 누락됐을 때 호출부가 지어내지 않고 이 필드에서 후보를 찾게 한다.
_PLACE_SIDE_FIELD: Dict[str, str] = {
    "loading": "port_of_loading",
    "discharge": "port_of_discharge",
}

# "FOB" · "F.O.B" · "F O B" 세 변형을 흡수한다. 3글자를 점·공백으로 자유롭게
# 나눌 수 있게 하되 정확히 3글자만 잡는다 — 4번째 이후 글자는 장소 쪽으로
# 넘긴다.
_INCOTERM_TOKEN_RE = re.compile(r"^\s*([A-Za-z])[.\s]?([A-Za-z])[.\s]?([A-Za-z])\b(.*)$")

# `format_price_term` 이 붙이는 병기 꼬리. 표준형을 다시 넣었을 때 이것을
# 장소의 일부로 읽으면 병기가 겹쳐 붙는다(§parse_price_term docstring).
# 연도를 고정하지 않는 이유: Incoterms 는 개정판이 있고(2010·2020), 옛 판
# 병기가 붙은 값이 들어와도 장소로 오인하면 안 된다.
_INCOTERMS_SUFFIX_RE = re.compile(r"\s*\(\s*incoterms\s*\d{4}\s*\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PriceTerm:
    """`parse_price_term` 의 결과 — 조건 코드와 장소(있으면)만 담는다.

    장소가 없을 때 이 타입은 장소를 지어내지 않는다. `place` 는 `None` 이고
    `place_side_field` 에 인접 필드 이름(`port_of_loading`/
    `port_of_discharge`)을 담아 호출부가 거기서 후보를 만들게 한다.
    """

    code: str
    place: Optional[str]
    place_side_field: Optional[str]  # 이 조건에서 장소가 가리키는 인접 필드 이름


def parse_price_term(text: str) -> Optional[PriceTerm]:
    """가격조건 텍스트에서 조건 코드와 장소를 분리한다.

    `INCOTERMS_2020` 에 없는 3글자는 가격조건이 아니라고 보고 `None` 을
    돌려준다(클래스 오판 방지 — 컨테이너 번호와 같은 논거).

    **이미 표준형인 입력을 다시 넣어도 같은 결과가 나와야 한다(멱등).**
    `format_price_term` 이 붙이는 `(Incoterms 2020)` 병기를 장소의 일부로
    읽으면 `"FOB Busan (Incoterms 2020)"` 이
    `"FOB Busan (Incoterms 2020) (Incoterms 2020)"` 이 된다. 게이트웨이가
    재검증하거나 사용자가 다시 정규화하는 것은 **정상 경로**이고, 거기서
    이미 교정된 값이 망가지면 F2 는 자기가 만든 값을 자기가 부순다.
    그래서 장소에서 병기 꼬리를 먼저 떼어 낸다.
    """
    m = _INCOTERM_TOKEN_RE.match(text or "")
    if not m:
        return None
    code = "".join(m.group(1, 2, 3)).upper()
    if code not in INCOTERMS_2020:
        return None
    place = _INCOTERMS_SUFFIX_RE.sub("", m.group(4)).strip(" ,") or None
    return PriceTerm(code=code, place=place, place_side_field=_PLACE_SIDE_FIELD.get(_PLACE_SIDE[code]))


def format_price_term(code: str, place: str) -> str:
    """표준형 문자열을 만든다 — 조건 대문자 + 장소 Title Case + 병기.

    장소가 없는 호출은 이 함수의 책임 밖이다(호출부가 `PriceTerm.place`
    가 `None` 인지 먼저 확인해야 한다) — 장소를 지어내지 않는다는 원칙을
    이 함수 안에서도 지키려면 빈 장소를 받아 형식만 갖춘 문자열을 만들지
    않아야 한다.
    """
    return f"{code.upper()} {place.strip().title()} (Incoterms 2020)"


def incoterms_consistent_with_checks() -> bool:
    """`INCOTERMS_2020` 과 `ruleEngine.checks.INCOTERMS` 가 같은 집합인가.

    두 튜플은 의미상 같은 표(Incoterms 2020 11개 조건)를 중복해서 들고
    있다. `checks.py` 를 이번 브랜치에서 건드리지 않기로 했으므로 상수를
    합치는 대신 이 함수로 정합성을 테스트에 묶는다(T13) — 한쪽만 바뀌면
    이 함수가 `False` 를 돌려주어 조용한 어긋남을 막는다.

    지연 임포트인 이유: 평소 경로(캐스케이드가 `parse_price_term` 등을
    쓰는 경로)에서 `ruleEngine` 을 끌어오지 않기 위해서다. 이 함수를
    실제로 부르는 것은 정합성 테스트뿐이다.
    """
    from f3_rules.checks import INCOTERMS as _checks_incoterms

    return set(INCOTERMS_2020) == set(_checks_incoterms)


# ════════════════════════════════════════════════════════════════
# HS / HSK
# ════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class HSCode:
    """HS/HSK 형식 검사 결과. **형식(자릿수·구분자)만 판정한다** — 그 코드가
    그 물품에 맞는지, 6단위가 실재하는 품목 분류인지는 판정 대상이 아니다.
    """

    normalized: str  # 국제 6단위 정규형 "nnnn.nn"
    hsk: Optional[str]  # HSK 10단위 정규형 "nnnn.nn-nnnn". 없으면 None
    hsk_present: bool  # False 면 6단위뿐 — 관세율표 미적재로 뒤 4자리를 만들지 않는다


_HS_RE = re.compile(r"^(?:HS\s*)?(\d{4})\.?(\d{2})(?:[-\s]?(\d{4}))?$", re.IGNORECASE)


def normalize_hs(text: str) -> Optional[HSCode]:
    """`847130`·`8471.30`·`HS 8471.30`·`8471.30-1000` 을 형식 정규형으로 바꾼다.

    관세율표를 적재하지 않았으므로 6단위만 주어졌을 때 **뒤 4자리를
    만들어내지 않는다.** `hsk_present=False` 로 그 사실을 호출부에
    알린다 — 호출부는 이 플래그로 `Notice(kind="not_covered")` 를 만들 수
    있다.
    """
    m = _HS_RE.match((text or "").strip())
    if not m:
        return None
    chapter, heading, hsk_tail = m.groups()
    normalized = f"{chapter}.{heading}"
    if hsk_tail:
        return HSCode(normalized=normalized, hsk=f"{normalized}-{hsk_tail}", hsk_present=True)
    return HSCode(normalized=normalized, hsk=None, hsk_present=False)


# ════════════════════════════════════════════════════════════════
# UN/LOCODE — 형식만
# ════════════════════════════════════════════════════════════════

# 3자리 자리에 0·1 을 쓰지 않는다 — UN/LOCODE 자체 규칙(자모와 혼동되는
# 숫자를 뺀다). 국가 코드 2자리는 ISO 3166-1 alpha-2 "형식"만 본다(실재
# 여부는 사전 커버리지의 몫).
LOCODE_RE = re.compile(r"^[A-Z]{2}[A-Z2-9]{3}$")


@dataclass(frozen=True)
class LocodeCheck:
    """UN/LOCODE 형식 검사 결과. **형식만** — 코드가 실재하는 항구인지는
    사전 커버리지에 달렸고 이 함수의 판정 범위 밖이다.
    """

    normalized: str
    ok: bool
    country: Optional[str]  # ok 일 때만 앞 2자리


def normalize_locode(text: str) -> str:
    """"KR PUS" · "krpus" 를 "KRPUS" 로. 공백을 전부 지우고 대문자화한다."""
    return re.sub(r"\s+", "", text or "").upper()


def validate_locode(text: str) -> LocodeCheck:
    """LOCODE 형식을 검사한다."""
    normalized = normalize_locode(text)
    ok = bool(LOCODE_RE.match(normalized))
    return LocodeCheck(normalized=normalized, ok=ok, country=normalized[:2] if ok else None)


def locode_ok(text: str) -> bool:
    """`validate_locode(text).ok` 의 축약형."""
    return validate_locode(text).ok


# ════════════════════════════════════════════════════════════════
# 상호 접미 (party_suffix)
# ════════════════════════════════════════════════════════════════

# `f3_rules/checks.py:_LEGAL_SUFFIXES` 를 복사한다 — 모듈 docstring의
# "임포트 대신 복사" 논거. 원본과 어긋나면(원본에 새 접미가 추가되는 등)
# 이 파일도 사람이 따로 갱신해야 하지만, 그 대가로 `terms` 가
# `ruleEngine` 을 몰라도 된다.
_LEGAL_SUFFIXES: Set[str] = {
    "CO", "LTD", "INC", "CORP", "LLC", "GMBH", "PTE", "PVT",
    "LIMITED", "COMPANY", "CORPORATION", "AG", "SA", "BV", "NV",
}

# 접미 토큰 → 표준 표기. `_LEGAL_SUFFIXES` 의 원소를 사람이 읽는 형태로
# 바꾼다. 두 토큰 이상이 이어지면(`CO`+`LTD`) ", " 로 이어 붙여
# "Co., Ltd." 가 나오도록 각 항목 끝에 이미 구두점을 넣어 두었다.
_SUFFIX_CANON: Dict[str, str] = {
    "CO": "Co.", "LTD": "Ltd.", "INC": "Inc.", "CORP": "Corp.",
    "LLC": "LLC", "GMBH": "GmbH", "PTE": "Pte.", "PVT": "Pvt.",
    "LIMITED": "Limited", "COMPANY": "Company", "CORPORATION": "Corporation",
    "AG": "AG", "SA": "SA", "BV": "BV", "NV": "NV",
}

_SUFFIX_WORD = "(?:" + "|".join(sorted(_LEGAL_SUFFIXES, key=len, reverse=True)) + ")"
_SUFFIX_RE = re.compile(
    rf"(?<!\S)(?P<suffix>{_SUFFIX_WORD}(?:[.,]*\s*{_SUFFIX_WORD})*[.,]*)\s*$",
    re.IGNORECASE,
)
_SUFFIX_WORD_RE = re.compile(_SUFFIX_WORD, re.IGNORECASE)


@dataclass(frozen=True)
class PartySuffixCheck:
    """상호 접미 정규화 결과.

    `span` 은 원문에서 접미 토큰이 차지하는 문자 오프셋(반열림 구간)이며
    **상호 본체를 포함하지 않는다.** `"GAE WOON CO.,LTD"` 에서
    `span=(9, 16)` 은 `"CO.,LTD"` 만 가리키고 `"GAE WOON"` 은 이 타입이
    건드릴 방법이 구조적으로 없다 — `apply` 가 지키는 게 아니라 span 이
    강제한다(`f2-standard-terms.md` §"고유명사·품명").
    """

    matched: bool
    span: Optional[Tuple[int, int]]
    as_is: Optional[str]  # 원문 접미 토큰(원래 표기 그대로)
    to_be: Optional[str]  # 표준 표기. matched=False 면 None


def party_suffix(text: str) -> PartySuffixCheck:
    """문자열 끝의 상호 접미를 찾아 표준 표기 후보를 만든다.

    본체는 절대 건드리지 않는다 — 정규식이 문자열 **끝**의 접미 토큰
    클러스터만 찾고, `span` 은 그 클러스터의 위치만 담는다.
    """
    m = _SUFFIX_RE.search(text or "")
    if not m:
        return PartySuffixCheck(False, None, None, None)
    span = m.span("suffix")
    raw = m.group("suffix")
    tokens = [t.upper() for t in _SUFFIX_WORD_RE.findall(raw)]
    to_be = ", ".join(_SUFFIX_CANON[t] for t in tokens)
    return PartySuffixCheck(True, span, raw, to_be)


__all__ = [
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

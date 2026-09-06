"""
F2 비교 키 — `normalize_key` / `loose_key`.

## 왜 `ocr/` 의 세 `_normalize` 와 다른가, 왜 통합하지 않는가

이 저장소에는 이미 "정규화"라는 이름의 함수가 세 개 있다. 겉보기엔 전부
"영숫자만 남기고 대문자로"라 하나로 합칠 수 있어 보인다. 실제로는 각자
**서로 다른 것을 지키려고** 다르게 만들어졌다 (`docs/f2/HANDOFF.md` §6.2):

| 위치 | 정규식 | 남기는 것 | 왜 |
|---|---|---|---|
| `ocr/doc_types.py:212` (`_normalize`) | `[^A-Z0-9가-힣 ]` | 한글 | `"선하증권"` 이 서류 종류 판별 키워드다 |
| `ocr/field_parser.py` (`_locate_anchor`) | `[^A-Z0-9/ ]` | `/` | `"B/L NO"` 앵커가 슬래시를 쓴다 |
| `ocr/draft.py:_normalize` | `[^A-Z0-9 ]` | 둘 다 버림 | 라벨 어휘 대조 |

셋이 다른 건 버그가 아니라 서로 다른 요구다. 통합하면 최소 두 호출부의
동작이 바뀌는데, 그건 F1 의 가장 뜨겁고 가장 잘 테스트된 경로다. 얻는 것은
중복 제거 3줄이고 잃는 것은 F1 회귀 위험이다 — 남는 장사가 아니다.

그리고 **F2 는 통합해도 자기 키가 필요하다.** 위 세 함수 중 어느 것도
`normalize_key` 가 요구하는 것을 만족하지 않는다:

- `doc_types._normalize` 는 한글은 남기지만 **숫자에 섞인 점(`.`)을 버린다**
  — `"8471.30"` 이 `"8471 30"` 이 되어 HS 코드 별칭이 깨진다.
- `field_parser._locate_anchor` 는 `/` 를 남기고 점을 버린다 — 앵커 매칭용이지
  비교 키가 아니다.
- `draft._normalize` 는 한글 자체를 버린다 — `"부산"`·`"서렌더"`(surrender B/L)
  같은 한글 별칭이 F2 의 절반이므로 이 함수로는 시작도 못 한다.

`normalize_key` 는 한글과 점을 **둘 다** 남긴다:

- 한글을 남기는 이유 — `"부산"`/`"Pusan"`/`"PUS"` 가 같은 항구를 가리키는
  별칭이고, 한글 표기가 사전에 그대로 실린다. 버리면 이 별칭들이 정규화
  단계에서부터 서로 다른 키로 갈라진다.
- 점을 남기는 이유 — `"8471.30"`(HS 코드)·`"F.O.B"`(Incoterms 약어에 점을
  찍는 옛 표기) 처럼 점이 값의 일부인 별칭이 있다. 버리면 `"8471.30"` 과
  `"847130"` 이 같은 키가 되어, 자릿수가 다른 별개의 HS 코드가 뒤섞인다.

`loose_key` 는 그 반대 방향이다 — 유사도(3-gram Dice) 비교에서는 점·공백
같은 구두점 표기 차이가 **잡음**이다. `"F.O.B"` 와 `"FOB"` 를 유사도 계산에서
같게 보려면 점을 지운 뼈대가 필요하다. `normalize_key` 를 비교(exact/alias)에,
`loose_key` 를 유사도(④)에 쓰는 이유가 이것이다 — 용도가 다르면 지켜야 할
것도 다르다.

## 의존성 제약

`re`·`unicodedata` 뿐이다. `ocr`·`ruleEngine`·`yaml` 을 임포트하지 않는다.
F6(현실 대조, `HANDOFF.md` §6.3)이 `from terms import normalize_key` 로 이
모듈만 가볍게 끌어 쓸 수 있어야 하기 때문이다. `ocr` 를 끌어오면 PaddleOCR
쪽 무거운 임포트 체인이 따라오고, `ruleEngine`/`yaml` 을 끌어오면 F6 이
필요 없는 룰 카탈로그 로딩까지 짊어진다.
"""

from __future__ import annotations

import re
import unicodedata

# 비교 키에서 지우는 것 — 위 한글·숫자·점 유지 논거의 반대 서술.
# `A-Z0-9가-힣.` 이외는 전부 공백으로 치환한다(대문자 변환 후 매칭이므로
# 소문자 범위는 필요 없다).
_NORMALIZE_STRIP = re.compile(r"[^A-Z0-9가-힣.]+")
_WHITESPACE = re.compile(r"\s+")

# 유사도 키에서 추가로 지우는 것 — 점과 남은 공백. `normalize_key` 의 결과에서
# 한 번 더 걷어내므로 `A-Z0-9가-힣` 이외를 전부 없앤다.
_LOOSE_STRIP = re.compile(r"[^A-Z0-9가-힣]+")


def normalize_key(text: str) -> str:
    """비교용 키(①exact·②alias 단계가 쓴다).

    NFKC 로 전각·호환 문자를 정규화한 뒤 대문자로 올리고, 한글·숫자·점
    이외는 공백으로 뭉갠다. 한글을 남기는 이유는 `"부산"`·`"서렌더"` 가
    별칭이기 때문이고, 점을 남기는 이유는 `"8471.30"`·`"F.O.B"` 가
    별칭이기 때문이다 — 모듈 docstring 참고.

    `text` 가 `None`/빈 문자열이어도 예외를 던지지 않고 빈 문자열을 돌려준다
    — OCR 추출 실패로 값이 없는 필드가 흔하고, 호출부마다 `None` 체크를
    반복시키지 않기 위함이다.
    """
    s = unicodedata.normalize("NFKC", text or "").upper()
    s = _NORMALIZE_STRIP.sub(" ", s)
    return _WHITESPACE.sub(" ", s).strip()


def loose_key(text: str) -> str:
    """유사도용 키(④similarity 단계가 쓴다).

    `normalize_key` 의 결과에서 점·공백까지 마저 지운 뼈대다.
    `"F.O.B"` 와 `"FOB"`, `"MSKU 123456 5"` 와 `"MSKU1234565"` 를 같은 키로
    만든다 — 3-gram Dice 유사도가 구두점·공백의 유무가 아니라 **글자
    배열의 근접도**를 재도록 잡음을 미리 걷어내는 것이다.

    exact/alias 단계에서 이 키를 쓰지 않는 이유: 점·공백을 지우면
    `"8471.30"` 과 `"84.71.30"` 처럼 자릿수가 다른 값도 같은 키가 될 수
    있다. 유사도 순위 매기기(상위 몇 건을 후보로 보여주는 것)에서는
    허용 가능한 오차지만, exact/alias 는 "이 값이 정확히 이 표준 표기다"를
    단정하는 단계라 그 오차가 곧 오답이 된다.
    """
    return _LOOSE_STRIP.sub("", normalize_key(text))


__all__ = ["loose_key", "normalize_key"]

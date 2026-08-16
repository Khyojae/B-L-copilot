"""
리포트 산문의 출력 무결성 검사 (기획안 v2 5.4 · 5.7).

5.4 는 "LLM 이 새로운 수치를 만들어 내지 못하도록 **출력 검증기가 리포트 내
수치와 원본 데이터의 일치를 대조**한다"고 쓰고, 5.7 은 "생성문에 포함된 인용
ID 가 실제 판정 객체에 존재하는지 대조하고, 존재하지 않는 인용이 있으면
재생성한다. 2회 실패 시 LLM 서술을 버리고 템플릿 문장으로 대체한다"고 쓴다.

## 프롬프트 제약은 검증이 아니다

`narrative._SYSTEM_PROMPT` 는 이미 "주어진 수치 외에 어떤 숫자도 만들지
마십시오"라고 지시한다. 그건 부탁이지 보장이 아니다. 리포트의 골격(건수·확률·
체크리스트)은 템플릿이 채우므로 안전하지만, **LLM 이 쓰는 산문은 자유 문장**
이고 거기 섞인 숫자 하나를 지금까지 아무도 보지 않았다.

`acceptance.py` 의 "리포트 수치와 판정 데이터 일치율 100%" 도 여기를 보지
않는다 — `build_report` 만 부르고 `apply_narrative` 를 거치지 않기 때문에
템플릿이 채운 필드끼리만 대조한다. 즉 지금까지 통과율 100% 는 **산문을 뺀
100%** 였다.

## 판정 원칙 — 못 찾으면 위반이다

산문에 있는 숫자가 리포트 어디에서도 발견되지 않으면 위반으로 본다. 반대로
하면(찾을 수 있을 때만 위반) 검사가 아무것도 막지 못한다.

이 판정은 엄격한 쪽으로 틀린다 — 정상 문장이 걸려 템플릿으로 떨어질 수 있다.
그 대가를 받아들이는 이유는 두 실패의 무게가 다르기 때문이다. 템플릿 요약은
사람이 읽으면 딱딱할 뿐 **틀리지 않는다.** 지어낸 숫자가 실린 리포트는 은행에
낼 서류의 근거로 쓰인다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Set

# 숫자 토큰. 천 단위 콤마와 소수점을 한 덩어리로 잡는다.
# `1,741.56` 을 1 / 741 / 56 으로 쪼개면 셋 다 리포트에 없어 오탐이 된다.
_NUMBER = re.compile(r"\d+(?:[,.]\d+)*")

# 룰 ID. `rules.yaml` 은 D + 3자리(+선택 접미문자), `cross_rules.yaml` 은 X + 3자리.
_RULE_ID = re.compile(r"\b([DX]\d{3}[A-Z]?)\b")

# 조문 인용. `UCP 600 Art.14(c)` · `Art. 20 (a)(ii)` 를 모두 잡는다.
_ARTICLE = re.compile(r"Art\.?\s*\d+\s*(?:\([0-9a-z]+\)\s*)*", re.IGNORECASE)

# 백분율 표기를 허용하기 위한 배수. 확률 0.35 를 산문이 "35%" 로 쓰는 것은
# 지어낸 것이 아니라 같은 값을 다르게 적은 것이다.
_PERCENT = 100


@dataclass
class IntegrityReport:
    """검사 결과. 무엇이 왜 걸렸는지까지 남긴다.

    통과 여부만 돌려주면 재생성이 실패했을 때 원인을 알 수 없다. 로그에
    찍히는 값이므로 걸린 토큰을 그대로 싣는다.
    """

    unknown_numbers: List[str] = field(default_factory=list)
    unknown_rule_ids: List[str] = field(default_factory=list)
    unknown_articles: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.unknown_numbers or self.unknown_rule_ids or self.unknown_articles
        )

    def describe(self) -> str:
        parts = []
        if self.unknown_numbers:
            parts.append(f"근거 없는 수치 {self.unknown_numbers}")
        if self.unknown_rule_ids:
            parts.append(f"판정에 없는 룰 ID {self.unknown_rule_ids}")
        if self.unknown_articles:
            parts.append(f"판정에 없는 조문 {self.unknown_articles}")
        return " · ".join(parts) or "통과"

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "unknown_numbers": self.unknown_numbers,
            "unknown_rule_ids": self.unknown_rule_ids,
            "unknown_articles": self.unknown_articles,
        }


def check_narrative(report: Any, *texts: Optional[str]) -> IntegrityReport:
    """산문이 리포트 데이터를 벗어나지 않았는지 본다.

    `texts` 는 headline·narrative 처럼 LLM 이 쓴 문장이다. 여러 개를 받는
    이유는 둘을 따로 검사해 봐야 얻을 것이 없기 때문이다 — 하나라도 어긋나면
    그 리포트의 서술을 통째로 버린다.
    """
    prose = "\n".join(t for t in texts if t)
    if not prose.strip():
        return IntegrityReport()

    allowed_numbers = _allowed_numbers(report)
    allowed_rule_ids = {r.rule_id for r in getattr(report, "risks", []) if r.rule_id}
    allowed_articles = _allowed_articles(report)

    # 룰 ID 와 조문은 숫자를 포함한다(D003, Art.14(c)). 수치 검사에 그대로
    # 넘기면 3 과 14 가 근거 없는 숫자로 잡힌다. 먼저 걷어내고 남은 것만 센다.
    remainder = _ARTICLE.sub(" ", _RULE_ID.sub(" ", prose))

    unknown_numbers = [
        raw for raw in _NUMBER.findall(remainder)
        if _to_number(raw) is not None and _to_number(raw) not in allowed_numbers
    ]
    unknown_rule_ids = [
        rid for rid in _RULE_ID.findall(prose) if rid not in allowed_rule_ids
    ]
    unknown_articles = [
        raw.strip() for raw in _ARTICLE.findall(prose)
        if _normalize_article(raw) not in allowed_articles
    ]

    return IntegrityReport(
        unknown_numbers=_unique(unknown_numbers),
        unknown_rule_ids=_unique(unknown_rule_ids),
        unknown_articles=_unique(unknown_articles),
    )


# ── 허용 집합 ────────────────────────────────────────────────────

def _allowed_numbers(report: Any) -> Set[float]:
    """리포트가 근거로 가진 수치 전부.

    구조화된 값과 **문자열에 박힌 값을 함께** 모은다. 위반 메시지의
    `884 KG`, 조문 출처의 연도, 기한 문자열의 날짜가 전부 산문에 나올 수 있고
    그것들은 지어낸 값이 아니다.
    """
    numbers: Set[float] = set()

    probability = getattr(report, "defect_probability", None)
    if probability is not None:
        numbers.add(float(probability))
        # 산문이 백분율로 쓰는 경우. 0.35 → 35 · 35.0
        numbers.add(round(float(probability) * _PERCENT, 6))

    for value in (getattr(report, "counts", None) or {}).values():
        numbers.add(float(value))

    for name in ("risks", "checklist", "recommendations", "unchecked"):
        numbers.add(float(len(getattr(report, name, []) or [])))

    for text in _texts_of(report):
        numbers |= _numbers_in(text)

    return numbers


def _texts_of(report: Any) -> Iterable[str]:
    """리포트가 들고 있는 모든 문자열. 수치 추출의 재료다."""
    for name in ("bl_no", "lc_no", "model", "outlook", "outlook_detail"):
        value = getattr(report, name, None)
        if value:
            yield str(value)

    generated = getattr(report, "generated_at", None)
    if generated:
        yield str(generated)

    deadline = getattr(report, "deadline", None)
    if deadline is not None:
        for name in ("effective_due", "expiry_date", "presentation_due", "days_left"):
            value = getattr(deadline, name, None)
            if value is not None:
                yield str(value)

    for risk in getattr(report, "risks", []) or []:
        yield from _strings(risk.title, risk.message, risk.source)
        yield from (str(v) for v in (risk.observed or {}).values() if v)
        yield from (str(f) for f in (risk.fields or []))

    for item in getattr(report, "checklist", []) or []:
        yield from _strings(item.label, item.detail)

    for rec in getattr(report, "recommendations", []) or []:
        yield from _strings(rec.action, rec.source)

    for item in getattr(report, "unchecked", []) or []:
        yield from _strings(item.title, item.reason)


def _allowed_articles(report: Any) -> Set[str]:
    """판정이 실제로 인용한 조문."""
    articles: Set[str] = set()
    for risk in getattr(report, "risks", []) or []:
        articles |= {_normalize_article(a) for a in _ARTICLE.findall(risk.source or "")}
    for rec in getattr(report, "recommendations", []) or []:
        articles |= {_normalize_article(a) for a in _ARTICLE.findall(rec.source or "")}
    return articles


# ── 정규화 ───────────────────────────────────────────────────────

def _strings(*values: Optional[str]) -> Iterable[str]:
    for value in values:
        if value:
            yield str(value)


def _numbers_in(text: str) -> Set[float]:
    """문자열에 있는 수치. 하위 토큰도 함께 허용한다.

    `2026-06-30` 은 하나의 날짜지만 산문은 "2026년 6월 30일"로 쓴다. 원문
    토큰만 허용하면 정상 문장이 걸린다. 그래서 `2026`·`6`·`30` 을 모두 넣는다.
    """
    found: Set[float] = set()
    for raw in _NUMBER.findall(text):
        value = _to_number(raw)
        if value is not None:
            found.add(value)
        # 콤마·소수점으로 이어진 덩어리의 조각도 허용한다.
        for piece in re.split(r"[,.]", raw):
            piece_value = _to_number(piece)
            if piece_value is not None:
                found.add(piece_value)
    return found


def _to_number(raw: str) -> Optional[float]:
    """숫자 토큰 → float. 천 단위 콤마를 없앤 뒤 읽는다."""
    cleaned = raw.replace(",", "")
    if not cleaned or cleaned == ".":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_article(raw: str) -> str:
    """`Art. 14 (c)` 와 `Art.14(c)` 를 같은 것으로 본다."""
    return re.sub(r"\s+", "", raw).lower().rstrip(".")


def _unique(values: List[str]) -> List[str]:
    """순서를 지키며 중복을 없앤다. 로그에서 읽는 값이라 순서가 의미를 갖는다."""
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = ["IntegrityReport", "check_narrative"]

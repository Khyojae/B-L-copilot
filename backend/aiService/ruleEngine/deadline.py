"""제시기한 계산 (UCP 600 Art.14(c) · MT700 :31D:).

**한 곳에서만 계산한다.** 이전에는 두 곳이었다 — 룰엔진(`checks.presentation_period`)이
"기한을 넘었는가"를, 리포트(`report.builder._deadline`)가 "며칠 남았는가"를 각자
계산했다. 같은 조문에서 나온 같은 날짜인데 정의가 둘이면, UCP 개정이나 기본값
변경 때 한쪽만 고치게 된다. **그 실패는 조용하다** — 예외가 아니라 숫자가
달라질 뿐이고, 리포트에는 그럴듯한 날짜가 그대로 찍힌다.

실제로 둘은 이미 어긋나 있었다. 룰은 선적일 필드를 `on_board_date` →
`date_of_issue` 순으로 찾는데(D018), 리포트는 `on_board_date` 만 봤다. 본선적재일
없이 발행일만 있는 서류에서 **룰은 하자로 잡고 리포트는 "기한을 계산하지
못했습니다"** 를 띄웠다.

## 실질 기한은 둘 중 이른 날이다

Art.14(c) 는 선적일로부터 제시기간(기본 21일) 이내를 요구하고, 신용장은 그와
별개로 유효기일(31D)을 갖는다. 사용자가 지켜야 하는 것은 **이른 쪽**이다.

다만 **룰과 리포트가 보는 범위는 다르다.** 룰 D018 은 21일 다리만 판정한다 —
유효기일 경과는 별도 룰(D017)이 잡으므로, 여기서 함께 잡으면 같은 하자가 두 번
계상된다. 리포트는 사용자에게 "언제까지"를 하나로 답해야 하므로 둘을 합친다.
그래서 이 모듈은 두 값을 **따로 내주고**, 합치는 판단은 부르는 쪽에 맡긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from .types import DEFAULT_PRESENTATION_DAYS, LCTerms

# 선적일로 볼 필드와 그 우선순위. 본선적재일이 없으면 발행일로 갈음한다.
#
# 이 순서는 룰 카탈로그 D018 의 `fields` 와 **같아야 한다.** 어긋나면 룰과
# 리포트가 서로 다른 날짜로 같은 기한을 말하게 된다. 테스트가 대조한다
# (`test_report.py::test_룰과_리포트가_같은_선적일을_본다`).
SHIPMENT_DATE_FIELDS: Tuple[str, ...] = ("on_board_date", "date_of_issue")


@dataclass(frozen=True)
class PresentationDeadline:
    """제시기한 한 벌.

    두 다리를 따로 들고 있다 — 룰은 `presentation_due` 만 보고, 리포트는
    `effective_due` 를 보여 준다.
    """

    # 선적일 + 제시기간 (Art.14(c))
    presentation_due: Optional[date]
    # 신용장 유효기일 (:31D:)
    expiry: Optional[date]
    # 둘 중 이른 날. 사용자가 실제로 지켜야 하는 기한이다.
    effective_due: date
    days_left: int
    basis: str
    # 기한 계산에 쓴 선적일과 그 출처 필드. 리포트가 근거를 밝힐 때 쓴다.
    shipped_from: Optional[str] = None

    @property
    def is_overdue(self) -> bool:
        return self.days_left < 0

    def to_dict(self) -> dict:
        return {
            "presentation_due": _iso(self.presentation_due),
            "expiry": _iso(self.expiry),
            "effective_due": _iso(self.effective_due),
            "days_left": self.days_left,
            "is_overdue": self.is_overdue,
            "basis": self.basis,
            "shipped_from": self.shipped_from,
        }


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def presentation_days(lc: Optional[LCTerms]) -> int:
    """적용할 제시기간.

    신용장이 :48: 로 명시하면 그 값, 아니면 UCP 600 Art.14(c) 의 21일이다.
    기본값을 여기서 한 번만 결정한다 — 호출부마다 `or DEFAULT_...` 를 쓰면
    한 곳을 빠뜨렸을 때 그 경로만 다른 기한을 쓴다.
    """
    if lc is None:
        return DEFAULT_PRESENTATION_DAYS
    return lc.presentation_days or DEFAULT_PRESENTATION_DAYS


def shipment_date(
    bl, fields: Sequence[str] = SHIPMENT_DATE_FIELDS
) -> Tuple[Optional[str], Optional[datetime]]:
    """선적일과 그 출처 필드. 값이 있는 첫 필드를 쓴다.

    지역 import 는 순환을 피하기 위한 것이다 — `checks` 가 이 모듈을 쓴다.
    """
    from .checks import field_value, parse_date

    for name in fields:
        raw = field_value(bl, name)
        if not raw:
            continue
        parsed = parse_date(raw)
        if parsed is not None:
            return name, parsed
    return None, None


def due_from(shipped: datetime, lc: Optional[LCTerms]) -> date:
    """선적일 + 제시기간. 기한 자체의 정의는 이 한 줄뿐이어야 한다."""
    return (shipped + timedelta(days=presentation_days(lc))).date()


def compute(
    bl,
    lc: Optional[LCTerms] = None,
    as_of: Optional[datetime] = None,
    fields: Sequence[str] = SHIPMENT_DATE_FIELDS,
) -> Optional[PresentationDeadline]:
    """제시기한을 계산한다. 근거가 하나도 없으면 None.

    None 을 돌려주는 것과 기한이 0 인 것은 다르다. 계산하지 못한 것을 기한
    경과로 표시하면, 선적일이 비었을 뿐인 서류가 '수리 불가'로 보고된다.
    """
    from .checks import parse_date

    lc = lc or LCTerms()
    now = as_of or datetime.now()

    shipped_from, shipped = shipment_date(bl, fields)

    basis: List[str] = []
    due: Optional[date] = None
    if shipped is not None:
        due = due_from(shipped, lc)
        basis.append(
            f"선적일 + {presentation_days(lc)}일(UCP 600 Art.14(c))"
        )

    expiry_raw = lc.expiry_date
    expiry = parse_date(expiry_raw) if expiry_raw else None
    expiry_date = expiry.date() if expiry else None
    if expiry_date:
        basis.append("신용장 유효기일(31D)")

    candidates = [d for d in (due, expiry_date) if d]
    if not candidates:
        return None

    effective = min(candidates)
    return PresentationDeadline(
        presentation_due=due,
        expiry=expiry_date,
        effective_due=effective,
        days_left=(effective - now.date()).days,
        basis=" / ".join(basis) + (" 중 이른 날" if len(basis) > 1 else ""),
        shipped_from=shipped_from,
    )


__all__ = [
    "SHIPMENT_DATE_FIELDS",
    "PresentationDeadline",
    "compute",
    "due_from",
    "presentation_days",
    "shipment_date",
]

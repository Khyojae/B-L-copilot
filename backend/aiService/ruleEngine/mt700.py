"""MT700 원문 파서 — 기획안 v2 5.1 입력 사양.

`LCTerms.from_tags` 는 **이미 잘린** 태그 dict 를 받는다. 실무에서 오는 것은
SWIFT 전문 원문이므로 그 사이가 비어 있었고, 지금까지는 사람이 L/C 를 손으로
JSON 에 옮겨야 검증이 돌았다. 이 모듈이 그 자리를 메운다.

원칙 하나가 이 파서의 형태를 정한다 — **버린 것을 말한다.**

L/C 조건이 비어 있으면 그 조건을 쓰는 룰은 `not_evaluated` 로 빠지고, 화면에서
위반 0건은 '하자 없음'으로 읽힌다. 즉 **파서가 조용히 실패하면 시스템은 더
안전해 보인다.** 그래서 읽지 못한 태그(`unmapped`)와 정규화하며 버린 값(`notes`)을
결과에 함께 실어 돌려준다. 태그를 하나도 못 찾으면 빈 `LCTerms` 를 내주는 대신
예외를 던진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .checks import INCOTERMS, parse_date, parse_quantity
from .types import LCTerms


class MT700ParseError(ValueError):
    """전문에서 태그를 하나도 찾지 못했다."""


# 줄 앞의 `:20:` `:44E:` 같은 필드 태그. SWIFT 태그는 두 자리 숫자 +
# 선택적 영문 한 글자다.
_TAG_RE = re.compile(r"^:(\d{2}[A-Z]?):", re.MULTILINE)

# 전문 블록. 본문은 4번 블록에 있고 `-}` 로 닫힌다.
_BLOCK4_RE = re.compile(r"\{4:\s*(.*?)(?:\n?\s*-\})", re.DOTALL)

# 1·2·3·5번 블록(헤더·트레일러). 본문 밖이므로 통째로 버린다.
_OTHER_BLOCK_RE = re.compile(r"\{[1235]:[^{}]*\}")

# 46A 요구 서류 목록의 줄머리 장식. `+` 는 SWIFT 연속 줄 표시이고
# `1.` `1)` `-` 는 사람이 붙인 번호다.
_BULLET_RE = re.compile(r"^\s*(?:[+\-*]|\d+[.)])\s*")


@dataclass
class MT700Parse:
    """파싱 결과. `lc` 만 쓰면 되지만, 나머지가 없으면 무엇을 못 읽었는지 모른다."""

    lc: LCTerms
    tags: Dict[str, str] = field(default_factory=dict)
    """원문에서 잘라낸 태그. 정규화 전 값이다."""

    unmapped: Dict[str, str] = field(default_factory=dict)
    """태그로 인식했으나 `LCTerms` 에 자리가 없는 것. 47A 가 대표적이다."""

    notes: List[str] = field(default_factory=list)
    """정규화하며 버렸거나 해석하지 못한 것."""

    def to_dict(self) -> dict:
        return {
            "lc": self.lc.to_dict(),
            "tags": self.tags,
            "unmapped": self.unmapped,
            "notes": self.notes,
        }


def parse_mt700(text: str) -> MT700Parse:
    """MT700 전문 원문 → `LCTerms` + 파싱 진단."""
    tags, notes = _split_tags(text)
    if not tags:
        raise MT700ParseError(
            "MT700 태그를 찾지 못했습니다. 줄 앞에 ':20:' 같은 필드 태그가 있어야 합니다."
        )

    fields, unmapped = _apply_tags(tags, notes)
    for tag in unmapped:
        notes.append(_UNMAPPED_NOTES.get(tag, f":{tag}: 는 L/C 조건으로 옮기지 않았습니다."))

    return MT700Parse(
        lc=LCTerms(**fields),  # type: ignore[arg-type]
        tags=tags,
        unmapped=unmapped,
        notes=notes,
    )


def terms_from_tags(tags: Dict[str, str], lc_no: Optional[str] = None) -> LCTerms:
    """이미 잘린 태그 dict → `LCTerms`. `LCTerms.from_tags` 가 이 함수다.

    **원문 파서와 같은 정규화를 탄다.** 태그 값을 필드에 그대로 꽂던 예전
    구현은 두 가지로 틀렸다 — 46A 를 문자열로 넣어 `documents_required` 가
    문자 단위로 순회됐고(정상 L/C 에 D016 을 날조한다), 44C 의 `260630` 을
    그대로 두어 날짜 룰이 통째로 '해석 실패'로 빠졌다.

    진단(`notes`·`unmapped`)은 버린다. 돌려줄 자리가 없는 진입점이므로,
    무엇을 못 읽었는지 알아야 하면 `parse_mt700` 을 쓸 것.
    """
    fields, _ = _apply_tags({k: str(v) for k, v in tags.items()}, [])
    if lc_no is not None:
        fields["lc_no"] = lc_no
    return LCTerms(**fields)  # type: ignore[arg-type]


def _apply_tags(
    tags: Dict[str, str], notes: List[str]
) -> tuple[Dict[str, object], Dict[str, str]]:
    fields: Dict[str, object] = {}
    unmapped: Dict[str, str] = {}
    for tag, raw in tags.items():
        handler = _HANDLERS.get(tag)
        if handler is None:
            unmapped[tag] = raw
            continue
        handler(raw, fields, notes)
    # 47A/45A 를 함께 봐야 해서 태그별 핸들러 루프 밖에 둔다 — 값 자체는
    # 위 루프가 이미 채운 `tags` 원본에서 다시 읽는다.
    _h_incoterms(tags, fields, notes)
    return fields, unmapped


def _split_tags(text: str) -> tuple[Dict[str, str], List[str]]:
    """전문을 태그 → 값으로 자른다. 값은 다음 태그 전까지 여러 줄일 수 있다."""
    notes: List[str] = []
    body = _strip_blocks(str(text or "").replace("\r\n", "\n").replace("\r", "\n"))

    matches = list(_TAG_RE.finditer(body))
    tags: Dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = body[m.end():end].strip()
        tag = m.group(1)
        if tag in tags:
            # MT700 에서 같은 태그가 두 번 오는 것은 정상이 아니다. 나중 값으로
            # 덮으면 어느 쪽이 반영됐는지 알 수 없으므로 먼저 온 값을 지킨다.
            notes.append(f":{tag}: 가 두 번 이상 나와 첫 값만 씁니다.")
            continue
        tags[tag] = value
    return tags, notes


def _strip_blocks(text: str) -> str:
    """`{4:...-}` 안쪽만 남긴다. 블록 구조가 없으면 원문 그대로."""
    m = _BLOCK4_RE.search(text)
    if m:
        return m.group(1)
    return _OTHER_BLOCK_RE.sub("", text)


# ── 값 정규화 ────────────────────────────────────────────────────

def _first_line(raw: str) -> str:
    for line in raw.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _joined(raw: str) -> str:
    """연속 줄을 한 줄로. SWIFT 는 `+` 로 줄을 잇는다."""
    parts = [_BULLET_RE.sub("", line).strip() for line in raw.splitlines()]
    return " ".join(p for p in parts if p)


def _swift_date(raw: str, tag: str, notes: List[str]) -> Optional[str]:
    """YYMMDD → ISO. 사람이 손으로 적은 형식도 받는다.

    SWIFT 날짜에는 세기가 없다. 2000년대로 읽는다 — 무역 서류에 1900년대
    유효기일이 들어올 일은 없고, 그 가정이 틀리면 날짜 룰이 전부 어긋나므로
    조용히 두지 않고 여기 적어 둔다.
    """
    head = _first_line(raw)
    m = re.match(r"^(\d{6})", head)
    if m:
        yy, mm, dd = int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:])
        try:
            return datetime(2000 + yy, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            notes.append(f":{tag}: 날짜가 달력에 없습니다: {m.group(1)}")
            return None

    parsed = parse_date(head)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")

    notes.append(f":{tag}: 날짜를 해석하지 못했습니다: {head}")
    return None


def _swift_amount(raw: str, notes: List[str]) -> tuple[Optional[str], Optional[str]]:
    """`USD123456,78` → (`USD`, `USD 123,456.78`).

    **SWIFT 의 콤마는 소수점이다.** 그대로 두면 `parse_amount` 가 콤마를
    천단위로 보고 지워 금액이 100배가 된다 — 송장 금액 대조(X009)가
    통과해 버리는 조용한 실패다. 그래서 여기서 표기를 확정한다.
    """
    head = _first_line(raw).upper()
    m = re.match(r"^([A-Z]{3})\s*([\d.,]+)", head)
    if not m:
        notes.append(f":32B: 통화·금액을 해석하지 못했습니다: {head}")
        return None, None

    currency, digits = m.group(1), m.group(2)
    amount = _to_amount(digits, notes)
    if amount is None:
        return currency, None
    return currency, f"{currency} {amount:,.2f}"


def _to_amount(digits: str, notes: List[str]) -> Optional[float]:
    if digits.endswith(","):          # SWIFT 정수 표기 `1000,`
        digits = digits[:-1]
    elif "." in digits and "," in digits:  # 사람이 적은 `123,456.78`
        digits = digits.replace(",", "")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        if len(tail) <= 2:            # SWIFT 소수점 `123456,78`
            digits = f"{head}.{tail}"
        else:                          # `1,000` — 규격상 소수점이지만 통화 금액이 아니다
            notes.append(f":32B: 콤마를 천단위로 읽었습니다: {digits}")
            digits = digits.replace(",", "")
    try:
        return float(digits)
    except ValueError:
        notes.append(f":32B: 금액을 해석하지 못했습니다: {digits}")
        return None


def _allowed_or_prohibited(raw: str, tag: str, notes: List[str]) -> Optional[str]:
    """`NOT ALLOWED` → PROHIBITED.

    부정형을 먼저 본다. `NOT ALLOWED` 는 `ALLOWED` 를 품고 있어서 순서를
    바꾸면 금지가 허용으로 뒤집힌다.
    """
    value = _joined(raw).upper()
    if not value:
        return None
    if re.search(r"\bNOT\s+ALLOWED\b|\bNOT\s+PERMITTED\b|PROHIBIT", value):
        return "PROHIBITED"
    if re.search(r"\bALLOWED\b|\bPERMITTED\b", value):
        return "ALLOWED"
    # CONDITIONAL 등. 기본값(허용)을 그대로 두되 사람이 보게 남긴다.
    notes.append(f":{tag}: 값을 허용/금지로 판정하지 못했습니다: {value}")
    return None


# ── 태그 처리기 ──────────────────────────────────────────────────

Handler = Callable[[str, Dict[str, object], List[str]], None]


def _h_lc_no(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["lc_no"] = _first_line(raw)


def _h_expiry(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    # 31D 는 날짜 뒤에 장소가 붙는다. `LCTerms` 에 장소 자리가 없어 버리므로
    # 무엇을 버렸는지 남긴다.
    value = _swift_date(raw, "31D", notes)
    if value:
        out["expiry_date"] = value
    place = re.sub(r"^\s*\d{6}\s*", "", _first_line(raw)).strip()
    if place:
        notes.append(f":31D: 유효장소 '{place}' 는 검증에 쓰지 않습니다.")


def _h_amount(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    currency, amount = _swift_amount(raw, notes)
    if currency:
        out["currency"] = currency
    if amount:
        out["currency_amount"] = amount


def _h_tolerance(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    nums = re.findall(r"\d+(?:[.,]\d+)?", _joined(raw))
    if not nums:
        notes.append(f":39A: 허용 오차를 해석하지 못했습니다: {_joined(raw)}")
        return
    plus = float(nums[0].replace(",", "."))
    out["tolerance_pct"] = plus
    if len(nums) > 1 and float(nums[1].replace(",", ".")) != plus:
        # 룰의 허용 오차는 대칭 한 값이다. 비대칭 신용장이면 큰 쪽을 쓰면
        # 초과분을 놓치므로 작은 쪽(엄격한 쪽)을 쓰고 사실을 남긴다.
        minus = float(nums[1].replace(",", "."))
        out["tolerance_pct"] = min(plus, minus)
        notes.append(
            f":39A: 허용 오차가 비대칭입니다(+{plus:g}/-{minus:g}) — "
            f"엄격한 쪽 {min(plus, minus):g}% 를 적용합니다."
        )


def _h_partial(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    value = _allowed_or_prohibited(raw, "43P", notes)
    if value:
        out["partial_shipment"] = value


def _h_transhipment(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    value = _allowed_or_prohibited(raw, "43T", notes)
    if value:
        out["transhipment"] = value


def _h_latest_shipment(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    value = _swift_date(raw, "44C", notes)
    if value:
        out["latest_shipment_date"] = value


def _h_pol(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["port_of_loading"] = _joined(raw)


def _h_pod(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["port_of_discharge"] = _joined(raw)


def _h_goods(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["description_of_goods"] = _joined(raw)
    # 거래조건(Incoterms)은 여기서 뽑지 않는다 — `_h_incoterms` 가 47A 를
    # 우선으로, 없으면 이 45A 값을 다시 읽어 채운다. 이유는 그쪽 주석 참고.


def _h_incoterms(tags: Dict[str, str], out: Dict[str, object], notes: List[str]) -> None:
    """거래조건 코드를 47A(추가조건) 우선, 없으면 45A(물품 명세)에서 뽑는다.

    **거래조건 "코드"만 담는다 — 장소 병기는 담지 않는다.** MT700 에는
    Incoterms 전용 태그가 없어 자유서식에서 뽑아야 하는데, `FOB BUSAN` 처럼
    장소까지 담으면 송장의 `FOB BUSAN` 과는 맞아도 `FOB BUSAN, KOREA` 와는
    어긋난다 — **동등 비교(X010)** 를 하는 룰이 정상 서류를 하자로 잡는다.
    이 우려는 X010 한정이다. D015(`contains_incoterms`)는 화물 명세가 그
    거래조건을 "포함"하는지만 보고, D026(`freight_prepaid_required`)은
    선불계(CFR/CIF/CPT/CIP/D 조건) 여부만 판단하므로 코드 하나로 충분하다.
    그래서 코드만 채운다.

    47A 를 45A 보다 먼저 보는 이유는 실무에서 거래조건이 47A 추가조건에 더
    자주 오기 때문이다. 한 태그 안에 서로 다른 코드가 2개 이상 있으면
    임의로 하나를 고르지 않고 비운다 — 기획안 9절의 '심각도 보수적 산정'.
    """
    for tag in ("47A", "45A"):
        raw = tags.get(tag)
        if not raw:
            continue
        text = _joined(raw).upper()
        found = sorted({t for t in INCOTERMS if re.search(rf"\b{t}\b", text)})
        if not found:
            continue  # 이 태그엔 표기가 없다 — 다음 우선순위로.
        if len(found) > 1:
            notes.append(
                f":{tag}: 거래조건이 여럿 표기되어({'/'.join(found)}) "
                "채우지 않았습니다 — 필요하면 incoterms 를 직접 지정하세요."
            )
            return
        out["incoterms"] = found[0]
        notes.append(f":{tag}: 에서 거래조건 {found[0]} 를 읽었습니다.")
        return


# 46A 의 B/L 요구 줄에 실리는 수하인 지정. 지시식이 "TO ORDER" 를 늘 품고
# 있어(`TO ORDER OF SHIPPER`·`TO THE ORDER OF <은행>`) 먼저 검사해야 한다 —
# 순서를 바꾸면 `MADE OUT TO ORDER` 가 기명식 패턴에 걸려 "ORDER" 를 상호로
# 오인한다.
_TO_ORDER_RE = re.compile(r"\bTO\s+(?:THE\s+)?ORDER\b", re.IGNORECASE)
_CONSIGNED_TO_RE = re.compile(r"\bCONSIGNED\s+TO\s+(.+)", re.IGNORECASE)
_MADE_OUT_TO_RE = re.compile(r"\bMADE\s+OUT\s+TO\s+(.+)", re.IGNORECASE)

# 통지처. `NOTIFY` 뒤 줄 끝까지가 이름이다 — "PARTY:"/"ADDRESS" 는 실무에서
# 흔한 장식이라 있어도 없어도 받는다.
_NOTIFY_RE = re.compile(r"\bNOTIFY\b\s*(?:PARTY|ADDRESS)?\s*[:\-]?\s*(.+)", re.IGNORECASE)


def _h_documents(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    items = [_BULLET_RE.sub("", line).strip() for line in raw.splitlines()]
    items = [i for i in items if i]
    out["documents_required"] = items
    _h_bl_consignment(items, out, notes)


def _h_bl_consignment(items: List[str], out: Dict[str, object], notes: List[str]) -> None:
    """B/L 요구 항목에서 수하인 지정과 통지처를 읽는다.

    지시식(`TO ORDER` 계열)은 `bl_consignment` 로 간다 — D027 이 이 값을
    본다. 기명식(`CONSIGNED TO`/`MADE OUT TO <상호>`)만 `consignee` 에
    담는다. D005B(`match_place`)는 상호 대조 규칙이라 "TO ORDER" 같은 문구를
    넣으면 안 된다.

    통지처는 두 분기 중 어느 쪽이든(지시식이어도) 같은 줄에 실리므로
    (`...MADE OUT TO ORDER AND BLANK ENDORSED NOTIFY <상호>`) 분기와 무관하게
    따로 뽑는다.
    """
    bl_item = next(
        (i for i in items if re.search(r"BILL OF LADING|\bB/?L\b", i, re.IGNORECASE)),
        None,
    )
    if not bl_item:
        return
    if _TO_ORDER_RE.search(bl_item):
        out["bl_consignment"] = "TO_ORDER"
    else:
        m = _CONSIGNED_TO_RE.search(bl_item) or _MADE_OUT_TO_RE.search(bl_item)
        if m:
            name = m.group(1).strip().rstrip(".")
            if name:
                out["consignee"] = name
    _h_notify(bl_item, out, notes)


def _h_notify(bl_item: str, out: Dict[str, object], notes: List[str]) -> None:
    """B/L 요구 줄의 `NOTIFY` 절에서 통지처를 뽑는다.

    `NOTIFY APPLICANT` 처럼 대상이 개설의뢰인 자신인 표기가 실무에 흔하다.
    원문 그대로 "APPLICANT" 를 `notify_party` 에 넣으면, 서류에는 실제
    개설의뢰인 상호가 인쇄되므로 D020(상호 대조)이 매번 불일치로 걸린다 —
    미표기보다 나쁜 오탐이다. 그래서 개설의뢰인(50)이 이미 읽혀 있으면 그
    상호로 치환한다. SWIFT 필드 순서상 50 은 46A 보다 항상 먼저 오므로
    보통은 채워져 있다. 못 채웠으면(비표준 순서 등) 원문을 그대로 두고
    그 사실을 notes 에 남긴다 — 값을 비우면 D010 이 조용히 미검사로 빠져
    "조용한 실패가 안전해 보이는" 쪽으로 되돌아간다.
    """
    m = _NOTIFY_RE.search(bl_item)
    if not m:
        return
    name = m.group(1).strip().rstrip(".")
    if not name:
        return
    if name.upper() == "APPLICANT":
        applicant = out.get("applicant")
        if applicant:
            out["notify_party"] = applicant
            notes.append(":46A: NOTIFY APPLICANT 를 개설의뢰인(50) 상호로 치환했습니다.")
        else:
            out["notify_party"] = name
            notes.append(
                ":46A: NOTIFY APPLICANT 인데 개설의뢰인(50)을 아직 읽지 못해 원문을 그대로 둡니다."
            )
        return
    out["notify_party"] = name


def _h_presentation(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    value = _joined(raw)
    m = re.search(r"\d+", value)
    if not m:
        notes.append(f":48: 제시기간을 해석하지 못했습니다: {value}")
        return
    out["presentation_days"] = int(m.group())


def _h_applicant(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["applicant"] = _party(raw, "50", notes)


def _h_beneficiary(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    out["beneficiary"] = _party(raw, "59", notes)


def _party(raw: str, tag: str, notes: List[str]) -> str:
    """당사자는 첫 줄(상호)만 쓴다. 계좌 줄(`/`)은 건너뛴다."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("/")]
    if len(lines) > 1:
        notes.append(f":{tag}: 주소 {len(lines) - 1}줄은 상호 대조에 쓰지 않습니다.")
    return lines[0] if lines else ""


# 47A 자유서식 중 한도 문장을 찾는 열쇠말. GROSS WEIGHT/MEASUREMENT 가 줄에
# 있어도 이 열쇠말이 없으면 "실제 값 통보"(예: 송장에 이미 적힌 실측치)일 수
# 있어 한도로 읽지 않는다 — MAXIMUM/MAX. 는 수치 앞, NOT (TO) EXCEED(ING) 는
# 수치 뒤에 오는 실무 표기다.
_LIMIT_WORD_RE = re.compile(r"\bMAX(?:IMUM)?\.?\b|\bNOT\s+(?:TO\s+)?EXCEED(?:ING)?\b", re.IGNORECASE)

# `checks.parse_quantity` 는 KG/KGS 와 MT/M.T. 만 안다(B/L 쪽 실무 표기가
# 그 정도라서). 47A 자유서식에는 "M.TON"/"METRIC TON(S)" 도 흔히 나오므로
# `parse_quantity` 에 넘기기 전에 그 표기를 MT 로 맞춰 둔다.
_MTON_ALIAS_RE = re.compile(r"\bM\.?\s?TONS?\b|\bMETRIC\s+TONS?\b", re.IGNORECASE)


def _h_47a(raw: str, out: Dict[str, object], notes: List[str]) -> None:
    """47A(추가조건)는 자유서식이다. 그중 룰이 직접 쓰는 두 한도만 뽑는다.

    나머지(신용장번호 표기 지시, 서드파티 서류 허용 등)는 해석 규칙이 없어
    그대로 버린다 — 47A 전체를 판정하려면 LLM 보조가 필요하다(기획안 v2 5.3
    R-LC-47A, 미구현). 거래조건 코드는 여기서 다루지 않는다 — `_h_incoterms`
    가 원문 태그를 따로 다시 읽는다(이유는 그쪽 주석 참고).

    수치 변환은 `checks.parse_quantity` 를 그대로 쓴다 — 콤마 천단위,
    KG/KGS ↔ M.TON 환산, CBM/M3 인식이 서류 쪽(D007/D007B)과 여기가
    갈리면 같은 표기가 한쪽에서만 읽혀 판정이 어긋난다.
    """
    for line in raw.splitlines():
        line = _BULLET_RE.sub("", line).strip()
        if not line or not _LIMIT_WORD_RE.search(line):
            continue
        upper = line.upper()
        if "GROSS WEIGHT" in upper:
            value = parse_quantity(_MTON_ALIAS_RE.sub("MT", line), "KG")
            if value is not None:
                out["max_gross_weight_kg"] = value
            else:
                notes.append(f":47A: 총중량 한도의 단위를 해석하지 못했습니다: {line}")
        elif "MEASUREMENT" in upper:
            value = parse_quantity(line, "CBM")
            if value is not None:
                out["max_measurement_cbm"] = value
            else:
                notes.append(f":47A: 용적 한도의 단위를 해석하지 못했습니다: {line}")


_HANDLERS: Dict[str, Handler] = {
    "20": _h_lc_no,
    "31D": _h_expiry,
    "32B": _h_amount,
    "39A": _h_tolerance,
    "43P": _h_partial,
    "43T": _h_transhipment,
    "44C": _h_latest_shipment,
    "44E": _h_pol,
    "44F": _h_pod,
    "45A": _h_goods,
    "46A": _h_documents,
    "47A": _h_47a,
    "48": _h_presentation,
    "50": _h_applicant,
    "59": _h_beneficiary,
}

# 자리가 없는 태그 중 **없다는 사실이 중요한 것**만 따로 설명한다.
# 47A 는 이제 자체 핸들러(`_h_47a`)가 있어 여기 실리지 않는다 — 총중량·용적
# 한도만 뽑고 나머지 자유서식(신용장번호 표기 지시 등)은 조용히 버리는데,
# 그 사실은 `_h_47a` 의 독스트링이 설명한다.
_UNMAPPED_NOTES: Dict[str, str] = {
    "44A": ":44A: 수령지는 B/L 대조 항목이 아니어서 옮기지 않았습니다.",
    "44B": ":44B: 최종목적지는 B/L 대조 항목이 아니어서 옮기지 않았습니다.",
    "71B": ":71B: 수수료 부담 조건은 검증 대상이 아닙니다.",
    "78": ":78: 지급은행 지시는 검증 대상이 아닙니다.",
}


__all__ = ["MT700Parse", "MT700ParseError", "parse_mt700", "terms_from_tags"]

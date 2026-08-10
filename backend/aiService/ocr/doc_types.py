"""
서류 종류 정의 (F1 서류 세트 확장).

기획안 5절은 입력을 "선적 **서류**"(복수)로 잡는데, 지금까지 파서는
선하증권 한 종류만 알았다. 상업송장·포장명세서를 더한다.

## 왜 명세를 데이터로 두는가

룰 카탈로그(`rules.yaml`)와 같은 이유다. 서류 종류가 늘 때마다 파서 코드를
고치는 구조면, 종류 추가가 곧 회귀 위험이 된다. 여기서는 **무엇을 뽑을지**만
선언하고, 뽑는 방법은 파서 하나가 공통으로 처리한다.

## 선하증권만 좌표를 쓰는 이유

`field_parser.FieldParser.REGIONS` 는 1654×2340 라벨 데이터셋 **실측으로
교정된** 좌표다. 상업송장·포장명세서에는 그런 교정 데이터가 없다.

없는 좌표를 지어내면 안 된다 — 임의로 찍은 구역은 맞을 때보다 틀릴 때가
많고, 틀려도 값이 나오므로 조용히 잘못된 추출이 된다. 그래서 새 서류
종류는 **앵커(항목명 근접)만** 쓴다. 정확도는 낮지만 어디서 왔는지가
분명하고, 앵커 추출은 이미 신뢰도를 감점해 사람 확인을 유도한다
(`ANCHOR_CONFIDENCE_PENALTY`).

실물 샘플이 확보되면 그때 좌표를 교정해 넣으면 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# 서류 종류 이름. 라벨 JSON 의 `Images.form_type` 과 같은 표기를 쓴다.
BILL_OF_LADING = "선하증권"
COMMERCIAL_INVOICE = "상업송장"
PACKING_LIST = "포장명세서"
UNKNOWN = "미상"


@dataclass(frozen=True)
class DocumentSpec:
    """서류 한 종류의 추출 명세."""

    name: str
    # 서식 제목에 나타나는 문구. 종류 판별에 쓴다.
    title_keywords: Tuple[str, ...]
    # 뽑을 필드. 순서는 화면 표시 순서다.
    fields: Tuple[str, ...]
    # 필드별 항목명 후보. 앵커 추출이 이걸 찾아 그 오른쪽/아래를 읽는다.
    anchors: Dict[str, List[str]]
    # 화면에 쓸 한국어 라벨.
    labels: Dict[str, str]
    # 비면 검증이 성립하지 않는 필드.
    critical: Tuple[str, ...]

    def label_for(self, field: str) -> str:
        return self.labels.get(field, field)


# ── 상업송장 ─────────────────────────────────────────────────────
#
# 필드 선택 기준은 **서류 간 정합성 대조에 쓰이는 것**이다. 송장에만 있고
# 다른 서류와 대조할 일이 없는 항목(결제 조건, 은행 정보 등)은 넣지 않았다.
# 지금 뽑아 봐야 확인 대기열만 늘리고 쓰이지 않는다.
_INVOICE = DocumentSpec(
    name=COMMERCIAL_INVOICE,
    title_keywords=("COMMERCIAL INVOICE", "INVOICE", "상업송장", "송장"),
    fields=(
        "invoice_no",
        "invoice_date",
        "seller",
        "buyer",
        "description_of_goods",
        "quantity",
        "total_amount",
        "incoterms",
        "lc_no",
    ),
    anchors={
        "invoice_no": ["INVOICE NO", "INVOICE NUMBER", "INV NO", "COMMERCIAL INVOICE NO"],
        "invoice_date": ["INVOICE DATE", "DATE OF INVOICE", "ISSUE DATE", "DATED"],
        "seller": ["SELLER", "SHIPPER", "EXPORTER", "MESSRS", "FROM"],
        "buyer": ["BUYER", "CONSIGNEE", "MESSRS", "TO", "IMPORTER", "APPLICANT"],
        "description_of_goods": [
            "DESCRIPTION OF GOODS", "DESCRIPTION", "COMMODITY", "GOODS",
        ],
        "quantity": ["QUANTITY", "QTY", "TOTAL QUANTITY"],
        "total_amount": ["TOTAL AMOUNT", "TOTAL", "AMOUNT", "GRAND TOTAL", "SAY TOTAL"],
        "incoterms": ["PRICE TERM", "TERMS OF PRICE", "TRADE TERM", "DELIVERY TERM"],
        "lc_no": ["L/C NO", "LC NO", "CREDIT NO", "LETTER OF CREDIT NO"],
    },
    labels={
        "invoice_no": "송장 번호",
        "invoice_date": "송장 발행일",
        "seller": "매도인",
        "buyer": "매수인",
        "description_of_goods": "물품 명세",
        "quantity": "수량",
        "total_amount": "총 금액",
        "incoterms": "가격 조건",
        "lc_no": "신용장 번호",
    },
    critical=("invoice_no", "buyer", "description_of_goods", "total_amount"),
)


# ── 포장명세서 ───────────────────────────────────────────────────
_PACKING_LIST = DocumentSpec(
    name=PACKING_LIST,
    title_keywords=("PACKING LIST", "PACKING SPECIFICATION", "포장명세서", "포장 명세서"),
    fields=(
        "invoice_no",
        "packing_date",
        "seller",
        "buyer",
        "description_of_goods",
        "package_count",
        "gross_weight",
        "net_weight",
        "measurement",
        "marks",
    ),
    anchors={
        "invoice_no": ["INVOICE NO", "INVOICE NUMBER", "INV NO"],
        "packing_date": ["DATE", "PACKING DATE", "ISSUE DATE", "DATED"],
        "seller": ["SELLER", "SHIPPER", "EXPORTER", "FROM"],
        "buyer": ["BUYER", "CONSIGNEE", "TO", "IMPORTER"],
        "description_of_goods": [
            "DESCRIPTION OF GOODS", "DESCRIPTION", "COMMODITY", "GOODS",
        ],
        "package_count": [
            "NUMBER OF PACKAGES", "TOTAL PACKAGES", "PACKAGES", "NO OF PKGS", "CTNS",
        ],
        "gross_weight": ["GROSS WEIGHT", "G/W", "TOTAL GROSS WEIGHT"],
        "net_weight": ["NET WEIGHT", "N/W", "TOTAL NET WEIGHT"],
        "measurement": ["MEASUREMENT", "CBM", "TOTAL MEASUREMENT", "VOLUME"],
        "marks": ["MARKS AND NUMBERS", "SHIPPING MARKS", "MARKS"],
    },
    labels={
        "invoice_no": "송장 번호",
        "packing_date": "작성일",
        "seller": "매도인",
        "buyer": "매수인",
        "description_of_goods": "물품 명세",
        "package_count": "포장 수량",
        "gross_weight": "총 중량",
        "net_weight": "순 중량",
        "measurement": "용적",
        "marks": "화인",
    },
    critical=("invoice_no", "buyer", "package_count", "gross_weight"),
)


SPECS: Dict[str, DocumentSpec] = {
    COMMERCIAL_INVOICE: _INVOICE,
    PACKING_LIST: _PACKING_LIST,
}

# 선하증권은 좌표 교정본이 있어 전용 파서(`FieldParser`)를 쓴다.
# 여기 SPECS 에 넣지 않는 이유가 그것이다 — 넣으면 앵커 전용 경로로
# 처리되어 교정된 좌표를 버리게 된다.
SUPPORTED_TYPES = (BILL_OF_LADING, COMMERCIAL_INVOICE, PACKING_LIST)


def spec_for(form_type: str) -> Optional[DocumentSpec]:
    """서류 종류 → 명세. 선하증권과 미상은 None."""
    return SPECS.get(form_type)


def detect(text: str) -> str:
    """서식 제목으로 서류 종류를 판별한다.

    **판별하지 못하면 선하증권으로 넘겨짚지 않는다.** `미상` 을 돌려준다.
    기본값을 선하증권으로 두면 송장을 올렸을 때 B/L 구역 좌표로 파싱되어
    엉뚱한 값이 나오는데, 그 결과는 오류가 아니라 그럴듯한 값이라 조용하다.

    상단부터 본다. 서식 제목은 지면 위쪽에 있고, 본문에는 다른 서류 이름이
    참조로 등장하기 때문이다 — 선하증권 본문의 "COMMERCIAL INVOICE" 는
    요구 서류 목록의 한 줄이지 이 서류의 제목이 아니다.
    """
    head = _normalize("\n".join(text.splitlines()[:_TITLE_SCAN_LINES]))
    if not head:
        return UNKNOWN

    # 긴 문구를 먼저 본다. "COMMERCIAL INVOICE" 가 "INVOICE" 보다 구체적이고,
    # "PACKING LIST" 는 "LIST" 같은 조각에 밀리면 안 된다.
    matches = [
        (len(kw), name)
        for name, keywords in _DETECT_KEYWORDS.items()
        for kw in keywords
        if _normalize(kw) in head
    ]
    if not matches:
        return UNKNOWN
    return max(matches)[1]


# 제목을 찾을 상단 줄 수.
_TITLE_SCAN_LINES = 12

_DETECT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    BILL_OF_LADING: (
        "BILL OF LADING", "MULTIMODAL TRANSPORT", "SEA WAYBILL",
        "COMBINED TRANSPORT", "선하증권",
    ),
    COMMERCIAL_INVOICE: _INVOICE.title_keywords,
    PACKING_LIST: _PACKING_LIST.title_keywords,
}


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9가-힣 ]", " ", text.upper())

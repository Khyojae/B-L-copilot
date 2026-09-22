"""F5 정정 영향분석 — 그래프가 답하지 못하는 부분: 누가 고치고, 어떤 절차로.

aiService `/impact` 는 룰 카탈로그에서 "이 필드를 고치면 함께 확인할 (서류,
필드)"를 뽑는다. 그 그래프는 **선적 상태를 모른다** — 같은 선적항 정정이라도
초안이면 다시 쓰면 되고, 은행에 제출된 뒤면 조건 변경(amendment)과 B/L
재발행까지 간다(프론트 mocks/shipmentData.ts S8 주석, 기획안 5.5). 상태는
DB 에 있으므로 그 판단은 여기서 한다.

여기 있는 규칙은 전부 **입력이 이미 갖고 있는 정보에서만** 나온다 — 영향받는
서류 종류, 편집한 서류 종류, 선적 상태, 간선 룰의 심각도. 값(무엇을 무엇으로
고쳤는지)은 보지 않는다. 그래서 낼 수 없는 답도 있다:

- `ENDORSEMENT`(배서)·`SWITCH_BL`(스위치 B/L)은 내지 않는다. 배서는 지시식
  B/L 의 권리 이전이지 기재 정정이 아니고, 스위치 B/L 은 삼각무역 여부라는
  선적에 없는 정보가 있어야 고를 수 있다. 발행 후 B/L 기재 정정은 전부
  `REISSUE` 로 낸다 — 모르는 것을 그럴듯하게 고르지 않는다.
- `requires_amendment` 는 "제출 후 + 신용장 조건과 묶인 필드"일 때만 True 다.
  값이 실제로 신용장과 어긋나는지는 F3 재검증이 답할 일이다.
"""

from __future__ import annotations

from typing import Literal

from smart_e_bl.mapping import (
    AI_DOC_BILL_OF_LADING,
    AI_DOC_COMMERCIAL_INVOICE,
    AI_DOC_LC,
    AI_DOC_PACKING_LIST,
)
from smart_e_bl.models.enums import ShipmentStatus

Party = Literal["화주", "포워더", "선사", "은행", "관세사"]
ReissuePath = Literal["DRAFT_EDIT", "ENDORSEMENT", "REISSUE", "SWITCH_BL"]

# 영향받는 서류를 누가 고치는가 — 서류의 발행 주체다.
# 신용장은 개설은행만 조건을 바꿀 수 있고(amendment), B/L 은 운송인이 발행하며,
# 송장·포장명세서는 매도인(화주)이 작성한다. 포워더·관세사는 이 그래프의
# 서류(정합성 룰이 다루는 4종)를 발행하지 않아 여기 없다 — F6 통관 서류가
# 붙으면 관세사가 들어올 자리다.
PARTY_BY_AI_DOC: dict[str, Party] = {
    AI_DOC_LC: "은행",
    AI_DOC_BILL_OF_LADING: "선사",
    AI_DOC_COMMERCIAL_INVOICE: "화주",
    AI_DOC_PACKING_LIST: "화주",
}

# B/L 이 이미 발행된 상태. 은행 제출(SUBMITTED)은 발행된 B/L 을 제시하는
# 행위이므로 그 이후 상태는 전부 발행 후다.
BL_ISSUED_STATUSES: frozenset[ShipmentStatus] = frozenset(
    {ShipmentStatus.SUBMITTED, ShipmentStatus.MONITORING, ShipmentStatus.CLOSED}
)

# aiService 룰 심각도(소문자) → 프론트 domain.ts Severity 리터럴.
AI_SEVERITY_TO_FRONTEND: dict[str, str] = {
    "critical": "Critical",
    "warning": "Warning",
    "info": "Info",
}


def party_for(ai_doc: str) -> Party:
    return PARTY_BY_AI_DOC[ai_doc]


def reissue_path_for(status: ShipmentStatus, edited_ai_doc: str) -> ReissuePath:
    """편집한 서류가 발행된 B/L 이면 재발행, 아니면 초안 수정.

    송장·포장명세서를 제출 후에 고치는 것도 다시 제시해야 하지만, 그것은
    B/L 재발행 경로가 아니다 — `reissue_path` 는 B/L 에 대한 답이다.
    """
    if edited_ai_doc == AI_DOC_BILL_OF_LADING and status in BL_ISSUED_STATUSES:
        return "REISSUE"
    return "DRAFT_EDIT"


def requires_amendment_for(status: ShipmentStatus, impacted_ai_docs: list[str]) -> bool:
    """제출 후에 신용장 조건과 묶인 필드를 고치면 조건 변경이 따라온다."""
    return status in BL_ISSUED_STATUSES and AI_DOC_LC in impacted_ai_docs


__all__ = [
    "AI_SEVERITY_TO_FRONTEND",
    "BL_ISSUED_STATUSES",
    "PARTY_BY_AI_DOC",
    "Party",
    "ReissuePath",
    "party_for",
    "reissue_path_for",
    "requires_amendment_for",
]

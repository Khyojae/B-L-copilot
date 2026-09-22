"""DB 에 저장된 선적 한 건을 aiService `/report`(= `/verify` + submitted_documents)
요청 본문으로 옮긴다.

순수 함수로 둔 이유: 라우트 테스트는 Postgres 가 있어야 돌지만(conftest.py
머리말), 필드 코드 변환·서류 분류·신뢰도 전달 같은 조립 규칙은 DB 없이도
검증할 수 있어야 한다.
"""

from __future__ import annotations

from typing import Any

from smart_e_bl.mapping import (
    AI_DOC_BILL_OF_LADING,
    AI_DOC_LC,
    DB_DOC_TYPE_TO_AI,
    DB_DOC_TYPE_TO_SUBMITTED_NAME,
    field_code_to_ai_name,
)
from smart_e_bl.models import FieldValue, Shipment
from smart_e_bl.models.enums import DocumentType


def build_report_payload(
    shipment: Shipment,
    rows: list[tuple[DocumentType, FieldValue]],
    *,
    submitted_types: list[DocumentType],
) -> dict[str, Any]:
    """`rows` 는 (그 값이 나온 서류 종류, 필드값). 반환은 aiService ReportRequest 와 같은 dict.

    - 값은 `normalized_value` 가 있으면 그것, 없으면 `value`. 룰엔진이 문자열
      동일성으로 대조하므로 F2 교정본이 있으면 그쪽이 맞다.
    - 같은 (서류, 필드)에 행이 여럿이면 대표값(`is_representative`)이 이긴다.
      후보는 5.1 원칙대로 버리지 않고 저장돼 있을 뿐, 검증 입력은 아니다.
    - `field_confidence` 는 선하증권 필드만 보낸다. aiService 의 판정 보류
      게이트(기획안 v2 5.3)가 bl 필드만 대상으로 하기 때문이다.
    - 신용장은 서류 필드에 더해 선적 헤더의 `lc_no` · `lc_expiry_date` 를
      합친다. 만기일은 제시기간 계산의 입력이라 서류 없이도 의미가 있다.
    """
    by_doc: dict[str, dict[str, FieldValue]] = {}
    for doc_type, fv in rows:
        ai_doc = DB_DOC_TYPE_TO_AI.get(doc_type)
        if ai_doc is None:
            continue
        name = field_code_to_ai_name(fv.field_code)
        if name is None:
            continue
        bucket = by_doc.setdefault(ai_doc, {})
        current = bucket.get(name)
        if current is None or (fv.is_representative and not current.is_representative):
            bucket[name] = fv

    def values(doc: str) -> dict[str, str | None]:
        return {name: fv.normalized_value or fv.value for name, fv in by_doc.get(doc, {}).items()}

    bl = values(AI_DOC_BILL_OF_LADING)
    payload: dict[str, Any] = {"bl": bl}

    confidence = {
        name: float(fv.confidence)
        for name, fv in by_doc.get(AI_DOC_BILL_OF_LADING, {}).items()
        if fv.confidence is not None
    }
    if confidence:
        payload["field_confidence"] = confidence

    lc: dict[str, Any] = {k: v for k, v in values(AI_DOC_LC).items() if v}
    if shipment.lc_no and "lc_no" not in lc:
        lc["lc_no"] = shipment.lc_no
    if shipment.lc_expiry_date and "expiry_date" not in lc:
        lc["expiry_date"] = shipment.lc_expiry_date.isoformat()
    if lc:
        payload["lc"] = lc

    documents = {
        doc: values(doc)
        for doc in by_doc
        if doc not in (AI_DOC_BILL_OF_LADING, AI_DOC_LC)
    }
    if documents:
        payload["documents"] = documents

    submitted = sorted(
        {
            DB_DOC_TYPE_TO_SUBMITTED_NAME[t]
            for t in submitted_types
            if t in DB_DOC_TYPE_TO_SUBMITTED_NAME
        }
    )
    if submitted:
        payload["submitted_documents"] = submitted

    return payload


__all__ = ["build_report_payload"]

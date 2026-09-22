"""근거 강제(migrations/sql/evidence/10) 테스트 공용 도우미.

트리거 내부 함수를 직접 부르지 않고 field_value 에 INSERT 하고 SELECT 로
판정만 읽는다 — 실험기(A6)와 같은 계약이다. "저장소가 막았다"는 주장은
이 수준에서 성립해야 한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from smart_e_bl.models import AppUser, Document, Shipment
from smart_e_bl.models.enums import DocumentSource, DocumentType

# 한 페이지짜리 선하증권 토큰. (text, x1, y1, x2, y2). idx 는 나열 순서.
# 실제 OCR 이 내는 모양을 흉내 낸다 — 이름표와 값이 섞여 있고, 값이 여러 토큰으로 갈라진다.
SAMPLE_TOKENS: list[tuple[str, float, float, float, float]] = [
    ("B/L", 0.05, 0.05, 0.08, 0.07),              # 0
    ("NO.", 0.09, 0.05, 0.12, 0.07),              # 1
    ("HLCUBEN2100123456", 0.13, 0.05, 0.30, 0.07),  # 2
    ("PORT", 0.05, 0.10, 0.09, 0.12),             # 3
    ("OF", 0.10, 0.10, 0.12, 0.12),               # 4
    ("LOADING", 0.13, 0.10, 0.20, 0.12),          # 5
    ("BUSAN,", 0.05, 0.13, 0.11, 0.15),           # 6
    ("KOREA", 0.12, 0.13, 0.18, 0.15),            # 7
    ("DATE", 0.05, 0.20, 0.09, 0.22),             # 8
    ("OF", 0.10, 0.20, 0.12, 0.22),               # 9
    ("ISSUE", 0.13, 0.20, 0.18, 0.22),            # 10
    ("12", 0.05, 0.23, 0.07, 0.25),               # 11
    ("AUG", 0.08, 0.23, 0.11, 0.25),              # 12
    ("2026", 0.12, 0.23, 0.16, 0.25),             # 13
    ("GROSS", 0.05, 0.30, 0.10, 0.32),            # 14
    ("WEIGHT", 0.11, 0.30, 0.17, 0.32),           # 15
    ("1,234.50", 0.05, 0.33, 0.12, 0.35),         # 16
    ("KGS", 0.13, 0.33, 0.16, 0.35),              # 17
    ("SHIPPER", 0.55, 0.05, 0.62, 0.07),          # 18
    ("HAPAG", 0.55, 0.08, 0.60, 0.10),            # 19
    ("LLOYD", 0.61, 0.08, 0.66, 0.10),            # 20
    ("AG", 0.67, 0.08, 0.69, 0.10),               # 21
    ("CONTAINER", 0.55, 0.20, 0.64, 0.22),        # 22
    ("MSKU1234567", 0.55, 0.23, 0.66, 0.25),      # 23
]


@dataclass
class EvidenceDoc:
    tenant_id: uuid.UUID
    shipment_id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID


async def make_evidence_doc(
    session: AsyncSession, user: AppUser, *, tokens: bool = True
) -> EvidenceDoc:
    """선적 + 서류 + (선택) 토큰 계층을 만든다."""
    shipment = Shipment(tenant_id=user.tenant_id, created_by=user.id)
    session.add(shipment)
    await session.flush()
    document = Document(
        tenant_id=user.tenant_id,
        shipment_id=shipment.id,
        doc_type=DocumentType.BL_COPY,
        source=DocumentSource.UPLOAD,
        file_hash=f"hash-{uuid.uuid4().hex[:8]}",
        page_count=1,
        uploaded_by=user.id,
    )
    session.add(document)
    await session.flush()
    doc = EvidenceDoc(
        tenant_id=user.tenant_id,
        shipment_id=shipment.id,
        document_id=document.id,
        user_id=user.id,
    )
    if tokens:
        await load_tokens(session, doc.document_id, SAMPLE_TOKENS)
    return doc


async def load_tokens(
    session: AsyncSession,
    document_id: uuid.UUID,
    tokens: list[tuple[str, float, float, float, float]],
    page: int = 1,
) -> None:
    for idx, (txt, x1, y1, x2, y2) in enumerate(tokens):
        await session.execute(
            text(
                """
                INSERT INTO document_token
                  (document_id, page, idx, text, bbox_x1, bbox_y1, bbox_x2, bbox_y2, ocr_confidence)
                VALUES (:doc, :page, :idx, :txt, :x1, :y1, :x2, :y2, 0.95)
                """
            ),
            {"doc": document_id, "page": page, "idx": idx, "txt": txt,
             "x1": x1, "y1": y1, "x2": x2, "y2": y2},
        )


async def set_mode(session: AsyncSession, mode: str) -> None:
    await session.execute(text("SELECT set_evidence_mode(CAST(:m AS evidence_mode))"), {"m": mode})


async def set_threshold(session: AsyncSession, theta: float) -> None:
    await session.execute(text("SELECT set_evidence_reattach_threshold(:t)"), {"t": theta})


async def insert_value(
    session: AsyncSession,
    doc: EvidenceDoc,
    *,
    field_code: str,
    value: str | None,
    span: tuple[int, int] | None = None,
    page: int | None = 1,
    bbox: tuple[float, float, float, float] | None = None,
    extractor: str = "OCR_LLM",
    grade: str = "CONFIRMED",
    source_layer: str | None = "REGION",
    edited_by: uuid.UUID | None = None,
    is_representative: bool = True,
    document_id: uuid.UUID | None = "__doc__",  # type: ignore[assignment]
    **overrides: Any,
) -> dict[str, Any]:
    """field_value 한 행을 넣고 트리거 판정을 읽어 돌려준다."""
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant": doc.tenant_id,
        "shipment": doc.shipment_id,
        "doc": doc.document_id if document_id == "__doc__" else document_id,
        "field": field_code,
        "page": page,
        "value": value,
        "extractor": extractor,
        "grade": grade,
        "layer": source_layer,
        "from": span[0] if span else None,
        "to": span[1] if span else None,
        "x1": bbox[0] if bbox else None,
        "y1": bbox[1] if bbox else None,
        "x2": bbox[2] if bbox else None,
        "y2": bbox[3] if bbox else None,
        "edited_by": edited_by,
        "rep": is_representative,
        # 쓰기 경로가 판정을 주장해도 트리거가 덮어쓰는지 확인하기 위해 넣을 수 있다
        "status": overrides.get("evidence_status"),
    }
    await session.execute(
        text(
            """
            INSERT INTO field_value
              (id, tenant_id, shipment_id, field_code, document_id, page,
               bbox_x1, bbox_y1, bbox_x2, bbox_y2,
               value, grade, extractor, is_representative, source_layer,
               evidence_token_from, evidence_token_to, edited_by, evidence_status)
            VALUES
              (:id, :tenant, :shipment, :field, :doc, :page,
               :x1, :y1, :x2, :y2,
               :value, CAST(:grade AS confidence_grade), CAST(:extractor AS extractor_kind),
               :rep, :layer, :from, :to, :edited_by, CAST(:status AS evidence_status))
            """
        ),
        params,
    )
    return await read_value(session, params["id"])


async def read_value(session: AsyncSession, field_value_id: uuid.UUID) -> dict[str, Any]:
    row = await session.execute(
        text(
            """
            SELECT id, value, grade, extractor, is_representative, page,
                   bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                   evidence_token_from, evidence_token_to,
                   derivation, evidence_status, evidence_mode, evidence_reason,
                   (SELECT count(*) FROM field_value_trusted t WHERE t.id = fv.id) AS in_trusted,
                   (SELECT count(*) FROM field_value_review_queue q WHERE q.id = fv.id) AS in_review_queue
            FROM field_value fv WHERE id = :id
            """
        ),
        {"id": field_value_id},
    )
    m = row.mappings().one()
    out = dict(m)
    for k in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2"):
        if isinstance(out[k], Decimal):
            out[k] = float(out[k])
    return out


async def seed_glossary(session: AsyncSession) -> None:
    """GLOSSARY 파생 테스트용 표준 용어 두 건. normalized_key 는 evidence_norm() 으로 만든다."""
    await session.execute(
        text(
            """
            WITH t AS (
              INSERT INTO glossary_term
                (term_code, canonical, category, lang, authority, scope, version, effective_date)
              VALUES
                ('KRPUS', 'KRPUS (Busan)', 'port', 'en', 'UNLOCODE', 'STANDARD', 'test', '2026-01-01'),
                ('KGM',   'KGM',           'unit', 'en', 'UNECE_REC20', 'STANDARD', 'test', '2026-01-01')
              RETURNING id, term_code
            ), a(term_code, alias) AS (
              VALUES ('KRPUS', 'KRPUS'), ('KRPUS', 'BUSAN'), ('KRPUS', 'PUSAN'), ('KRPUS', 'BUSAN, KOREA'),
                     ('KGM', 'KGM'), ('KGM', 'KGS'), ('KGM', 'KILOGRAMS')
            )
            INSERT INTO glossary_alias (term_id, alias_text, normalized_key)
            SELECT t.id, a.alias, evidence_norm(a.alias) FROM t JOIN a USING (term_code)
            """
        )
    )

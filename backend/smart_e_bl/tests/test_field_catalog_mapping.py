"""mapping.DB_FIELD_CODE_TO_AI 와 SQL 카탈로그(field_definition 시드)의 정합.

두 곳이 어긋나는 방향은 둘이고 둘 다 조용히 망가진다:
  - 표에는 있는데 시드에 없는 코드 → 워커가 FK 위반으로 잡을 죽인다
  - 시드에는 있는데 표에 없는 코드 → 워커가 그 값을 버린다(추출됐는데 초안이 빔)
DB 없이 SQL 파일을 정규식으로 읽어 대조한다. 스키마 도구가 아니라 시드의
INSERT 문에 나오는 ('CODE', 'DOC_TYPE') 쌍만 뽑는 정도라, 시드 형식이
바뀌면 이 테스트도 같이 손봐야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from smart_e_bl.mapping import DB_DOC_TYPE_TO_AI, DB_FIELD_CODE_TO_AI
from smart_e_bl.models.enums import DocumentType

_SQL_DIR = Path(__file__).resolve().parents[1] / "migrations" / "sql"
_SEED_FILES = (
    _SQL_DIR / "09_seed_catalog.sql",
    _SQL_DIR / "catalog" / "11_invoice_packing_fields.sql",
)
_ROW = re.compile(r"\(\s*'([A-Z]+\.[A-Z0-9_]+)'\s*,\s*'([A-Z_0-9]+)'")


def _seeded_codes() -> dict[str, DocumentType]:
    codes: dict[str, DocumentType] = {}
    for path in _SEED_FILES:
        for code, doc_type in _ROW.findall(path.read_text(encoding="utf-8")):
            codes[code] = DocumentType(doc_type)
    return codes


def test_시드_파일을_읽을_수_있다():
    codes = _seeded_codes()
    assert "BL.BL_NO" in codes and "INV.INVOICE_NO" in codes and "PL.MARKS" in codes


def test_매핑_표의_모든_코드는_시드에_있다():
    seeded = _seeded_codes()
    missing = sorted(code for code in DB_FIELD_CODE_TO_AI if code not in seeded)
    assert missing == [], f"시드에 없는 코드(워커가 FK 위반을 낸다): {missing}"


def test_매핑_표의_서류_종류는_시드의_doc_type과_같다():
    seeded = _seeded_codes()
    wrong = {
        code: (DB_DOC_TYPE_TO_AI[seeded[code]], ai_doc)
        for code, (ai_doc, _) in DB_FIELD_CODE_TO_AI.items()
        if DB_DOC_TYPE_TO_AI.get(seeded[code]) != ai_doc
    }
    assert wrong == {}, f"코드의 서류 종류가 시드와 다름 {{code: (시드, 표)}}: {wrong}"


def test_시드의_상업송장_포장명세서_코드는_전부_표에_있다():
    """두 서류는 aiService 가 뽑는 필드와 시드 코드를 1:1 로 맞춰 두었다.
    선하증권은 시드가 더 넓어(컨테이너·봉인 등 aiService 가 안 뽑는 필드) 대상이 아니다."""
    seeded = _seeded_codes()
    unmapped = sorted(
        code
        for code, doc_type in seeded.items()
        if doc_type in (DocumentType.COMMERCIAL_INVOICE, DocumentType.PACKING_LIST)
        and code not in DB_FIELD_CODE_TO_AI
    )
    assert unmapped == ["INV.UNIT_PRICE"], (
        f"표에 없어 워커가 버리는 코드: {unmapped} (INV.UNIT_PRICE 는 aiService 가 뽑지 않아 예외)"
    )

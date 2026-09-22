"""표준 용어사전 적재 — E3 의 전제조건 (작업분배 B2 · 계획서 §4.4).

GLOSSARY 파생은 트리거가 DB 안의 glossary_alias 를 조회해야 성립한다. 용어사전이
코드나 설정 파일에만 있으면 트리거가 볼 수 없고, 그 상태로 측정하면 E3 = E2 가
된다(정직성 규약). 이 스크립트는 aiService 의 표준 카탈로그
(backend/aiService/terms/catalogs/<version>/*.yaml — UN/LOCODE · UN/ECE Rec 20 ·
ISO 6346 · Incoterms · HS 등)를 glossary_term / glossary_alias 로 옮긴다.

  uv run python scripts/load_evidence_glossary.py            # std-2026.1
  uv run python scripts/load_evidence_glossary.py --version std-2026.1 --catalog-dir ../aiService/terms/catalogs

normalized_key 는 DB 의 evidence_norm() 으로 계산한다 — 트리거가 값을 정규화하는
함수와 같아야 별칭 조회가 맞는다. 같은 (term_code, category, version) 은 갱신하고,
별칭은 지웠다 다시 넣는다(멱등). 실험 결과를 본 뒤에는 카탈로그를 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from smart_e_bl.config import settings  # noqa: E402

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parents[2] / "aiService" / "terms" / "catalogs"

# 카탈로그 category → glossary_term_category_ck
CATEGORY_MAP = {
    "port": "port",
    "qty_unit": "unit",
    "volume_unit": "unit",
    "container_no": "container",
    "party_suffix": "party",
    "price_term": "incoterms",
    "delivery": "incoterms",
    "hs_code": "hs",
    "practice_phrase": "phrase",
    "transport_doc": "document_term",
}


def map_authority(raw: str) -> str:
    """카탈로그 authority 문자열 → glossary_authority 열거형."""
    s = raw.upper()
    if "LOCODE" in s:
        return "UNLOCODE"
    if "REC 20" in s or "REC20" in s:
        return "UNECE_REC20"
    if "6346" in s:
        return "ISO6346"
    if "INCOTERMS" in s:
        return "INCOTERMS_2020"
    if s.startswith("HS"):
        return "HS"
    if "ISBP" in s:
        return "ISBP"
    if "UCP" in s:
        return "UCP600"
    if "DCSA" in s:
        return "DCSA"
    # '업계 관행', '상호 표기 정규화 규칙' — 표준 기관이 없는 관행 항목. 열거형에
    # 대응 값이 없어 ORGANIZATION 으로 둔다(테넌트 사전이라는 뜻은 아니다).
    return "ORGANIZATION"


def iter_terms(catalog_dir: Path, version: str):
    base = catalog_dir / version
    manifest = yaml.safe_load((base / "manifest.yaml").read_text(encoding="utf-8"))
    for name in manifest["files"]:
        data = yaml.safe_load((base / name).read_text(encoding="utf-8"))
        for t in data["terms"]:
            yield t


def load(conn: psycopg.Connection, catalog_dir: Path, version: str) -> tuple[int, int]:
    n_terms = n_aliases = 0
    with conn.cursor() as cur:
        for t in iter_terms(catalog_dir, version):
            category = CATEGORY_MAP.get(t["category"])
            if category is None:
                raise SystemExit(f"알 수 없는 category {t['category']!r}: {t['term_id']}")
            lang = t.get("lang", "en")
            if lang not in ("ko", "en"):
                lang = "en"  # 'code' — 열거형 CHECK(ko|en)
            cur.execute(
                """
                INSERT INTO glossary_term
                  (term_code, canonical, category, lang, authority, scope, version, effective_date, is_active)
                VALUES (%s, %s, %s, %s, %s, 'STANDARD', %s, %s, true)
                ON CONFLICT (term_code, category, version) WHERE scope = 'STANDARD'
                DO UPDATE SET canonical = EXCLUDED.canonical, lang = EXCLUDED.lang,
                              authority = EXCLUDED.authority, effective_date = EXCLUDED.effective_date,
                              is_active = true
                RETURNING id
                """,
                (
                    t["term_id"], t["canonical"], category, lang, map_authority(t["authority"]),
                    str(t.get("version", version)), str(t["effective_date"]),
                ),
            )
            term_id = cur.fetchone()[0]
            n_terms += 1

            # 별칭: 카탈로그 aliases + canonical · display · bl_form · term_id 꼬리(코드).
            # 값이 코드(KRPUS)로 오고 원문이 B/L 표기(BUSAN)인 경우와 그 반대를 모두 잇는다.
            aliases = {t["canonical"], t["term_id"].split(".", 1)[-1]}
            aliases.update(t.get("aliases") or [])
            for k in ("display", "bl_form"):
                if t.get(k):
                    aliases.add(t[k])

            cur.execute("DELETE FROM glossary_alias WHERE term_id = %s", (term_id,))
            for alias in sorted(a for a in aliases if a):
                cur.execute(
                    """
                    INSERT INTO glossary_alias (term_id, alias_text, normalized_key)
                    SELECT %s, %s, evidence_norm(%s)
                    WHERE evidence_norm(%s) <> ''
                    ON CONFLICT (term_id, normalized_key) DO NOTHING
                    """,
                    (term_id, alias, alias, alias),
                )
                n_aliases += cur.rowcount
    return n_terms, n_aliases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--version", default="std-2026.1")
    ap.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    args = ap.parse_args()

    # settings.sync_database_url 은 SQLAlchemy 드라이버 접두사(postgresql+psycopg)가 붙어 있다
    dsn = settings.sync_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn:
        n_terms, n_aliases = load(conn, args.catalog_dir, args.version)
        conn.commit()
    print(f"glossary {args.version}: terms={n_terms} aliases={n_aliases}")


if __name__ == "__main__":
    main()

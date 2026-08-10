"""FastAPI 계층 테스트 — F1/F3/F4 엔드포인트 계약."""

from __future__ import annotations

import pytest
from conftest import complete_bl_bboxes

fastapi = pytest.importorskip("fastapi", reason="FastAPI 미설치 시 건너뜀")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


CLEAN_BL = {
    "bl_no": "HG290309",
    "shipper": "GAE WOON CO., LTD.",
    "consignee": "DHHJ FRANCHISING CO., LTD.",
    "notify_party": "TRY ENERGY CO., LTD.",
    "vessel": "MSC BIANCA",
    "port_of_loading": "BUSAN, KOREA",
    "port_of_discharge": "TOKYO, JAPAN",
    "description_of_goods": "SAW MACHINE",
    "gross_weight": "884 KG",
    "date_of_issue": "2026-06-01",
    "on_board_date": "2026-06-01",
    "total_freight": "$1,741.56",
}

CLEAN_LC = {
    "lc_no": "LC-2026-001",
    "port_of_loading": "PUSAN",
    "port_of_discharge": "TOKYO",
    "consignee": "DHHJ FRANCHISING CO., LTD.",
    "description_of_goods": "SAW MACHINE",
    "latest_shipment_date": "2026-06-30",
    "expiry_date": "2026-12-31",
    "max_gross_weight_kg": 1000.0,
    "freight_amount": 1741.56,
}

AS_OF = "2026-06-10T00:00:00"


class TestHealth:
    def test_룰_적재_수를_보고한다(self, client):
        body = client.get("/health").json()

        assert body["status"] == "ok"
        assert body["rules_loaded"] >= 20

    def test_룰_목록에_조문이_실린다(self, client):
        body = client.get("/rules").json()

        assert body["count"] == len(body["rules"])
        assert all(r["source"] for r in body["rules"])


class TestExtract:
    def test_라벨_JSON으로_초안을_만든다(self, client):
        payload = {
            "Images": {"identifier": "API_TEST", "width": 1654, "height": 2340},
            "bbox": complete_bl_bboxes(),
        }

        body = client.post("/extract/label", json=payload).json()

        assert body["image_id"] == "API_TEST"
        assert body["is_ready_for_verification"] is True
        names = {f["name"]: f["value"] for f in body["fields"]}
        assert names["bl_no"] == "HG290309"

    def test_bbox가_비면_400이다(self, client):
        response = client.post("/extract/label", json={"Images": {}, "bbox": []})

        assert response.status_code == 400

    def test_빈_파일_업로드는_400이다(self, client):
        response = client.post(
            "/extract", files={"file": ("empty.png", b"", "image/png")}
        )

        assert response.status_code == 400

    def test_OCR_엔진_미설치는_503이다(self, client):
        # 서버 구성 문제지 요청 오류가 아니다. 500 으로 흘리면
        # 게이트웨이가 무의미하게 재시도한다.
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            pass
        else:
            pytest.skip("PaddleOCR 설치됨 — 미설치 경로를 검사할 수 없음")

        response = client.post(
            "/extract", files={"file": ("x.png", b"\x89PNG fake", "image/png")}
        )

        assert response.status_code == 503
        # 무엇을 설치해야 하는지 응답에 담긴다.
        assert "pip install" in response.json()["detail"]


class TestVerify:
    def test_정상_서류는_위반이_없다(self, client):
        response = client.post(
            "/verify", json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        )
        verdict = response.json()["verdict"]

        assert response.status_code == 200
        assert verdict["counts"]["critical"] == 0
        assert verdict["defect_probability"] == 0.0

    def test_하자를_검출하고_조문을_돌려준다(self, client):
        bl = {**CLEAN_BL, "port_of_loading": "SHANGHAI, CHINA"}

        verdict = client.post(
            "/verify", json={"bl": bl, "lc": CLEAN_LC, "as_of": AS_OF}
        ).json()["verdict"]

        d003 = next(v for v in verdict["violations"] if v["rule_id"] == "D003")
        assert "UCP 600" in d003["source"]
        assert d003["remedy"]
        assert "port_of_loading" in d003["fields"]

    def test_LC가_없어도_동작한다(self, client):
        # 서류 내부 정합성만 검사한다.
        verdict = client.post(
            "/verify", json={"bl": CLEAN_BL, "as_of": AS_OF}
        ).json()["verdict"]

        assert verdict["skipped_count"] > 0

    def test_미검사_항목이_응답에_실린다(self, client):
        # 침묵하면 '검사했고 문제없다'로 읽힌다.
        verdict = client.post(
            "/verify", json={"bl": CLEAN_BL, "as_of": AS_OF}
        ).json()["verdict"]

        assert verdict["skipped"]
        assert all(s["reason"] for s in verdict["skipped"])

    def test_bl이_비면_400이다(self, client):
        response = client.post("/verify", json={"bl": {}})

        assert response.status_code == 400

    def test_bl이_없으면_422다(self, client):
        # Pydantic 이 잡는 스키마 오류.
        assert client.post("/verify", json={}).status_code == 422

    def test_as_of가_결과를_고정한다(self, client):
        bl = {**CLEAN_BL, "on_board_date": "2026-05-01"}

        early = client.post(
            "/verify", json={"bl": bl, "lc": CLEAN_LC, "as_of": "2026-05-10T00:00:00"}
        ).json()["verdict"]
        late = client.post(
            "/verify", json={"bl": bl, "lc": CLEAN_LC, "as_of": "2026-07-10T00:00:00"}
        ).json()["verdict"]

        ids_early = {v["rule_id"] for v in early["violations"]}
        ids_late = {v["rule_id"] for v in late["violations"]}
        assert "D018" not in ids_early
        assert "D018" in ids_late


class TestReport:
    def test_5개_구성과_미검사_부록을_돌려준다(self, client):
        body = client.post(
            "/report",
            json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
                  "submitted_documents": ["BILL OF LADING"]},
        ).json()

        assert set(body) >= {
            "summary", "risks", "checklist", "deadline",
            "recommendations", "outlook", "unchecked",
        }

    def test_요약에_산출_주체가_남는다(self, client):
        # 룰 가중치 합산을 학습된 모델의 확률로 표기하면 안 된다.
        summary = client.post(
            "/report", json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        ).json()["summary"]

        assert summary["model"] == "rules-v1"
        assert summary["narrative_source"] in {"template", "llm"}

    def test_권고가_심각도순이다(self, client):
        bl = {**CLEAN_BL, "port_of_loading": "SHANGHAI, CHINA", "vessel": None}

        recs = client.post(
            "/report", json={"bl": bl, "lc": CLEAN_LC, "as_of": AS_OF}
        ).json()["recommendations"]

        order = {"치명": 0, "경고": 1, "참고": 2}
        ranks = [order[r["severity_label"]] for r in recs]
        assert ranks == sorted(ranks)
        assert [r["order"] for r in recs] == list(range(1, len(recs) + 1))

    def test_제출서류_누락을_체크리스트가_잡는다(self, client):
        body = client.post(
            "/report",
            json={
                "bl": CLEAN_BL,
                "lc": {**CLEAN_LC, "documents_required":
                       ["COMMERCIAL INVOICE", "PACKING LIST", "BILL OF LADING"]},
                "as_of": AS_OF,
                "submitted_documents": ["BILL OF LADING"],
            },
        ).json()

        missing = [c for c in body["checklist"] if not c["done"]]
        labels = " ".join(c["label"] for c in missing)
        assert "PACKING LIST" in labels

    def test_PDF를_돌려준다(self, client):
        response = client.post(
            "/report/pdf", json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert "HG290309" in response.headers["content-disposition"]

    def test_PDF에_한글이_들어간다(self, client):
        fitz = pytest.importorskip("fitz", reason="PyMuPDF 미설치")

        response = client.post(
            "/report/pdf", json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        )
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            text = "\n".join(p.get_text() for p in doc)

        assert "선제 대응 서류 분석 리포트" in text
        hangul = sum(1 for ch in text if "가" <= ch <= "힣")
        assert hangul > 100


class TestPipelineIntegration:
    def test_추출_검증_리포트가_이어진다(self, client):
        # F1 → F3 → F4 가 같은 필드 형태로 이어지는지 확인한다.
        extract = client.post(
            "/extract/label",
            json={
                "Images": {"identifier": "E2E", "width": 1654, "height": 2340},
                "bbox": complete_bl_bboxes(),
            },
        ).json()

        bl = {f["name"]: f["value"] for f in extract["fields"]}
        verdict = client.post(
            "/verify", json={"bl": bl, "as_of": AS_OF}
        ).json()["verdict"]
        report = client.post(
            "/report", json={"bl": bl, "as_of": AS_OF}
        ).json()

        assert extract["is_ready_for_verification"]
        assert verdict["evaluated_count"] > 0
        assert report["bl_no"] == "HG290309"

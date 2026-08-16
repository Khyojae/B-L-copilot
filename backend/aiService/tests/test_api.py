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
    "place_of_issue": "PUSAN",
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

# 서류 간 정합성 검증용. CLEAN_BL·CLEAN_LC 와 저촉하지 않는 값이다.
CLEAN_INVOICE = {
    "invoice_no": "INV-2026-0421",
    "invoice_date": "2026-06-01",
    "seller": "GAE WOON CO., LTD.",
    "buyer": "DHHJ FRANCHISING CO., LTD.",
    "description_of_goods": "SAW MACHINE",
    "quantity": "27 PKG",
    "total_amount": "USD 9,800.00",
    "incoterms": "FOB",
    "lc_no": "LC-2026-001",
}


class TestHealth:
    def test_룰_적재_수를_보고한다(self, client):
        body = client.get("/health").json()

        assert body["status"] == "ok"
        assert body["rules_loaded"] >= 20

    def test_룰_목록에_조문이_실린다(self, client):
        body = client.get("/rules").json()

        # count 는 두 카탈로그의 합이다. 화면이 서류별 룰만 세면 실제 판정에
        # 쓰이는 룰보다 적게 표시된다.
        assert body["count"] == len(body["rules"]) + len(body["cross_rules"])
        assert all(r["source"] for r in body["rules"])
        assert all(r["source"] for r in body["cross_rules"])

    def test_룰_목록이_서류_간_룰을_함께_낸다(self, client):
        body = client.get("/rules").json()

        assert len(body["cross_rules"]) >= 10
        assert body["cross_catalog"]["label"] != body["catalog"]["label"]
        # 화면이 '해당 필드로 바로가기'를 그리려면 어느 서류의 어느 필드인지가
        # 있어야 한다. 서류별 룰과 달리 양쪽을 맞대므로 둘 다 필요하다.
        first = body["cross_rules"][0]
        assert first["scope"] == "cross_document"
        assert "." in first["left"] and "." in first["right"]


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


class TestExtractPDF:
    """F1 PDF 입력 — 기획안 5절 "이메일·엑셀·**PDF** 등 비정형 선적 서류"."""

    def _upload(self, client, path, **params):
        with open(path, "rb") as f:
            return client.post(
                "/extract/pdf",
                files={"file": ("bl.pdf", f.read(), "application/pdf")},
                params=params,
            )

    def test_PDF로_초안을_만든다(self, client, bl_pdf):
        response = self._upload(client, bl_pdf)

        assert response.status_code == 200
        body = response.json()
        assert body["is_ready_for_verification"] is True
        names = {f["name"]: f["value"] for f in body["fields"]}
        assert names["bl_no"] == "HG290309"

    def test_텍스트_레이어_경로임을_알린다(self, client, bl_pdf):
        # 신뢰도 1.0 이 '원문 그대로'인지 'OCR 이 확신한 값'인지는
        # 전혀 다른 이야기다. 화면이 구분할 수 있어야 한다.
        assert self._upload(client, bl_pdf).json()["source"] == "pdf-text"

    def test_이미지를_PDF로_올리면_400이다(self, client):
        # 확장자가 아니라 내용으로 판정한다. PyMuPDF 오류를 그대로 흘리면
        # 원인을 알 수 없는 500 이 된다.
        response = client.post(
            "/extract/pdf",
            files={"file": ("fake.pdf", b"PNG_NOT_A_PDF", "application/pdf")},
        )

        assert response.status_code == 400
        assert "PDF" in response.json()["detail"]

    def test_빈_파일은_400이다(self, client):
        response = client.post(
            "/extract/pdf", files={"file": ("empty.pdf", b"", "application/pdf")}
        )

        assert response.status_code == 400

    def test_없는_페이지는_400이다(self, client, bl_pdf):
        response = self._upload(client, bl_pdf, page=7)

        assert response.status_code == 400
        assert "범위" in response.json()["detail"]

    def test_라벨_경로와_같은_초안을_낸다(self, client, bl_pdf):
        # 두 입력 경로가 갈리면 '편집 후 재검증'이 다른 코드 경로를 탄다.
        from_pdf = self._upload(client, bl_pdf).json()
        from_label = client.post(
            "/extract/label",
            json={
                "Images": {"identifier": "bl", "width": 1654, "height": 2340},
                "bbox": complete_bl_bboxes(),
            },
        ).json()

        assert (
            {f["name"]: f["value"] for f in from_pdf["fields"]}
            == {f["name"]: f["value"] for f in from_label["fields"]}
        )


class TestMT700:
    """POST /lc/mt700 — 기획안 v2 5.1 의 L/C 원문 입력 경로."""

    MESSAGE = (
        ":20:LC-2026-101\n"
        ":31D:261231SEOUL\n"
        ":32B:USD123456,78\n"
        ":43P:NOT ALLOWED\n"
        ":44C:260630\n"
        ":44E:BUSAN, KOREA\n"
        ":44F:TOKYO, JAPAN\n"
        ":47A:ALL DOCUMENTS MUST BEAR THE CREDIT NUMBER\n"
    )

    def test_전문을_LC조건으로_바꾼다(self, client):
        response = client.post("/lc/mt700", json={"text": self.MESSAGE})
        body = response.json()

        assert response.status_code == 200
        assert body["lc"]["port_of_loading"] == "BUSAN, KOREA"
        assert body["lc"]["latest_shipment_date"] == "2026-06-30"
        assert body["lc"]["partial_shipment"] == "PROHIBITED"

    def test_못_읽은_것을_응답에_싣는다(self, client):
        # 화면이 이걸 못 받으면 검사하지 않은 조건이 검사된 것처럼 보인다.
        body = client.post("/lc/mt700", json={"text": self.MESSAGE}).json()

        assert "47A" in body["unmapped"]
        assert body["notes"]

    def test_응답을_그대로_verify_에_실을_수_있다(self, client):
        # 이 왕복이 깨지면 파서는 돌지만 쓸 데가 없다.
        lc = client.post("/lc/mt700", json={"text": self.MESSAGE}).json()["lc"]

        verdict = client.post(
            "/verify", json={"bl": CLEAN_BL, "lc": lc, "as_of": AS_OF}
        ).json()["verdict"]

        assert verdict["counts"]["critical"] == 0
        # L/C 를 실었으므로 대조 룰이 실제로 평가돼야 한다.
        assert verdict["evaluated_count"] > 0

    def test_태그가_없으면_400이다(self, client):
        # 빈 L/C 로 검증을 돌리면 위반 0건이 나오고 화면은 '하자 없음'으로
        # 읽는다. 200 으로 흘리지 않는다.
        response = client.post("/lc/mt700", json={"text": "첨부 참조 바랍니다."})

        assert response.status_code == 400

    def test_text가_없으면_422다(self, client):
        assert client.post("/lc/mt700", json={}).status_code == 422


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


class TestVerifyCrossDocument:
    """서류 간 정합성이 `/verify` 응답에 합쳐져 나오는지 (21번)."""

    def test_서류를_안_주면_서류_간_카탈로그가_비어_있다(self, client):
        verdict = client.post(
            "/verify", json={"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        ).json()["verdict"]

        # null 은 '돌리지 않았다'는 뜻이다. '돌렸는데 위반이 없었다'와 다르며
        # 화면이 이 둘을 같게 그리면 검사 범위를 속이게 된다.
        assert verdict["cross_catalog"] is None

    def test_송장을_주면_서류_간_룰이_함께_돈다(self, client):
        verdict = client.post("/verify", json={
            "bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"상업송장": CLEAN_INVOICE},
        }).json()["verdict"]

        assert verdict["cross_catalog"]["label"]
        assert verdict["cross_catalog"] != verdict["catalog"]

    def test_송장_명세가_어긋나면_저촉이_잡힌다(self, client):
        invoice = {**CLEAN_INVOICE, "description_of_goods": "COTTON FABRIC ROLL"}

        verdict = client.post("/verify", json={
            "bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"상업송장": invoice},
        }).json()["verdict"]

        x003 = next(v for v in verdict["violations"] if v["rule_id"] == "X003")
        assert x003["source"]
        # 서류가 둘이므로 필드에 종류가 붙는다. S4 의 바로가기가 이걸 쓴다.
        assert any("선하증권." in f for f in x003["fields"])
        assert any("상업송장." in f for f in x003["fields"])

    def test_송장_금액이_LC를_넘으면_저촉이다(self, client):
        invoice = {**CLEAN_INVOICE, "total_amount": "USD 99,000.00"}

        verdict = client.post("/verify", json={
            "bl": CLEAN_BL, "lc": {**CLEAN_LC, "currency_amount": "USD 10,000.00"},
            "as_of": AS_OF, "documents": {"상업송장": invoice},
        }).json()["verdict"]

        assert any(v["rule_id"] == "X009" for v in verdict["violations"])

    def test_없는_서류의_룰은_위반이_아니라_평가불가다(self, client):
        # 포장명세서를 주지 않았다. 사용자가 고칠 수 없는 것을 하자로 세면
        # 화면이 신뢰를 잃는다.
        verdict = client.post("/verify", json={
            "bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"상업송장": CLEAN_INVOICE},
        }).json()["verdict"]

        packing_rules = {"X004", "X005", "X006", "X007"}
        assert not packing_rules & {v["rule_id"] for v in verdict["violations"]}
        assert packing_rules <= {s["rule_id"] for s in verdict["skipped"]}

    def test_서류별_판정은_그대로_남는다(self, client):
        bl = {**CLEAN_BL, "port_of_loading": "SHANGHAI, CHINA"}

        verdict = client.post("/verify", json={
            "bl": bl, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"상업송장": CLEAN_INVOICE},
        }).json()["verdict"]

        assert any(v["rule_id"] == "D003" for v in verdict["violations"])

    def test_모르는_서류_종류는_400이다(self, client):
        # 조용히 무시하면 그 서류를 쓰는 룰이 전부 평가불가로 빠지는데,
        # 200 응답을 받은 사용자는 검사가 된 줄 안다.
        response = client.post("/verify", json={
            "bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"invoice": CLEAN_INVOICE},
        })

        assert response.status_code == 400
        assert "invoice" in response.json()["detail"]

    def test_예측은_서류별_판정으로만_낸다(self, client):
        """모델은 서류별 룰만 돌던 판정으로 학습했다(30번 전까지)."""
        payload = {"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        alone = client.post("/verify", json=payload).json()

        invoice = {**CLEAN_INVOICE, "description_of_goods": "COTTON FABRIC ROLL"}
        withdoc = client.post(
            "/verify", json={**payload, "documents": {"상업송장": invoice}}
        ).json()

        # 서류 간 위반이 늘어도 예측 확률은 움직이지 않는다.
        assert withdoc["verdict"]["counts"]["critical"] > alone["verdict"]["counts"]["critical"]
        assert withdoc["prediction"]["probability"] == alone["prediction"]["probability"]

    def test_리포트도_서류_간_저촉을_싣는다(self, client):
        invoice = {**CLEAN_INVOICE, "description_of_goods": "COTTON FABRIC ROLL"}

        body = client.post("/report", json={
            "bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF,
            "documents": {"상업송장": invoice},
        }).json()

        assert body["summary"]["cross_rule_catalog"]["label"]
        assert any(r["rule_id"] == "X003" for r in body["risks"])

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
        """표기가 실제 산출 주체와 일치해야 한다.

        이전 판은 `== "rules-v1"` 을 단언했다. 모델이 파이프라인에 붙기 전의
        상태를 굳힌 것이라, 모델을 연결하자 **정상 동작이 실패로 잡혔다.**
        재고 싶은 것은 특정 값이 아니라 표기와 실제의 일치다.
        """
        body = {"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}
        summary = client.post("/report", json=body).json()["summary"]
        prediction = client.post("/verify", json=body).json()["prediction"]

        assert summary["model"] in {"rules-v1", "xgboost-v1"}
        # 같은 입력인데 두 응답의 산출 주체가 갈리면 어느 쪽이 참인지 알 수 없다.
        assert summary["model"] == prediction["model"]
        # Prediction.to_dict 는 4자리로 반올림하고 리포트는 원값을 담는다.
        assert round(summary["defect_probability"], 4) == prediction["probability"]

    def test_모델이_없으면_룰로_표기한다(self, client, tmp_path, monkeypatch):
        # 조용히 룰 가중치로 떨어지면서 'AI 예측'으로 표기하면,
        # 5절이 기록한 "리포트 출처 거짓 표기" 결함이 되풀이된다.
        from mlModel.predictor import DefectPredictor

        import api.main as main

        monkeypatch.setattr(
            main, "_predictor", DefectPredictor(model_path=tmp_path / "없음.json")
        )
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


class TestReportShare:
    """F4 공유 — 기획안 5절 "PDF 출력·공유 가능"."""

    BODY = {"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF}

    def test_링크를_발급한다(self, client):
        response = client.post("/report/share", json=self.BODY)

        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["path"].endswith(body["token"])
        assert body["pdf_path"].endswith("/pdf")

    def test_공유_링크가_같은_리포트를_낸다(self, client):
        # 저장하지 않으므로, 링크를 열 때마다 다시 조립한다. 원본과
        # 어긋나면 공유받은 쪽이 다른 판정을 보게 된다.
        direct = client.post("/report", json=self.BODY).json()
        token = client.post("/report/share", json=self.BODY).json()["token"]

        shared = client.get(f"/report/shared/{token}")

        assert shared.status_code == 200
        assert shared.json() == direct

    def test_공유_링크로_PDF를_연다(self, client):
        token = client.post("/report/share", json=self.BODY).json()["token"]

        response = client.get(f"/report/shared/{token}/pdf")

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        # 링크를 클릭하면 브라우저에서 바로 보여야 한다. attachment 면
        # 받는 쪽이 파일을 내려받아 여는 한 단계를 더 거친다.
        assert response.headers["content-disposition"].startswith("inline")

    def test_위조된_토큰을_거절한다(self, client):
        token = client.post("/report/share", json=self.BODY).json()["token"]
        head, packed, signature = token.split(".")
        forged = f"{head}.{packed}.{'A' * len(signature)}"

        assert client.get(f"/report/shared/{forged}").status_code == 404

    def test_본문을_바꾸면_서명이_깨진다(self, client):
        # 서명이 본문을 덮지 않으면 받은 쪽이 내용을 고쳐 열 수 있다.
        import base64
        import json
        import zlib

        from report import share

        token = client.post("/report/share", json=self.BODY).json()["token"]
        head, packed, signature = token.split(".")
        body = json.loads(zlib.decompress(share._b64decode(packed)))
        body["data"]["bl"]["bl_no"] = "위조됨"
        tampered = base64.urlsafe_b64encode(
            zlib.compress(json.dumps(body).encode())
        ).decode().rstrip("=")

        response = client.get(f"/report/shared/{head}.{tampered}.{signature}")

        assert response.status_code == 404

    def test_만료된_링크는_410_이다(self, client):
        # 404 로 내면 받은 쪽이 '주소가 틀렸나'를 의심하게 된다.
        from report import share

        token = share.encode({"bl": CLEAN_BL, "lc": CLEAN_LC, "as_of": AS_OF},
                             ttl_seconds=60, now=0)

        response = client.get(f"/report/shared/{token}")

        assert response.status_code == 410
        assert "만료" in response.json()["detail"]

    def test_형식이_틀린_토큰을_거절한다(self, client):
        assert client.get("/report/shared/아무거나").status_code == 404

    def test_열리지_않을_링크는_발급하지_않는다(self, client):
        # 발급은 되고 열면 400 이면, 공유받은 쪽에서 터지고 원인을 알 수 없다.
        response = client.post("/report/share", json={"bl": {}})

        assert response.status_code == 400

    def test_만료를_지정할_수_있다(self, client):
        short = client.post(
            "/report/share", json={**self.BODY, "ttl_seconds": 3600}
        ).json()
        default = client.post("/report/share", json=self.BODY).json()

        assert short["expires_at"] < default["expires_at"]


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

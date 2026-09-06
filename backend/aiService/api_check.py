"""API 전 경로 점검.

실행:
    python -m api_check          # PaddleOCR 경로 제외 (빠름)
    python -m api_check --ocr    # 전 경로

모든 엔드포인트를 실제로 한 번씩 호출한다. LLM 은 끈다 — 네트워크·요금에
묶이면 API 가 멀쩡한지와 외부가 멀쩡한지를 구분할 수 없다.
"""

import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ.setdefault("LLM_STRUCTURED_EXTRACT", "false")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

WITH_OCR = "--ocr" in sys.argv

BL = {
    "bl_no": "HG290309",
    "shipper": "GAE WOON CO., LTD.",
    "consignee": "DHHJ FRANCHISING CO., LTD.",
    "notify_party": "TRY ENERGY CO., LTD.",
    "vessel": "MSC BIANCA",
    "voyage_no": "V.112",
    "port_of_loading": "BUSAN, KOREA",
    "port_of_discharge": "TOKYO, JAPAN",
    "description_of_goods": "SAW MACHINE FOB",
    "gross_weight": "884 KG",
    "measurement": "349.64 CBM",
    "date_of_issue": "2026-06-01",
    "place_of_issue": "PUSAN",
    "on_board_date": "2026-06-01",
    "total_freight": "$1,741.56",
}

# 서류 간 정합성 점검용 상업송장. BL 과 저촉하지 않는 값이다 — 여기서 보는
# 것은 하자 검출이 아니라 **경로가 살아 있는가**이므로 정상 서류를 쓴다.
INVOICE = {
    "invoice_no": "INV-2026-0421",
    "invoice_date": "2026-06-01",
    "seller": "GAE WOON CO., LTD.",
    "buyer": "DHHJ FRANCHISING CO., LTD.",
    "description_of_goods": "SAW MACHINE",
    "quantity": "27 PKG",
    "total_amount": "USD 9,800.00",
    "incoterms": "FOB",
    "lc_no": "LC-2026-0001",
}

LINES = [
    (0.35, 0.03, "BILL OF LADING"),
    (0.60, 0.09, "B/L NO HG290309"),
    (0.06, 0.14, "GAE WOON CO., LTD."),
    (0.06, 0.21, "DHHJ FRANCHISING CO., LTD."),
    (0.06, 0.28, "TRY ENERGY CO., LTD."),
    (0.06, 0.40, "MSC BIANCA V.112"),
    (0.06, 0.44, "BUSAN, KOREA"),
    (0.35, 0.44, "TOKYO, JAPAN"),
    (0.08, 0.55, "27 PKG CELL ASSEMBLY"),
    (0.62, 0.62, "TOTAL 884 KG"),
    (0.62, 0.66, "TOTAL 349.64 CBM"),
    (0.06, 0.78, "FREIGHT PREPAID $1,741.56"),
    (0.27, 0.90, "PUSAN"),
    (0.27, 0.93, "2026-06-01"),
]

MT700 = """{1:F01BANKKRSEAXXX0000000000}{2:I700BANKJPJTXXXXN}{4:
:20:LC-2026-0001
:31D:261231SEOUL
:32B:USD50000,00
:44E:BUSAN, KOREA
:44F:TOKYO, JAPAN
:44C:260630
:45A:SAW MACHINE
:46A:+BILL OF LADING
+COMMERCIAL INVOICE
:47A:SHIPMENT MUST BE EFFECTED BY LINER VESSEL
:48:21
-}"""

W, H = 1654, 2340
PW, PH = 595.0, 842.0

results = []


def check(name, fn):
    start = time.perf_counter()
    try:
        detail = fn()
        ok = True
    except Exception as exc:  # noqa: BLE001
        detail, ok = f"{type(exc).__name__}: {exc}", False
    ms = (time.perf_counter() - start) * 1000
    results.append((ok, name, detail, ms))
    print(f"  {'✅' if ok else '❌'} {name:<34} {ms:7.0f}ms  {str(detail)[:52]}")


def bboxes():
    out = []
    for xr, yr, text in LINES:
        x0, y0 = int(xr * W), int(yr * H)
        x1 = x0 + int(len(text) * 0.011 * W)
        y1 = y0 + int(0.014 * H)
        out.append({"data": text, "x": [x0, x0, x1, x1], "y": [y0, y1, y0, y1]})
    return out


def make_pdf(path: Path, text_layer=True):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=PW, height=PH)
    if text_layer:
        for xr, yr, text in LINES:
            page.insert_text((xr * PW, (yr + 0.012) * PH), text,
                             fontsize=9, fontname="helv")
    else:
        page.draw_rect(pymupdf.Rect(50, 50, 545, 792))
    doc.save(str(path))
    doc.close()


def make_xlsx(path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BL"
    rows = [
        ["BILL OF LADING", ""],
        ["B/L NO", "HG290309"],
        ["SHIPPER", "GAE WOON CO., LTD."],
        ["CONSIGNEE", "DHHJ FRANCHISING CO., LTD."],
        ["PORT OF LOADING", "BUSAN, KOREA"],
        ["PORT OF DISCHARGE", "TOKYO, JAPAN"],
        ["DATE OF ISSUE", "2026-06-01"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def make_eml(path: Path, pdf_path: Path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "B/L draft"
    msg["From"] = "a@b.com"
    msg["To"] = "c@d.com"
    msg.set_content("첨부 확인 바랍니다.")
    msg.add_attachment(pdf_path.read_bytes(), maintype="application",
                       subtype="pdf", filename="bl.pdf")
    path.write_bytes(msg.as_bytes())


with TestClient(app) as client, tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    print("\n── 조회 ─────────────────────────────────────────────────────")

    def _health():
        r = client.get("/health")
        r.raise_for_status()
        d = r.json()
        return f"룰 {d['rules_loaded']}건 · {d['rule_catalog']['label']}"

    check("GET  /health", _health)

    def _rules():
        d = client.get("/rules").json()
        return f"{d['count']}건 · 미검증 {d['unverified_source_count']}"

    check("GET  /rules", _rules)

    print("\n── F1 인테이크 ──────────────────────────────────────────────")

    def _label():
        r = client.post("/extract/label", json={
            "Images": {"identifier": "T", "width": W, "height": H,
                       "form_type": "선하증권"},
            "bbox": bboxes(),
        })
        r.raise_for_status()
        d = r.json()
        return f"채움 {d['completeness']:.0%} · 확인 {d['review_required_count']}"

    check("POST /extract/label", _label)

    def _pdf():
        p = tmp / "bl.pdf"
        make_pdf(p)
        r = client.post("/extract/pdf",
                        files={"file": ("bl.pdf", p.read_bytes(), "application/pdf")})
        r.raise_for_status()
        d = r.json()
        return f"{d['source']} · 채움 {d['completeness']:.0%}"

    check("POST /extract/pdf", _pdf)

    def _xlsx():
        p = tmp / "bl.xlsx"
        make_xlsx(p)
        r = client.post("/extract/excel", files={"file": ("bl.xlsx", p.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        r.raise_for_status()
        d = r.json()
        return f"{d['source']} · 채움 {d['completeness']:.0%}"

    check("POST /extract/excel", _xlsx)

    def _eml():
        p, pdf = tmp / "mail.eml", tmp / "bl.pdf"
        make_eml(p, pdf)
        r = client.post("/extract/email",
                        files={"file": ("mail.eml", p.read_bytes(), "message/rfc822")})
        r.raise_for_status()
        d = r.json()
        return f"{d['source']} · 채움 {d['completeness']:.0%}"

    check("POST /extract/email", _eml)

    if WITH_OCR:
        def _image():
            import pymupdf

            p = tmp / "bl.pdf"
            doc = pymupdf.open(str(p))
            pix = doc[0].get_pixmap(dpi=200)
            img = tmp / "bl.png"
            pix.save(str(img))
            doc.close()
            r = client.post("/extract", files={"file": ("bl.png", img.read_bytes(),
                                                        "image/png")})
            r.raise_for_status()
            d = r.json()
            return f"{d['source']} · 채움 {d['completeness']:.0%}"

        check("POST /extract (PaddleOCR)", _image)
    else:
        print("  ⏭  POST /extract (PaddleOCR)        건너뜀 — --ocr 로 포함")

    print("\n── L/C · 검증 ───────────────────────────────────────────────")

    def _mt700():
        r = client.post("/lc/mt700", json={"text": MT700})
        r.raise_for_status()
        d = r.json()
        assert "lc" in d, f"응답 키가 바뀌었다: {list(d)}"
        terms = d["lc"]
        assert terms.get("lc_no"), ":20: 을 못 읽었다"
        return (f"lc_no={terms['lc_no']} · 요구서류 "
                f"{len(terms.get('documents_required') or [])}건 · "
                f"미매핑 {len(d.get('unmapped') or {})}")

    check("POST /lc/mt700", _mt700)

    lc = client.post("/lc/mt700", json={"text": MT700}).json()["lc"]

    def _verify():
        r = client.post("/verify", json={"bl": BL, "lc": lc,
                                         "as_of": "2026-06-10T00:00:00"})
        r.raise_for_status()
        d = r.json()["verdict"]
        # **절대 개수로 재지 않는다.** 신용장이 침묵한 조건의 룰은 평가불가로
        # 빠지는 것이 옳고(그걸 위반으로 세면 정상 건이 반려된다), 그 수는
        # L/C 내용에 달렸다. 임계값을 박으면 L/C 를 바꿀 때마다 점검이 깨진다.
        #
        # 대신 **L/C 를 실으면 검사 범위가 넓어진다**는 불변식을 본다. 여기가
        # 깨졌다면 L/C 가 요청에 제대로 실리지 않은 것이다.
        bare = client.post("/verify", json={"bl": BL,
                                            "as_of": "2026-06-10T00:00:00"})
        bare.raise_for_status()
        without = bare.json()["verdict"]["evaluated_count"]
        assert d["evaluated_count"] > without, (
            f"L/C 를 실어도 평가 범위가 그대로다 ({without} → {d['evaluated_count']})"
        )
        return (f"위반 {len(d['violations'])} · 평가 {without}→{d['evaluated_count']} · "
                f"미평가 {d['skipped_count']} · {d['catalog']['label']}")

    check("POST /verify", _verify)

    def _verify_bad():
        r = client.post("/verify", json={"bl": {}})
        return f"빈 입력 → {r.status_code} (400 이어야 함)" if r.status_code == 400 \
            else f"빈 입력 → {r.status_code} ✗"

    check("POST /verify (빈 입력)", _verify_bad)

    def _verify_cross():
        """서류 간 정합성이 같은 응답에 합쳐지는지 (21번)."""
        payload = {"bl": BL, "lc": lc, "as_of": "2026-06-10T00:00:00"}
        alone = client.post("/verify", json=payload).json()["verdict"]

        r = client.post("/verify", json={**payload, "documents": {"상업송장": INVOICE}})
        r.raise_for_status()
        d = r.json()["verdict"]

        # 여기도 절대 개수로 재지 않는다. 보는 것은 두 불변식이다 —
        # 서류를 주기 전에는 서류 간 카탈로그가 없고(검사하지 않았다),
        # 주고 나면 검사 범위가 넓어진다.
        assert alone["cross_catalog"] is None, "서류를 안 줬는데 서류 간 판정이 있다"
        assert d["cross_catalog"], "서류를 줬는데 서류 간 카탈로그가 비었다"
        assert d["evaluated_count"] > alone["evaluated_count"], (
            f"송장을 실어도 평가 범위가 그대로다 "
            f"({alone['evaluated_count']} → {d['evaluated_count']})"
        )
        cross_hits = [v for v in d["violations"] if v["rule_id"].startswith("X")]
        return (f"평가 {alone['evaluated_count']}→{d['evaluated_count']} · "
                f"서류 간 위반 {len(cross_hits)} · {d['cross_catalog']['label']}")

    check("POST /verify (서류 간)", _verify_cross)

    def _verify_cross_bad():
        r = client.post("/verify", json={
            "bl": BL, "lc": lc, "as_of": "2026-06-10T00:00:00",
            "documents": {"invoice": INVOICE},
        })
        return f"모르는 서류 종류 → {r.status_code} (400 이어야 함)" \
            if r.status_code == 400 else f"모르는 서류 종류 → {r.status_code} ✗"

    check("POST /verify (모르는 서류 종류)", _verify_cross_bad)

    def _verify_held():
        """필수 확인 등급 필드가 판정 보류로 이어지는지 (32·33번).

        점검은 "신뢰도를 실으면 검사 범위가 **좁아진다**"는 불변식을 본다.
        평가 건수가 줄고 그만큼 보류로 옮겨가야 한다 — 줄지 않으면 배선이
        끊긴 것이고, 그 실패는 200 응답 뒤에 숨는다.
        """
        base = {"bl": BL, "lc": lc, "as_of": "2026-06-10T00:00:00"}
        alone = client.post("/verify", json=base).json()["verdict"]
        r = client.post("/verify", json={
            **base, "field_confidence": {"port_of_discharge": 0.4},
        })
        r.raise_for_status()
        d = r.json()["verdict"]

        assert d["held_count"], "필수 확인 필드를 줬는데 보류된 룰이 없다"
        assert d["evaluated_count"] < alone["evaluated_count"],             "보류가 생겼는데 평가 건수가 그대로다"
        assert all("port_of_discharge" in h["fields"] for h in d["held"]),             "보류 사유가 준 필드와 무관하다"
        low, high = d["probability_range"]
        assert low <= high, "범위의 하한이 상한보다 크다"
        return (f"평가 {alone['evaluated_count']}→{d['evaluated_count']} · "
                f"보류 {d['held_count']} · 범위 {low:.2f}~{high:.2f}")

    check("POST /verify (판정 보류)", _verify_held)

    print("\n── F4 리포트 ────────────────────────────────────────────────")

    body = {"bl": BL, "lc": lc, "as_of": "2026-06-10T00:00:00",
            "submitted_documents": ["BILL OF LADING"]}

    def _report():
        r = client.post("/report", json=body)
        r.raise_for_status()
        d = r.json()
        return (f"위험 {d['summary']['risk_level']} · 리스크 {len(d['risks'])} · "
                f"기한 {d['deadline']['effective_due'] if d['deadline'] else '-'}")

    check("POST /report", _report)

    def _report_pdf():
        r = client.post("/report/pdf", json=body)
        r.raise_for_status()
        assert r.content[:4] == b"%PDF", "PDF 헤더가 아님"
        return f"{len(r.content):,} bytes"

    check("POST /report/pdf", _report_pdf)

    token = None

    def _share():
        global token
        r = client.post("/report/share", json={**body, "ttl_seconds": 3600})
        r.raise_for_status()
        d = r.json()
        token = d["token"]
        return f"만료 {d['expires_at'][:16]} · 임시키={d['ephemeral_secret']}"

    check("POST /report/share", _share)

    def _shared():
        r = client.get(f"/report/shared/{token}")
        r.raise_for_status()
        return f"위험 {r.json()['summary']['risk_level']}"

    check("GET  /report/shared/{token}", _shared)

    def _shared_pdf():
        r = client.get(f"/report/shared/{token}/pdf")
        r.raise_for_status()
        return f"{len(r.content):,} bytes · {r.headers['content-disposition'][:20]}"

    check("GET  /report/shared/{token}/pdf", _shared_pdf)

    def _shared_bad():
        r = client.get("/report/shared/엉터리토큰")
        return f"{r.status_code} (404 이어야 함)"

    check("GET  /report/shared (잘못된 토큰)", _shared_bad)

ok = sum(1 for r in results if r[0])
print(f"\n{'=' * 66}")
print(f"통과 {ok} / {len(results)}")
for good, name, detail, _ in results:
    if not good:
        print(f"  ❌ {name}: {detail}")

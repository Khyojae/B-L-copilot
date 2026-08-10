"""엑셀·이메일 입력 테스트 (기획안 5절 2·3번).

픽스처를 conftest 가 아니라 여기 둔다. 이 두 형식은 좌표가 없는 입력이라
라벨·PDF 픽스처와 공유할 것이 없고, 여기 두면 무엇을 만들어 무엇을 기대하는지
한 파일에서 읽힌다.
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from conftest import complete_bl_bboxes, write_bl_pdf
from ocr import IntakePipeline
from ocr.extractor import OCRExtractor
from ocr.mail import parse_email
from ocr.spreadsheet import from_excel

openpyxl = pytest.importorskip("openpyxl", reason="openpyxl 미설치")

# 엑셀·이메일 본문에 심는 값. 라벨 픽스처와 다른 값을 쓴다 — 같은 값을 쓰면
# 파서가 어느 입력에서 읽었는지 구분되지 않는다.
# 12자를 넘으면 파서가 화물 추적 코드로 보고 버린다(_BL_NO_MAX_LEN).
# 실제 B/L 번호는 선사 접두 2~4자 + 일련번호로 대개 그 안에 들어간다.
BL_NO = "SMBL26080001"
SHIPPER = "HANWOO TRADING CO., LTD."
CONSIGNEE = "PACIFIC IMPORT GMBH"
VESSEL = "HMM ROTTERDAM V.024E"
POL = "BUSAN, KOREA"
POD = "HAMBURG, GERMANY"

ROWS = [
    ("BILL OF LADING", ""),
    ("B/L NO", BL_NO),
    ("SHIPPER", SHIPPER),
    ("CONSIGNEE", CONSIGNEE),
    ("VESSEL", VESSEL),
    ("PORT OF LOADING", POL),
    ("PORT OF DISCHARGE", POD),
    ("DESCRIPTION OF GOODS", "27 PKG CELL ASSEMBLY"),
    ("GROSS WEIGHT", "884 KG"),
]


def write_xlsx(tmp_path: Path, rows=ROWS, name: str = "bl.xlsx",
               sheet_title: str = "BL", extra_sheet: bool = False) -> str:
    """A열 라벨 / B열 값 형태의 엑셀 B/L."""
    wb = openpyxl.Workbook()
    if extra_sheet:
        # 표지 시트를 앞에 둔다. '첫 시트'를 고르면 빈 결과가 나온다.
        cover = wb.active
        cover.title = "COVER"
        cover["A1"] = "SHIPPING DOCUMENTS"
        ws = wb.create_sheet(sheet_title)
    else:
        ws = wb.active
        ws.title = sheet_title

    for index, (label, value) in enumerate(rows, start=1):
        ws.cell(row=index, column=1, value=label)
        if value:
            ws.cell(row=index, column=2, value=value)

    path = tmp_path / name
    wb.save(str(path))
    return str(path)


def write_eml(tmp_path: Path, body: str = "", attachment: Path | None = None,
              subject: str = "B/L for shipment", name: str = "mail.eml",
              maintype: str = "application",
              subtype: str = "pdf") -> str:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "forwarder@example.com"
    msg["To"] = "trader@example.com"
    msg.set_content(body or "Please find the document attached.")

    if attachment is not None:
        msg.add_attachment(
            Path(attachment).read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=Path(attachment).name,
        )

    path = tmp_path / name
    path.write_bytes(msg.as_bytes())
    return str(path)


class TestExcel:
    def test_엑셀에서_초안을_만든다(self, tmp_path):
        draft = IntakePipeline().run_from_excel(write_xlsx(tmp_path))

        values = {f["name"]: f["value"] for f in draft.to_dict()["fields"]}
        assert values["bl_no"] == BL_NO
        assert values["port_of_loading"] == POL
        assert values["port_of_discharge"] == POD

    def test_OCR_없이_동작한다(self, tmp_path, monkeypatch):
        # PaddleOCR 을 못 쓰게 막아도 엑셀 경로는 끝까지 가야 한다.
        def boom(*_args, **_kwargs):
            raise AssertionError("엑셀 경로가 OCR 을 탔습니다")

        monkeypatch.setattr(OCRExtractor, "_get_ocr", boom)
        result = OCRExtractor().from_excel(write_xlsx(tmp_path))

        assert result.source == "excel"

    def test_셀_값을_추측하지_않는다(self, tmp_path):
        result = OCRExtractor().from_excel(write_xlsx(tmp_path))

        # 셀에 적힌 글자를 그대로 읽었으므로 전부 1.0 이다.
        assert {b.confidence for b in result.bboxes} == {1.0}

    def test_값이_가장_많은_시트를_고른다(self, tmp_path):
        # 표지 시트가 앞에 있어도 본문 시트를 찾아야 한다.
        result = from_excel(write_xlsx(tmp_path, extra_sheet=True))
        texts = " | ".join(b.text for b in result.bboxes)

        assert BL_NO in texts
        assert "SHIPPING DOCUMENTS" not in texts

    def test_시트를_지정할_수_있다(self, tmp_path):
        path = write_xlsx(tmp_path, extra_sheet=True)
        result = from_excel(path, sheet="COVER")

        assert "SHIPPING DOCUMENTS" in " ".join(b.text for b in result.bboxes)

    def test_없는_시트는_거절한다(self, tmp_path):
        with pytest.raises(ValueError, match="시트를 찾을 수 없습니다"):
            from_excel(write_xlsx(tmp_path), sheet="NOPE")

    def test_빈_시트는_거절한다(self, tmp_path):
        wb = openpyxl.Workbook()
        path = tmp_path / "empty.xlsx"
        wb.save(str(path))

        with pytest.raises(ValueError, match="값이 있는 셀이 없습니다"):
            from_excel(str(path))

    def test_그리드를_좌표로_펼친다(self, tmp_path):
        result = from_excel(write_xlsx(tmp_path))
        by_text = {b.text: b for b in result.bboxes}

        # A열 라벨이 B열 값보다 왼쪽에 있어야 앵커 탐색이 성립한다.
        assert by_text["B/L NO"].x_min < by_text[BL_NO].x_min
        # 같은 행이므로 세로 위치가 같다.
        assert by_text["B/L NO"].y_min == by_text[BL_NO].y_min


class TestEmail:
    def test_첨부_PDF를_서류로_쓴다(self, tmp_path):
        pdf = write_bl_pdf(tmp_path, complete_bl_bboxes())
        result = OCRExtractor().from_email(write_eml(tmp_path, attachment=Path(pdf)))

        assert result.source == "email-pdf"
        # PDF 텍스트 레이어의 값이지 본문 안내문이 아니다.
        assert "HG290309" in " ".join(b.text for b in result.bboxes)

    def test_첨부_엑셀을_서류로_쓴다(self, tmp_path):
        xlsx = write_xlsx(tmp_path)
        result = OCRExtractor().from_email(write_eml(
            tmp_path, attachment=Path(xlsx),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ))

        assert result.source == "email-excel"
        assert BL_NO in " ".join(b.text for b in result.bboxes)

    def test_첨부가_없으면_본문을_읽는다(self, tmp_path):
        body = "\n".join(f"{label}: {value}" for label, value in ROWS if value)
        draft = IntakePipeline().run_from_email(write_eml(tmp_path, body=body))

        values = {f["name"]: f["value"] for f in draft.to_dict()["fields"]}
        assert values["bl_no"] == BL_NO

    def test_본문의_라벨과_값을_갈라_놓는다(self, tmp_path):
        path = write_eml(tmp_path, body=f"B/L NO: {BL_NO}")
        result = OCRExtractor().from_email(path)
        by_text = {b.text: b for b in result.bboxes}

        # 한 상자에 뭉쳐 있으면 앵커가 값을 찾지 못한다.
        assert "B/L NO" in by_text
        assert BL_NO in by_text
        assert by_text["B/L NO"].x_max <= by_text[BL_NO].x_min

    def test_첨부가_본문보다_우선한다(self, tmp_path):
        # 본문에도 값이 있지만 첨부가 서류다.
        pdf = write_bl_pdf(tmp_path, complete_bl_bboxes())
        path = write_eml(tmp_path, body=f"B/L NO: {BL_NO}", attachment=Path(pdf))
        result = OCRExtractor().from_email(path)

        texts = " ".join(b.text for b in result.bboxes)
        assert result.source == "email-pdf"
        assert BL_NO not in texts

    def test_지원하지_않는_첨부는_무시한다(self, tmp_path):
        junk = tmp_path / "note.txt"
        junk.write_text("not a document", encoding="utf-8")
        body = f"B/L NO: {BL_NO}"
        path = write_eml(tmp_path, body=body, attachment=junk,
                         maintype="text", subtype="plain")

        result = OCRExtractor().from_email(path)
        assert result.source == "email-body"

    def test_제목도_읽는다(self, tmp_path):
        path = write_eml(tmp_path, body="Please see below.",
                         subject=f"B/L NO: {BL_NO}")
        result = OCRExtractor().from_email(path)

        assert BL_NO in " ".join(b.text for b in result.bboxes)

    def test_본문도_첨부도_없으면_거절한다(self, tmp_path):
        path = write_eml(tmp_path, body=" ", subject="")

        with pytest.raises(ValueError, match="본문이 비어 있고"):
            OCRExtractor().from_email(path)

    def test_첨부를_분류한다(self, tmp_path):
        pdf = write_bl_pdf(tmp_path, complete_bl_bboxes())
        content = parse_email(write_eml(tmp_path, attachment=Path(pdf)))

        assert [a.kind for a in content.attachments] == ["pdf"]
        assert content.best_attachment().filename.endswith(".pdf")

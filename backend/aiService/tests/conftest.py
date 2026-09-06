"""
테스트 공용 픽스처.

실제 라벨 데이터셋은 저장소에 없으므로(용량·기밀) 구역 좌표에 맞춘 합성
라벨 JSON 을 만들어 쓴다. 합성이라 오히려 좋은 면이 있다 — 어떤 값이
어느 구역에 있는지 테스트가 직접 통제하므로 실패했을 때 원인이 분명하다.

좌표는 field_parser.FieldParser.REGIONS 의 비율을 그대로 따른다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pytest

# aiService 를 임포트 루트로 잡는다. 패키지 설치 없이 테스트가 돌아야 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IMAGE_WIDTH = 1654
IMAGE_HEIGHT = 2340

# 각 구역의 대표 좌표(중심). FieldParser.REGIONS 범위 안에 들어간다.
REGION_CENTERS: Dict[str, tuple[float, float]] = {
    "header":       (0.50, 0.06),
    "bl_no":        (0.67, 0.19),
    "shipper":      (0.25, 0.10),
    "consignee":    (0.25, 0.21),
    "notify":       (0.25, 0.31),
    "vessel_info":  (0.30, 0.40),
    "port_left":    (0.14, 0.43),
    "port_right":   (0.41, 0.43),
    "cargo":        (0.36, 0.60),
    "weight":       (0.71, 0.62),
    "measurement":  (0.88, 0.62),
    "freight":      (0.27, 0.80),
    "footer":       (0.27, 0.90),
}


def make_bbox(
    text: str,
    xr: float,
    yr: float,
    *,
    width_ratio: float = 0.16,
    height_px: int = 28,
) -> dict:
    """상대 좌표(0~1)에 텍스트 하나를 배치한다."""
    cx, cy = xr * IMAGE_WIDTH, yr * IMAGE_HEIGHT
    half_w = width_ratio * IMAGE_WIDTH / 2
    half_h = height_px / 2
    return {
        "data": text,
        "x": [int(cx - half_w), int(cx + half_w)],
        "y": [int(cy - half_h), int(cy + half_h)],
    }


def region_bbox(text: str, region: str, *, line: int = 0, **kwargs) -> dict:
    """구역 이름으로 텍스트를 배치한다. line 은 아래로 내려가는 줄 번호."""
    xr, yr = REGION_CENTERS[region]
    # 한 줄 높이를 이미지 높이의 1.5% 로 잡는다. _build_lines 의
    # y_tolerance(15px)보다 충분히 커서 줄이 섞이지 않는다.
    return make_bbox(text, xr, yr + line * 0.015, **kwargs)


def write_label(
    tmp_path: Path,
    bboxes: Sequence[dict],
    *,
    identifier: str = "TEST_BL_0001",
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
    form_type: str = "선하증권",
) -> str:
    """라벨 JSON 파일을 만들고 경로를 돌려준다.

    `form_type` 은 메타데이터일 뿐이라는 점에 주의할 것. 파이프라인은 **본문
    판별을 메타데이터보다 우선**하므로(`IntakePipeline._form_type`), 서류
    종류를 바꾸려면 bbox 에 서식 제목도 함께 넣어야 한다.
    """
    payload = {
        "Images": {
            "identifier": identifier,
            "width": width,
            "height": height,
            "form_type": form_type,
        },
        "bbox": list(bboxes),
    }
    path = tmp_path / f"{identifier}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def complete_bl_bboxes(
    *,
    bl_no: str = "HG290309",
    shipper: str = "GAE WOON CO., LTD.",
    consignee: str = "DHHJ FRANCHISING CO., LTD.",
    notify: str = "TRY ENERGY CO., LTD.",
    vessel_line: str = "MSC BIANCA V.112",
    pol: str = "OMA, JAPAN",
    pod: str = "SHINJIMA, JAPAN",
) -> List[dict]:
    """하자 없는 정상 B/L 한 장 분량의 bbox 목록."""
    return [
        region_bbox("BILL OF LADING", "header"),
        region_bbox(f"B/L NO {bl_no}", "bl_no"),
        region_bbox(shipper, "shipper", width_ratio=0.30),
        region_bbox(consignee, "consignee", width_ratio=0.30),
        region_bbox(notify, "notify", width_ratio=0.30),
        region_bbox(vessel_line, "vessel_info", width_ratio=0.22),
        region_bbox(pol, "port_left", width_ratio=0.12),
        region_bbox(pod, "port_right", width_ratio=0.12),
        region_bbox("27 PKG CELL ASSEMBLY", "cargo", width_ratio=0.30),
        region_bbox("TOTAL 884 KG", "weight", width_ratio=0.14),
        region_bbox("TOTAL 349.64 CBM", "measurement", width_ratio=0.14),
        region_bbox("FREIGHT PREPAID $1,741.56", "freight", width_ratio=0.30),
        region_bbox("SEOUL, KOREA", "footer", width_ratio=0.20),
        region_bbox("SEP 06, 2006", "footer", line=1, width_ratio=0.20),
    ]


# PDF 지면 크기(A4, 포인트). 라벨 좌표를 **비율로** 옮기므로 실제 값은
# 중요하지 않다. 오히려 라벨 해상도(1654×2340)와 다른 값을 쓰는 편이,
# 구역 판정이 절대 좌표가 아니라 비율로 도는지 함께 검증해 준다.
PDF_PAGE_WIDTH = 595.0
PDF_PAGE_HEIGHT = 842.0


def write_bl_pdf(
    tmp_path: Path,
    bboxes: Sequence[dict],
    name: str = "bl.pdf",
    with_text_layer: bool = True,
) -> str:
    """bbox 목록 → 텍스트 레이어를 가진 PDF.

    라벨 JSON 과 **같은 bbox 목록**으로 만든다. 두 입력이 같은 초안을 내는지
    비교할 수 있어야, PDF 경로가 기존 파서를 제대로 재사용하는지 확인된다.

    `with_text_layer=False` 면 글자를 그리지 않는다. 스캔본(텍스트 레이어
    없음) 판정 경로를 타게 하는 데 쓴다.
    """
    pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF 미설치")

    doc = pymupdf.open()
    page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
    if with_text_layer:
        for item in bboxes:
            text = (item.get("data") or "").strip()
            xs, ys = item.get("x", []), item.get("y", [])
            if not text or not xs or not ys:
                continue
            # 라벨 픽셀 좌표 → 지면 비율 → 포인트.
            x = min(xs) / IMAGE_WIDTH * PDF_PAGE_WIDTH
            # insert_text 는 베이스라인을 받는다. 상자 아래변에 맞춘다.
            y = max(ys) / IMAGE_HEIGHT * PDF_PAGE_HEIGHT
            height = (max(ys) - min(ys)) / IMAGE_HEIGHT * PDF_PAGE_HEIGHT
            page.insert_text(
                (x, y), text, fontsize=max(4.0, height * 0.8), fontname="helv"
            )
    else:
        # 빈 지면이면 PyMuPDF 가 페이지를 만들어도 내용이 없다. 스캔본처럼
        # 보이도록 사각형만 하나 그려 둔다 — 텍스트가 아닌 내용물이다.
        page.draw_rect(pymupdf.Rect(50, 50, 545, 792))

    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def bl_pdf(tmp_path: Path) -> str:
    """모든 핵심 필드가 채워진 정상 B/L PDF (텍스트 레이어 있음)."""
    return write_bl_pdf(tmp_path, complete_bl_bboxes())


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> str:
    """텍스트 레이어가 없는 PDF. OCR 경로로 떨어져야 한다."""
    return write_bl_pdf(tmp_path, [], name="scan.pdf", with_text_layer=False)


@pytest.fixture
def label_factory(tmp_path: Path):
    """bbox 목록 → 라벨 JSON 경로."""

    def _make(bboxes: Sequence[dict], identifier: str = "TEST_BL_0001") -> str:
        return write_label(tmp_path, bboxes, identifier=identifier)

    return _make


@pytest.fixture
def complete_label(label_factory) -> str:
    """모든 핵심 필드가 채워진 정상 B/L 라벨."""
    return label_factory(complete_bl_bboxes())


def paddle_page(
    texts: Sequence[str],
    scores: Optional[Sequence[float]] = None,
    polys: Optional[Sequence[Sequence[Sequence[int]]]] = None,
) -> dict:
    """PaddleOCR 3.x 결과 한 페이지를 흉내낸다.

    3.x 는 dict-like 객체에 rec_texts / dt_polys / rec_scores 를 담아 주며
    extractor 는 `.get()` 으로 접근한다. dict 로 충분히 대체된다.
    """
    if polys is None:
        polys = [
            [[100, 100 + i * 40], [300, 100 + i * 40], [300, 130 + i * 40], [100, 130 + i * 40]]
            for i in range(len(texts))
        ]
    page = {"rec_texts": list(texts), "dt_polys": list(polys)}
    if scores is not None:
        page["rec_scores"] = list(scores)
    return page


# ── 선하증권 외 서류 (6번 서류 세트 확장) ──────────────────────────
#
# 항목명과 값을 별개 bbox 로 둔다. 앵커 파서가 "항목명을 찾아 그 오른쪽·
# 아래를 읽는" 방식이므로, 한 상자에 합쳐 넣으면 파서를 우회해 버린다.

INVOICE_LINES = [
    (0.35, 0.06, "COMMERCIAL INVOICE"),
    (0.05, 0.14, "INVOICE NO"), (0.30, 0.14, "INV-2026-0417"),
    (0.05, 0.18, "INVOICE DATE"), (0.30, 0.18, "2026-06-01"),
    (0.05, 0.24, "SELLER"), (0.30, 0.24, "GAE WOON CO., LTD."),
    (0.05, 0.30, "BUYER"), (0.30, 0.30, "DHHJ FRANCHISING CO., LTD."),
    (0.05, 0.38, "L/C NO"), (0.30, 0.38, "LC-2026-001"),
    (0.05, 0.46, "DESCRIPTION OF GOODS"), (0.40, 0.46, "SAW MACHINE"),
    (0.05, 0.54, "QUANTITY"), (0.30, 0.54, "27 SET"),
    (0.05, 0.60, "PRICE TERM"), (0.30, 0.60, "FOB BUSAN"),
    (0.05, 0.70, "TOTAL AMOUNT"), (0.30, 0.70, "USD 41,250.00"),
]

PACKING_LINES = [
    (0.38, 0.06, "PACKING LIST"),
    (0.05, 0.14, "INVOICE NO"), (0.30, 0.14, "INV-2026-0417"),
    (0.05, 0.18, "DATE"), (0.30, 0.18, "2026-06-01"),
    (0.05, 0.24, "SELLER"), (0.30, 0.24, "GAE WOON CO., LTD."),
    (0.05, 0.30, "BUYER"), (0.30, 0.30, "DHHJ FRANCHISING CO., LTD."),
    (0.05, 0.40, "DESCRIPTION OF GOODS"), (0.40, 0.40, "SAW MACHINE"),
    (0.05, 0.48, "NUMBER OF PACKAGES"), (0.40, 0.48, "27 CTNS"),
    (0.05, 0.54, "GROSS WEIGHT"), (0.35, 0.54, "884.00 KGS"),
    (0.05, 0.60, "NET WEIGHT"), (0.35, 0.60, "812.00 KGS"),
    (0.05, 0.66, "MEASUREMENT"), (0.35, 0.66, "349.64 CBM"),
    (0.05, 0.74, "MARKS AND NUMBERS"), (0.40, 0.74, "DHHJ / BUSAN / NO.1-27"),
]


def lines_to_bboxes(lines) -> List[dict]:
    """(가로비, 세로비, 글자) 목록 → 라벨 JSON bbox 목록."""
    boxes = []
    for xr, yr, text in lines:
        x0 = int(xr * IMAGE_WIDTH)
        y0 = int(yr * IMAGE_HEIGHT)
        width = int(len(text) * 0.011 * IMAGE_WIDTH)
        height = int(0.014 * IMAGE_HEIGHT)
        boxes.append({
            "data": text,
            "x": [x0, x0 + width, x0 + width, x0],
            "y": [y0, y0, y0 + height, y0 + height],
        })
    return boxes


def write_document_pdf(tmp_path: Path, lines, name: str) -> str:
    return write_bl_pdf(tmp_path, lines_to_bboxes(lines), name=name)


@pytest.fixture
def invoice_pdf(tmp_path: Path) -> str:
    """텍스트 레이어를 가진 상업송장 PDF."""
    return write_document_pdf(tmp_path, INVOICE_LINES, "invoice.pdf")


@pytest.fixture
def packing_list_pdf(tmp_path: Path) -> str:
    """텍스트 레이어를 가진 포장명세서 PDF."""
    return write_document_pdf(tmp_path, PACKING_LINES, "packing.pdf")

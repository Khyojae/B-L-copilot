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
) -> str:
    """라벨 JSON 파일을 만들고 경로를 돌려준다."""
    payload = {
        "Images": {
            "identifier": identifier,
            "width": width,
            "height": height,
            "form_type": "선하증권",
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

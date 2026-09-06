"""
OCR 결과 → B/L 필드 추출.

3단계로 동작한다.

1. bbox 를 Y 좌표로 묶어 라인 재조합
2. bbox 를 좌표 구역에 단독 할당 (라인 단위로 묶으면 좌/우 컬럼이 서로 샌다)
3. 구역 텍스트에서 필드별 규칙으로 값 추출. 실패하면 키워드 앵커로 재시도

구역 좌표는 1654×2340 스캔본 실측 기준으로 교정된 값이며 이미지 크기에
비례해 환산한다.

각 필드에는 값과 함께 **신뢰도와 출처**를 남긴다. 기획안 S3(초안 편집기)가
저신뢰 필드만 사람에게 확인받는 흐름을 요구하는데, 어떤 필드가 불확실한지
알 수 없으면 전 필드를 검토하게 되어 F1 의 시간 단축 목표가 무너진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .types import ANCHOR_CONFIDENCE_PENALTY, BBox, BLFields, OCRResult

# 실제 화주명이 아니라 서식 제목·필드 라벨인 라인들. Shipper 구역에서 걸러낸다.
_BL_HEADER_NOISE = (
    "BILL OF LADING", "MULTIMODAL", "NEGOTIABLE", "NON-NEGOTIABLE",
    "FIATA", "WIFFA", "WAYBILL", "COMBINED TRANSPORT", "THROUGH BILL",
    "STRAIGHT BILL", "OCEAN CARRIER", "SEA WAYBILL", "SURRENDER",
    "ORIGINAL", "COPY", "SEAWAY", "FREIGHT FORWARDER",
    "CONSIGNOR/SHIPPER", "CONSIGNOR", "SHIPPER",
)


def _is_header_noise(line: str) -> bool:
    upper = line.upper()
    # 지시식 수하인은 서식 항목명이 아니라 값이다. `TO ORDER OF SHIPPER`,
    # `TO ORDER OF <은행>` 같은 표기가 "SHIPPER" 때문에 노이즈로 버려지면
    # 수하인이 통째로 비고 D005 가 오탐으로 뜬다. L/C 거래 B/L 은 대부분
    # 지시식이라 이 예외가 없으면 정상 서류가 하자로 잡힌다.
    if "TO ORDER" in upper:
        return False
    return any(kw in upper for kw in _BL_HEADER_NOISE)


def _is_valid_date_str(date_str: str) -> bool:
    """추출된 날짜 문자열이 현실적인 범위인지 검사.

    OCR 노이즈(60-55-2708 같은 것)를 사전에 거른다.
    월·일 이름이 들어간 형식은 패턴 자체가 유효성을 보장하므로 통과시킨다.
    """
    s = date_str.strip().upper()

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return 1900 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31

    m = re.match(r"^(\d{2})[-/](\d{2})[-/](\d{4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not 1900 <= y <= 2099:
            return False
        if a > 31 or b > 31:        # 31 초과는 일·월 어느 쪽도 불가
            return False
        if a > 12 and b > 12:       # 둘 다 12 초과면 월 역할을 할 수 없음
            return False
        return True

    return True


@dataclass
class RegionContent:
    """한 구역에 할당된 텍스트와 그 근거 bbox."""

    text: str = ""
    bboxes: List[BBox] = field(default_factory=list)
    # 추출 방식에 따른 신뢰도 보정. 앵커 fallback 은 1.0 미만을 쓴다.
    confidence_factor: float = 1.0

    @property
    def confidence(self) -> float:
        """구역 신뢰도 = 기여한 bbox 신뢰도의 평균 × 방식 보정."""
        if not self.bboxes:
            return 0.0
        mean = sum(b.confidence for b in self.bboxes) / len(self.bboxes)
        return mean * self.confidence_factor

    def __bool__(self) -> bool:
        return bool(self.text.strip())


class FieldParser:
    """OCRResult → BLFields (교정 좌표 + 키워드 앵커)."""

    # ── 구역 정의: 1654×2340 실측 기준 ────────────────────────────
    REGIONS: Dict[str, Dict[str, Tuple[float, float]]] = {
        # 상단 전체: 서류 제목·헤더
        "header":       {"xr": (0.0,  1.0),  "yr": (0.0,  0.13)},
        # B/L No.: 우측 상단
        "bl_no":        {"xr": (0.50, 0.85), "yr": (0.13, 0.26)},
        # Shipper: 좌측 상단
        "shipper":      {"xr": (0.0,  0.50), "yr": (0.04, 0.17)},
        # Consignee: 좌측
        "consignee":    {"xr": (0.0,  0.50), "yr": (0.16, 0.26)},
        # Notify Party: 좌측 중상단
        "notify":       {"xr": (0.0,  0.50), "yr": (0.25, 0.38)},
        # 선박·항로: 좌측+중앙 (CFS/CY 토큰 위 0.37 시작)
        "vessel_info":  {"xr": (0.0,  0.60), "yr": (0.37, 0.44)},
        # 선적항: 좌측 첫 번째 컬럼
        "port_left":    {"xr": (0.0,  0.28), "yr": (0.40, 0.47)},
        # 양하항: 두 번째 컬럼
        "port_right":   {"xr": (0.28, 0.55), "yr": (0.40, 0.47)},
        # 화물 명세: 중앙
        "cargo":        {"xr": (0.05, 0.68), "yr": (0.50, 0.70)},
        # 총 중량: 화물 우측~하단 (인라인 KG 및 TOTAL 라인 포함)
        "weight":       {"xr": (0.60, 0.82), "yr": (0.50, 0.75)},
        # 총 용적: 화물 우측~하단 (CBM 값 포함)
        "measurement":  {"xr": (0.80, 0.97), "yr": (0.50, 0.75)},
        # 운임·Incoterms: 좌측 하단
        "freight":      {"xr": (0.0,  0.55), "yr": (0.73, 0.87)},
        # 발행지·발행일: 좌측 최하단
        "footer":       {"xr": (0.0,  0.55), "yr": (0.83, 0.97)},
    }

    # ── 키워드 앵커 ───────────────────────────────────────────────
    #
    # 후보는 **구체적인 것부터** 적는다. `_locate_anchor` 가 이 순서대로 찾기
    # 때문에, "SHIP" 을 "VESSEL" 보다 앞에 두면 `Shipper` 항목명이 선박 앵커로
    # 잡힌다("SHIP" 이 "SHIPPER" 의 부분 문자열이다).
    FIELD_ANCHORS: Dict[str, List[str]] = {
        "bl_no": [
            "B/L NO", "BL NO", "B.L.NO", "BILL OF LADING NO",
            "BILL OF LADING NUMBER", "B/L NUMBER",
        ],
        "shipper": [
            "CONSIGNOR/SHIPPER", "SHIPPER/EXPORTER", "CONSIGNOR",
            "SHIPPER", "EXPORTER", "FROM",
        ],
        "consignee": [
            "CONSIGNEE", "TO ORDER OF", "RECEIVER",
        ],
        "notify_party": [
            "NOTIFY PARTY", "NOTIFY ADDRESS", "NOTIFY",
        ],
        "port_of_loading": [
            "PORT OF LOADING", "PORT OF LOAD", "LOADING PORT",
            "POL", "PORT OF SHIPMENT", "PORT OF RECEIPT",
        ],
        "port_of_discharge": [
            "PORT OF DISCHARGE", "PORT OF DISCHARGING", "DISCHARGE PORT",
            "POD", "PLACE OF DELIVERY", "FINAL DESTINATION",
        ],
        "vessel": [
            "VESSEL / VOYAGE NO", "OCEAN VESSEL / VOY", "VESSEL/VOYAGE",
            "VESSEL NAME", "OCEAN VESSEL", "VESSEL", "SHIP",
        ],
        "description_of_goods": [
            "DESCRIPTION OF GOODS", "DESCRIPTION OF PACKAGES AND GOODS",
            "DESCRIPTION OF PACKAGES", "GOODS DESCRIPTION",
        ],
        "gross_weight": [
            "GROSS WEIGHT", "G.W.", "GROSS WT",
        ],
        "measurement": [
            "MEASUREMENT", "CBM", "VOLUME",
        ],
        "place_of_issue": [
            "PLACE AND DATE OF ISSUE", "PLACE OF ISSUE", "ISSUED AT",
        ],
        "total_freight": [
            "TOTAL FREIGHT", "FREIGHT AND CHARGES", "FREIGHT & CHARGES",
            "FREIGHT AMOUNT",
        ],
        "date_of_issue": [
            "DATE OF ISSUE", "DATE ISSUED", "PLACE AND DATE OF ISSUE",
            "DATED", "SIGNED ON",
        ],
        "on_board_date": [
            "SHIPPED ON BOARD DATE", "DATE LADEN ON BOARD", "SHIPPED ON BOARD",
            "LADEN ON BOARD", "ON BOARD DATE", "ON BOARD",
        ],
        "incoterms": [
            "INCOTERMS", "TRADE TERMS", "PRICE TERMS", "DELIVERY TERMS",
        ],
        "no_of_original_bl": [
            "NO. OF ORIGINAL B/L", "NUMBER OF ORIGINAL", "NO. OF ORIGINALS",
            "ORIGINAL B/L",
        ],
    }

    # ── 정규식 ────────────────────────────────────────────────────
    # ── 서식에 인쇄된 항목명 ──────────────────────────────────────
    #
    # `FIELD_ANCHORS` 는 **파서가 fallback 에 쓰는** 항목명이라 일부 필드만
    # 갖는다. 아래는 그 밖에 서식에 흔히 인쇄되는 항목명이며, 파싱에는
    # 쓰지 않는다 — 값에 항목명이 섞여 들어왔는지 판정하는 데만 쓴다
    # (`draft._echoes_label`).
    #
    # 값으로도 등장하는 문구는 넣지 않는다. `FREIGHT PREPAID` 는 항목명처럼
    # 보이지만 실제 운임란의 **값**이므로, 넣으면 정상 값이 오탐된다.
    EXTRA_FORM_LABELS: List[str] = [
        "CONSIGNEE",
        "NOTIFY PARTY",
        "DESCRIPTION OF GOODS",
        "DESCRIPTION OF PACKAGES AND GOODS",
        "NUMBER OF PACKAGES",
        "MARKS AND NUMBERS",
        "GROSS WEIGHT",
        "NET WEIGHT",
        "MEASUREMENT",
        "PLACE OF ISSUE",
        "PLACE OF RECEIPT",
        "TOTAL FREIGHT",
        "FREIGHT AND CHARGES",
        "VOYAGE NO",
        "CONTAINER NO",
        "SEAL NO",
    ]

    RE_DATE = re.compile(
        r"\b("
        r"\d{4}-\d{2}-\d{2}"                                 # 2014-09-15
        r"|\d{2}-\d{2}-\d{4}"                                # 09-11-2015
        r"|\d{2}/\d{2}/\d{4}"                                # 09/11/2015
        r"|\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{4}"
        r"|(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2}[,.]?\s+\d{4}"
        r"|\d{2}-(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-\d{4}"
        r")\b",
        re.IGNORECASE,
    )
    # 선사 접두어는 4자가 표준이지만(HLCU·MAEU) 그 뒤에 선적항 코드가 붙어
    # 글자가 7자까지 이어지는 서식이 있다 — HLCUBUS2608001. 6자로 끊으면
    # 이런 번호가 통째로 안 잡혀 옆 칸의 Booking No. 가 대신 들어온다.
    RE_BL_NO = re.compile(r"\b([A-Z]{2,8}\d{4,12})\b")
    RE_WEIGHT = re.compile(
        r"([\d,]+\.?\d*)\s*(KGS?|KG|MT|M\.T\.|METRIC\s*TONS?)", re.IGNORECASE
    )
    RE_CBM = re.compile(r"([\d,]+\.?\d*)\s*(CBM|M3|CU\.?\s*M)", re.IGNORECASE)
    RE_AMOUNT = re.compile(r"\$\s*([\d,]+\.?\d*)")
    # Incoterms 2020 코드. 코드 뒤에 이어지는 인도장소(줄 끝까지)를 함께 담는다.
    RE_INCOTERMS = re.compile(
        r"\b(?:EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b[^\n]{0,30}"
    )
    # 원본 통수 표기. "THREE (3)" 형태.
    RE_ORIGINAL_COUNT = re.compile(
        r"\b(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\s*\(\d+\)",
        re.IGNORECASE,
    )
    # 운송 유형 코드 — 항구명·선박명 구역에 섞여 들어온다
    RE_PORT_NOISE = re.compile(
        r"\b(?:CY|CFS|FCL|LCL|VIA|TRANSIT|THRU)(?:[/\-]\w+)?\b", re.IGNORECASE
    )
    RE_VESSEL_NOISE = re.compile(r"\b(?:CFS|CY|FCL|LCL)(?:[/\-]\w+)?\b", re.IGNORECASE)
    RE_CONTACT = re.compile(r"(?:TEL|FAX|T\)|F\)|PHONE|MOBILE)[^\n]*", re.IGNORECASE)

    # 컨테이너·화물 추적 코드. B/L 번호로 오인되기 쉽다.
    _CARGO_CODE_PREFIX = "DLSU"
    _BL_NO_MAX_LEN = 16

    # ── 공개 API ──────────────────────────────────────────────────

    # 지면 배치가 없는 입력. 좌표는 있지만 **B/L 서식 위의 위치가 아니라**
    # 그리드·줄 번호를 펼친 것이므로, REGIONS 판정이 엉뚱한 값을 집는다.
    # 실제로 엑셀 B/L 을 구역으로 읽으면 선적항 자리에 양하항·화물명세가
    # 통째로 들어온다 — 그리고 그건 값이 있으므로 앵커 탐색까지 가지 않는다.
    #
    # 이 입력들은 "A열 라벨 / B열 값", "라벨: 값" 한 줄 형태라 앵커의 **오른쪽**
    # 만 봐도 값이 나온다(`same_line`).
    LAYOUTLESS_SOURCES = frozenset({"excel", "email-body"})

    # 구역 좌표를 믿을 수 없는 입력. `REGIONS` 는 라벨 데이터셋(1654×2340
    # 스캔본) 한 종류의 배치에 맞춰 교정한 값이라, 발행사마다 칸 위치가 다른
    # 아래 형식에는 맞을 근거가 없다. 게다가 이 입력들은 신뢰도가 전 필드
    # 1.0 이라 틀려도 `LOW_CONFIDENCE` 로 걸러지지 않는다
    # (`draft._UNCALIBRATED_SOURCES` 와 같은 목록).
    #
    # 그래서 이 형식들은 **앵커를 먼저** 본다. 구역을 아예 끄지는 않는다 —
    # 항목명 없이 값만 인쇄된 서식이 실재하고, 거기서는 구역만이 유일한
    # 단서다. 앵커가 못 찾으면 예전처럼 구역으로 내려간다.
    UNCALIBRATED_SOURCES = frozenset({"pdf-text", "excel", "email-body"})

    def parse(self, ocr: OCRResult) -> BLFields:
        if ocr.source in self.LAYOUTLESS_SOURCES:
            regions: Dict[str, RegionContent] = {}
        else:
            regions = self._extract_regions(ocr)
        return self._map_fields(regions, ocr)

    # ── 1단계: bbox → 라인 재조합 ─────────────────────────────────

    @staticmethod
    def _build_lines(bboxes: List[BBox], y_tolerance: int = 15) -> List[List[BBox]]:
        """Y 좌표가 가까운 bbox 를 같은 라인으로 묶고 X 순 정렬."""
        if not bboxes:
            return []
        ordered = sorted(bboxes, key=lambda b: b.center_y)
        lines: List[List[BBox]] = []
        current: List[BBox] = [ordered[0]]

        for bbox in ordered[1:]:
            if abs(bbox.center_y - current[-1].center_y) <= y_tolerance:
                current.append(bbox)
            else:
                lines.append(sorted(current, key=lambda b: b.x_min))
                current = [bbox]
        lines.append(sorted(current, key=lambda b: b.x_min))
        return lines

    # ── 2단계: bbox 단위 구역 할당 ────────────────────────────────

    def _extract_regions(self, ocr: OCRResult) -> Dict[str, RegionContent]:
        """각 bbox 를 해당 구역에 단독 할당.

        라인 단위로 할당하면 좌우로 나뉜 컬럼(선적항/양하항)이 한 라인으로
        묶여 서로의 값을 오염시킨다. bbox 중심점 기준으로 개별 할당한다.
        """
        w, h = ocr.image_width, ocr.image_height
        buckets: Dict[str, List[BBox]] = {k: [] for k in self.REGIONS}

        for bbox in ocr.bboxes:
            for name, bounds in self.REGIONS.items():
                x1, x2 = bounds["xr"][0] * w, bounds["xr"][1] * w
                y1, y2 = bounds["yr"][0] * h, bounds["yr"][1] * h
                if x1 <= bbox.center_x <= x2 and y1 <= bbox.center_y <= y2:
                    buckets[name].append(bbox)

        regions: Dict[str, RegionContent] = {}
        for name, rbboxes in buckets.items():
            ordered = sorted(rbboxes, key=lambda b: (b.center_y, b.x_min))
            sub_lines = self._build_lines(ordered)
            text = "\n".join(" ".join(b.text for b in ln) for ln in sub_lines)
            regions[name] = RegionContent(text=text, bboxes=rbboxes)
        return regions

    # ── 3단계: 필드 매핑 ──────────────────────────────────────────

    def _map_fields(
        self, regions: Dict[str, RegionContent], ocr: OCRResult
    ) -> BLFields:
        f = BLFields(raw_regions={k: v.text for k, v in regions.items()})
        get = regions.get
        empty = RegionContent()

        def region(name: str) -> RegionContent:
            return get(name) or empty

        # 지면 배치가 없는 입력에서는 앵커 아래쪽을 보지 않는다. 그리드의
        # 아랫줄은 같은 필드의 다음 줄이 아니라 **다른 필드**다.
        same_line = ocr.source in self.LAYOUTLESS_SOURCES

        # 구역 좌표를 못 믿는 형식은 앵커를 먼저 본다. 아래 `resolve` 가
        # 두 경로를 이 순서대로 시도하고, 먼저 값이 나온 쪽을 채택한다.
        anchor_first = ocr.source in self.UNCALIBRATED_SOURCES

        def resolve(
            field_name: str,
            rc: RegionContent,
            extract: Callable[[str], Optional[str]],
            *,
            confidence: Optional[float] = None,
            also: Optional[Callable[[str], Optional[str]]] = None,
        ) -> None:
            """구역·앵커 두 경로에서 값을 뽑아 먼저 성공한 쪽을 채택한다.

            `also` 는 같은 텍스트에서 함께 나오는 두 번째 필드(선박명 옆의
            항차 번호)를 뽑는 함수다. 채택한 경로의 텍스트로만 돌려야
            선박은 앵커에서, 항차는 구역에서 오는 뒤섞임이 생기지 않는다.
            """
            region_conf = rc.confidence if confidence is None else confidence
            anchor_rc = self._find_by_anchor(field_name, ocr.bboxes, same_line)

            attempts = [(rc, "region", region_conf)]
            if anchor_rc is not None:
                attempts.append((anchor_rc, "anchor", anchor_rc.confidence))
            if anchor_first:
                attempts.reverse()

            for source_rc, method, conf in attempts:
                value = extract(source_rc.text)
                if value:
                    f.set_field(field_name, value, conf, method, source_rc.bboxes)
                    if also is not None:
                        extra_name, extra_value = also(source_rc.text)
                        f.set_field(extra_name, extra_value, conf, method, source_rc.bboxes)
                    return

            # 어느 경로에서도 못 찾았다. 근거가 없다는 사실을 남긴다.
            f.set_field(field_name, None, region_conf, "region", rc.bboxes)
            if also is not None:
                f.set_field(also("")[0], None, region_conf, "region", rc.bboxes)

        # ── B/L No. ───────────────────────────────────────────────
        # 구역 경로는 B/L 번호 칸과 머리글을 합쳐서 본다 — 번호가 서식
        # 상단에만 인쇄된 경우가 있다.
        bl_region = region("bl_no")
        header_region = region("header")
        resolve(
            "bl_no",
            RegionContent(
                text=f"{bl_region.text} {header_region.text}",
                bboxes=bl_region.bboxes + header_region.bboxes,
            ),
            self._pick_bl_no,
            confidence=bl_region.confidence or header_region.confidence,
        )

        # ── 화주 / 수하인 / 통지처 ────────────────────────────────
        resolve("shipper", region("shipper"), self._clean_party_name)
        resolve("consignee", region("consignee"), self._clean_party_name)
        resolve("notify_party", region("notify"), self._clean_party_name)

        # ── Vessel / Voyage ───────────────────────────────────────
        def vessel_only(text: str) -> Optional[str]:
            vessel, voyage = self._extract_vessel_voyage(text)
            # 항차만 읽힌 경우에도 이 칸을 채택해야 항차가 버려지지 않는다.
            return vessel or (text.strip()[:100] if voyage else None)

        def voyage_pair(text: str) -> Tuple[str, Optional[str]]:
            return "voyage_no", self._extract_vessel_voyage(text)[1]

        resolve("vessel", region("vessel_info"), vessel_only, also=voyage_pair)

        # ── 선적항 / 양하항 ───────────────────────────────────────
        resolve("port_of_loading", region("port_left"), self._clean_port_name)
        resolve("port_of_discharge", region("port_right"), self._clean_port_name)

        # ── 화물 명세 ─────────────────────────────────────────────
        cargo_region = region("cargo")
        resolve("description_of_goods", cargo_region, self._extract_description)

        # ── 중량 / 용적 ───────────────────────────────────────────
        # TOTAL 라인은 화물 구역에 있는 경우와 별도 컬럼에 있는 경우가 모두 있어
        # 양쪽을 합쳐서 본다. 신뢰도는 두 구역의 평균으로 잡는다.
        weight_region = region("weight")
        resolve(
            "gross_weight",
            RegionContent(
                text=f"{cargo_region.text}\n{weight_region.text}",
                bboxes=cargo_region.bboxes + weight_region.bboxes,
            ),
            self._extract_total_weight,
            confidence=self._merge_confidence(cargo_region, weight_region),
        )
        cbm_region = region("measurement")
        resolve(
            "measurement",
            RegionContent(
                text=f"{cargo_region.text}\n{cbm_region.text}",
                bboxes=cargo_region.bboxes + cbm_region.bboxes,
            ),
            self._extract_total_cbm,
            confidence=self._merge_confidence(cargo_region, cbm_region),
        )

        # ── 날짜 ──────────────────────────────────────────────────
        self._map_dates(f, region("footer"), region("freight"), ocr)

        # ── 발행지 ────────────────────────────────────────────────
        resolve("place_of_issue", region("footer"), self._extract_place_of_issue)

        # ── 운임 ──────────────────────────────────────────────────
        def pick_amount(text: str) -> Optional[str]:
            amount = self.RE_AMOUNT.search(text)
            return f"${amount.group(1)}" if amount else None

        resolve("total_freight", region("freight"), pick_amount)

        # ── Incoterms ─────────────────────────────────────────────
        # 운임란 바로 옆(같은 freight 구역)에 인쇄되는 경우가 많다.
        resolve("incoterms", region("freight"), self._extract_incoterms)

        # ── 원본 통수 ─────────────────────────────────────────────
        resolve("no_of_original_bl", region("footer"), self._extract_original_count)

        # ── 문언·부기 ─────────────────────────────────────────────
        # Charter Party·갑판적재·정정 등은 라벨 박스가 없는 자유 서술이라
        # 구역/앵커로는 위치를 미리 정할 수 없다. 페이지 원문 전체를 그대로
        # 담아 두고, 하자 룰이 문구를 직접 검색한다(D028~D031).
        #
        # 한계: 이 필드에는 다른 필드의 라벨·값도 함께 딸려 들어온다(예:
        # "CONSIGNEE", 화물 명세 원문 등). D028~D031 은 전부 "금지어가
        # 있으면 하자"형이라 이 잡음은 최악의 경우에도 미탐(하자를 놓침)으로만
        # 작용하고 오탐(정상을 하자로 잡음)을 만들지 않는다.
        if ocr.raw_text.strip():
            f.set_field("bl_clauses", ocr.raw_text, 1.0, "region", ocr.bboxes)

        return f

    def _map_dates(
        self,
        f: BLFields,
        footer: RegionContent,
        freight: RegionContent,
        ocr: OCRResult,
    ) -> None:
        """발행일과 선적일(On Board) 추출.

        두 날짜는 같은 구역에 나란히 있는 경우가 많아 위치로 구분한다.
        발행일은 footer 최하단, 선적일은 그보다 위(freight 구역 우선).
        """
        footer_dates = [d for d in self.RE_DATE.findall(footer.text) if _is_valid_date_str(d)]
        freight_dates = [d for d in self.RE_DATE.findall(freight.text) if _is_valid_date_str(d)]

        if footer_dates:
            f.set_field("date_of_issue", footer_dates[-1], footer.confidence, "region", footer.bboxes)

        all_dates = freight_dates + footer_dates
        if len(all_dates) >= 2:
            f.set_field(
                "on_board_date",
                all_dates[0],
                freight.confidence if freight_dates else footer.confidence,
                "region",
                freight.bboxes if freight_dates else footer.bboxes,
            )
        elif all_dates and not f.date_of_issue:
            f.set_field("date_of_issue", all_dates[0], footer.confidence, "region", footer.bboxes)

        # 구역 추출이 실패했으면 앵커로 재시도
        for name in ("date_of_issue", "on_board_date"):
            if getattr(f, name):
                continue
            found = self._find_date_by_anchor(name, ocr.bboxes)
            if found:
                value, confidence, bboxes = found
                f.set_field(name, value, confidence, "anchor", bboxes)

    # ── 키워드 앵커 fallback ──────────────────────────────────────

    def _find_by_anchor(
        self, field_name: str, bboxes: List[BBox], same_line_only: bool = False
    ) -> Optional[RegionContent]:
        """필드 라벨을 찾아 그 오른쪽/아래 텍스트를 수집한다.

        `same_line_only` 는 지면 배치가 없는 입력(엑셀·이메일 본문)에서 켠다.
        B/L 서식에서는 라벨 아래에 값이 오는 배치가 흔하지만, 그리드에서
        **아래 줄은 다른 필드**다. 아래를 함께 담으면 선적항 값에 양하항과
        화물명세가 붙는다.

        어느 방향이든 **다음 항목명을 만나면 거기서 끊는다**. 좌표 창만으로
        자르면 창 크기가 문서 배율에 좌우된다 — PDF 는 글자 높이가 9.6pt,
        스캔본은 30px 라 같은 배수가 전혀 다른 범위를 뜻한다. 실제로 이
        때문에 B/L 번호 자리에 아래 칸의 Booking No. 가 같이 딸려 왔다.
        """
        candidates = self.FIELD_ANCHORS.get(field_name, [])
        anchor = self._locate_anchor(bboxes, candidates)
        if anchor is None:
            return None

        # 배율 무관하게 앵커 자신의 글자 높이를 기준으로 쓴다. 0 은 방어.
        line_height = max(anchor.y_max - anchor.y_min, 1.0)

        same_line = sorted(
            (b for b in bboxes
             if abs(b.center_y - anchor.center_y) <= line_height * 0.7
             and b.x_min > anchor.x_max),
            key=lambda b: b.x_min,
        )
        below = [] if same_line_only else sorted(
            (b for b in bboxes
             if anchor.center_y + line_height * 0.3 < b.center_y
             < anchor.center_y + line_height * 2.5
             and anchor.x_min - line_height <= b.x_min
             <= anchor.x_max + line_height * 4),
            key=lambda b: (b.center_y, b.x_min),
        )

        def take_until_label(seq: List[BBox]) -> List[BBox]:
            out: List[BBox] = []
            for b in seq:
                if self._is_form_label(b.text):
                    break
                out.append(b)
            return out

        picked = (take_until_label(same_line) + take_until_label(below))[:10]
        if not picked:
            return None

        return RegionContent(
            text=" ".join(b.text for b in picked).strip(),
            bboxes=picked,
            confidence_factor=ANCHOR_CONFIDENCE_PENALTY,
        )

    # 항목명 판정용 어휘. 앵커 후보와 서식 항목명을 합치되, 짧은 것
    # (POL·POD·CBM·SHIP·FROM…)은 뺀다 — 값 안에 우연히 들어 있기 쉽다.
    _MIN_STOP_LABEL_LEN = 6
    # 항목명 뒤에 붙는 군더더기 허용치 — "(HS Code)", ":", 단위 표기 정도.
    _STOP_LABEL_SLACK = 12

    @classmethod
    def _stop_labels(cls) -> frozenset:
        cached = cls.__dict__.get("_STOP_LABELS_CACHE")
        if cached is None:
            words = {w for group in cls.FIELD_ANCHORS.values() for w in group}
            words.update(cls.EXTRA_FORM_LABELS)
            # `TO ORDER OF` 는 앵커이면서 **값의 일부**다(지시식 수하인).
            # 중단 항목명으로 두면 앵커 바로 아래의 `TO ORDER OF SHIPPER` 에서
            # 수집이 끊겨 수하인이 항목명째로 구역 경로로 밀려난다.
            words.discard("TO ORDER OF")
            cached = frozenset(
                norm
                for w in words
                if len(norm := re.sub(r"[^A-Z0-9/ ]", "", w.upper()).strip())
                >= cls._MIN_STOP_LABEL_LEN
            )
            cls._STOP_LABELS_CACHE = cached
        return cached

    @classmethod
    def _is_form_label(cls, text: str) -> bool:
        """이 bbox 가 값이 아니라 서식에 인쇄된 항목명인지.

        **앞에서부터** 일치할 때만 항목명으로 본다. 뒤쪽 부분일치까지 인정하면
        통지처 값 "SAME AS CONSIGNEE" 가 CONSIGNEE 항목명으로 오인돼 값이
        통째로 날아간다.
        """
        norm = re.sub(r"[^A-Z0-9/ ]", "", text.upper()).strip()
        if not norm:
            return False
        return any(
            norm.startswith(label) and len(norm) <= len(label) + cls._STOP_LABEL_SLACK
            for label in cls._stop_labels()
        )

    def _find_date_by_anchor(
        self, field_name: str, bboxes: List[BBox]
    ) -> Optional[Tuple[str, float, List[BBox]]]:
        """날짜 앵커 근처에서 날짜 패턴을 찾는다. (값, 신뢰도, 근거 bbox) 반환."""
        # 항목명을 찾았으면 **그 칸 안에서만** 본다.
        #
        # 예전에는 항목명 위아래 60 단위를 훑었는데, 60 이 무엇의 60 인지가
        # 문서마다 달랐다. PDF(pt)에서는 두 칸 위아래까지 닿아서, 발행일 칸이
        # 비어 있는 서류의 발행일에 옆 칸 본선적재일이 그대로 복사됐다 —
        # 없는 날짜를 만들어낸 것이라 하자 검증까지 그대로 흘러간다.
        candidates = self.FIELD_ANCHORS.get(field_name, [])
        if self._locate_anchor(bboxes, candidates) is not None:
            found = self._find_by_anchor(field_name, bboxes)
            if found is None:
                # 항목명은 있는데 칸이 비었다 = 문서에 그 날짜가 없다.
                # 여기서 문서 전체를 뒤지면 옆 칸 날짜를 베껴 오게 된다.
                return None
            dates = [d for d in self.RE_DATE.findall(found.text) if _is_valid_date_str(d)]
            return (dates[-1], found.confidence, found.bboxes) if dates else None

        # 항목명 자체가 없으면 예전처럼 문서 전체에서 날짜를 찾는다.
        nearby = bboxes
        if not nearby:
            return None

        ordered = sorted(nearby, key=lambda b: b.center_y)
        text = " ".join(b.text for b in ordered)
        dates = [d for d in self.RE_DATE.findall(text) if _is_valid_date_str(d)]
        if not dates:
            return None

        mean_conf = sum(b.confidence for b in nearby) / len(nearby)
        return dates[-1], mean_conf * ANCHOR_CONFIDENCE_PENALTY, ordered

    @staticmethod
    def _locate_anchor(
        bboxes: List[BBox], candidates: List[str], normalize: str = r"[^A-Z0-9/ ]"
    ) -> Optional[BBox]:
        """라벨 키워드와 일치하는 bbox 를 찾는다.

        후보를 바깥 루프로 돌린다 — 안쪽으로 돌리면 **문서에 먼저 나오는
        bbox** 가 이기므로, `Shipper` 칸이 `SHIP` 후보에 걸려 선박명 앵커가
        된다. 후보 목록은 구체적인 것부터 적혀 있으니 그 순서를 우선한다.

        같은 후보 안에서는 완전 일치를 부분 일치보다 먼저 본다 — 부분 일치를
        먼저 채택하면 `MEASUREMENT` 후보가 `TOTAL MEASUREMENT` 요약줄에
        걸리는 식으로 항목명 대신 값 줄을 집는다.
        """
        normalized = [(b, re.sub(normalize, "", b.text.upper()).strip()) for b in bboxes]
        for cand in candidates:
            cand_norm = re.sub(normalize, "", cand.upper()).strip()
            if not cand_norm:
                continue
            for bbox, text in normalized:
                if cand_norm == text:
                    return bbox
            for bbox, text in normalized:
                if cand_norm in text:
                    return bbox
        return None

    # ── 필드별 정제 ───────────────────────────────────────────────

    def _pick_bl_no(self, text: str) -> Optional[str]:
        """B/L 번호 후보 중 화물 추적 코드를 걸러낸다."""
        for match in self.RE_BL_NO.findall(text):
            if len(match) <= self._BL_NO_MAX_LEN and not match.startswith(
                self._CARGO_CODE_PREFIX
            ):
                return match
        return None

    def _clean_party_name(self, text: str) -> Optional[str]:
        """Shipper / Consignee / Notify Party 정제.

        연락처 라인과 서식 헤더를 걷어내고 회사명이 든 첫 줄을 고른다.
        """
        if not text or not text.strip():
            return None

        text = self.RE_CONTACT.sub("", text)
        lines = [ln.strip() for ln in re.split(r"\n|(?<=\.)\s{2,}", text) if ln.strip()]

        # 1순위: 법인격 표기가 있는 줄
        for line in lines:
            if _is_header_noise(line):
                continue
            if re.search(r"CO\.|LTD\.|INC\.|CORP\.|LLC|GMBH|PTE\.|PVT\.", line, re.I):
                cleaned = re.sub(r"^[A-Z]{2}\d{6,}\s+", "", line).strip()
                if cleaned:
                    return cleaned[:150]

        # 2순위: 헤더 노이즈가 아닌 첫 유의미한 줄
        for line in lines:
            if _is_header_noise(line):
                continue
            cleaned = re.sub(r"^[A-Z]{2}\d{6,}\s+", "", line).strip()
            if cleaned and len(cleaned) > 3:
                return cleaned[:150]
        return None

    def _clean_port_name(self, text: str) -> Optional[str]:
        """항구명 정제. CITY, COUNTRY 형태를 우선한다."""
        if not text or not text.strip():
            return None

        with_comma: List[str] = []
        without_comma: List[str] = []

        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # 합계·수량 라인
            if re.match(r"^\s*(TOTAL|SAY|\d+\s*PKG|\d+\s*KG)", stripped, re.I):
                continue
            # 원본 매수 표기 (ONE (1), TWO (2))
            if re.match(r"^(?:ONE|TWO|THREE|FOUR|FIVE|SIX)\s*\(\d+\)", stripped, re.I):
                continue

            cleaned = self.RE_PORT_NOISE.sub("", stripped)
            cleaned = re.sub(r"\d[\d,\.]*\s*(?:KGS?|KG|CBM|M3)\b", "", cleaned, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(",").strip()

            if not cleaned or len(cleaned) <= 2:
                continue
            (with_comma if "," in cleaned else without_comma).append(cleaned)

        result = with_comma or without_comma
        return result[0][:80] if result else None

    def _extract_description(self, cargo_text: str) -> Optional[str]:
        """화물 명세 추출. 추적 코드와 수량 접두어를 제거한다."""
        if not cargo_text.strip():
            return None

        goods: List[str] = []
        for line in cargo_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^TOTAL\b", stripped, re.I):
                break
            # 추적 코드만 있는 라인
            if re.match(r"^[A-Z]{1,4}\d{5,}\s*$", stripped, re.I):
                continue
            # 추적 코드 접두어 제거
            stripped = re.sub(r"^[A-Z]{1,4}\d{5,}\s+", "", stripped)

            unit = r"PKG|PCS|CTNS?|ROLLS?|SETS?|BAGS?|BUNDLES?"
            if re.match(rf"^\d+\s*(?:{unit})\b", stripped, re.I):
                item = re.sub(rf"^\d+\s*(?:{unit})\s+", "", stripped, flags=re.I)
                item = re.sub(
                    r",?\s*\d[\d,.]*\s*(?:KGS?|KG|CBM|M3)\b.*$", "", item, flags=re.I
                )
                item = item.strip().rstrip(",")
                if item and len(item) > 2:
                    goods.append(item)
            else:
                goods.append(stripped)

        if not goods:
            return None

        seen: set = set()
        unique: List[str] = []
        for g in goods:
            key = g.upper()[:30]
            if key not in seen:
                seen.add(key)
                unique.append(g)

        result = " / ".join(unique)
        return result[:200] or None

    def _extract_total_weight(self, text: str) -> Optional[str]:
        """TOTAL 라인의 중량을 우선 채택."""
        for line in text.split("\n"):
            if re.match(r"^TOTAL\b", line.strip(), re.I):
                m = self.RE_WEIGHT.search(line)
                if m:
                    return f"{m.group(1)} {m.group(2).upper()}"
        matches = list(self.RE_WEIGHT.finditer(text))
        if matches:
            m = matches[-1]
            return f"{m.group(1)} {m.group(2).upper()}"
        return None

    def _extract_total_cbm(self, text: str) -> Optional[str]:
        """TOTAL 라인의 용적을 우선 채택."""
        for line in text.split("\n"):
            if re.match(r"^TOTAL\b", line.strip(), re.I):
                m = self.RE_CBM.search(line)
                if m:
                    return f"{m.group(1)} CBM"
        matches = list(self.RE_CBM.finditer(text))
        if matches:
            return f"{matches[-1].group(1)} CBM"
        return None

    def _extract_vessel_voyage(
        self, text: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """선박명과 항차 번호를 분리한다."""
        if not text.strip():
            return None, None

        text = self.RE_VESSEL_NOISE.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()

        m = re.search(
            r"(?:M/?V|S/?S|VESSEL|OCEAN\s+VESSEL)\s+([A-Z][A-Z\s\-\.]+?)"
            r"(?:\s+V\.?\s*(\w+))?$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            return m.group(1).strip(), m.group(2)

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return None, None

        first = lines[0]

        # "HMM ALGECIRAS / 2608E" — 항목명이 "Vessel / Voyage No." 인 서식이
        # 흔해서 값도 슬래시로 붙어 나온다. 아래 `V.123` 패턴은 이걸 못 잡아
        # 선박명 칸에 항차까지 들어가고 항차는 빈 채로 남는다.
        slash = re.match(r"^(.+?)\s*/\s*([A-Z0-9\-]{2,10})$", first, re.IGNORECASE)
        if slash:
            return slash.group(1).strip() or None, slash.group(2).strip()

        voyage_m = re.search(r"\bV\.?(\w+)\b", first)
        voyage = voyage_m.group(0) if voyage_m else None
        head = first[: voyage_m.start()].strip() if voyage_m else first
        vessel = " ".join(head.split()[:4]) if head else None
        return vessel or None, voyage

    def _extract_place_of_issue(self, footer_text: str) -> Optional[str]:
        """발행지 추출. 날짜와 연락처를 제거한 뒤 대문자 지명을 찾는다."""
        text = self.RE_DATE.sub("", footer_text)
        text = self.RE_CONTACT.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()

        m = re.search(r"([A-Z][A-Z\s,\.]+)", text)
        if m:
            place = m.group(1).strip().strip(",")
            if len(place) > 2:
                return place[:80]
        return None

    def _extract_incoterms(self, text: str) -> Optional[str]:
        """Incoterms 코드 추출. "FOB BUSAN" 처럼 코드+인도장소를 함께 담는다."""
        if not text or not text.strip():
            return None
        m = self.RE_INCOTERMS.search(text)
        if not m:
            return None
        value = re.sub(r"\s+", " ", m.group(0)).strip()
        return value[:40] or None

    def _extract_original_count(self, text: str) -> Optional[str]:
        """원본 통수 추출. "THREE (3)" 형태의 표기를 찾는다."""
        if not text or not text.strip():
            return None
        m = self.RE_ORIGINAL_COUNT.search(text)
        if not m:
            return None
        return re.sub(r"\s+", " ", m.group(0)).strip().upper()[:20]

    @staticmethod
    def _merge_confidence(*regions: RegionContent) -> float:
        """여러 구역에서 값을 합쳐 뽑을 때의 신뢰도."""
        present = [r for r in regions if r.bboxes]
        if not present:
            return 0.0
        return sum(r.confidence for r in present) / len(present)

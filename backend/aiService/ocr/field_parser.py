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
from typing import Dict, List, Optional, Tuple

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

    # ── 키워드 앵커: 구역 기반 실패 시 fallback ────────────────────
    FIELD_ANCHORS: Dict[str, List[str]] = {
        "bl_no": [
            "B/L NO", "BL NO", "B.L.NO", "BILL OF LADING NO",
            "BILL OF LADING NUMBER", "B/L NUMBER",
        ],
        "shipper": [
            "CONSIGNOR/SHIPPER", "SHIPPER/EXPORTER", "CONSIGNOR",
            "SHIPPER", "EXPORTER", "FROM",
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
            "VESSEL", "VESSEL NAME", "OCEAN VESSEL", "SHIP",
            "OCEAN VESSEL / VOY", "VESSEL/VOYAGE",
        ],
        "date_of_issue": [
            "DATE OF ISSUE", "DATE ISSUED", "PLACE AND DATE OF ISSUE",
            "DATED", "SIGNED ON",
        ],
        "on_board_date": [
            "ON BOARD", "SHIPPED ON BOARD", "LADEN ON BOARD",
            "DATE LADEN ON BOARD", "ON BOARD DATE",
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
    RE_BL_NO = re.compile(r"\b([A-Z]{2,6}\d{4,12})\b")
    RE_WEIGHT = re.compile(
        r"([\d,]+\.?\d*)\s*(KGS?|KG|MT|M\.T\.|METRIC\s*TONS?)", re.IGNORECASE
    )
    RE_CBM = re.compile(r"([\d,]+\.?\d*)\s*(CBM|M3|CU\.?\s*M)", re.IGNORECASE)
    RE_AMOUNT = re.compile(r"\$\s*([\d,]+\.?\d*)")
    # 운송 유형 코드 — 항구명·선박명 구역에 섞여 들어온다
    RE_PORT_NOISE = re.compile(
        r"\b(?:CY|CFS|FCL|LCL|VIA|TRANSIT|THRU)(?:[/\-]\w+)?\b", re.IGNORECASE
    )
    RE_VESSEL_NOISE = re.compile(r"\b(?:CFS|CY|FCL|LCL)(?:[/\-]\w+)?\b", re.IGNORECASE)
    RE_CONTACT = re.compile(r"(?:TEL|FAX|T\)|F\)|PHONE|MOBILE)[^\n]*", re.IGNORECASE)

    # 컨테이너·화물 추적 코드. B/L 번호로 오인되기 쉽다.
    _CARGO_CODE_PREFIX = "DLSU"
    _BL_NO_MAX_LEN = 12

    # ── 공개 API ──────────────────────────────────────────────────

    # 지면 배치가 없는 입력. 좌표는 있지만 **B/L 서식 위의 위치가 아니라**
    # 그리드·줄 번호를 펼친 것이므로, REGIONS 판정이 엉뚱한 값을 집는다.
    # 실제로 엑셀 B/L 을 구역으로 읽으면 선적항 자리에 양하항·화물명세가
    # 통째로 들어온다 — 그리고 그건 값이 있으므로 앵커 탐색까지 가지 않는다.
    #
    # 이 입력들은 "A열 라벨 / B열 값", "라벨: 값" 형태라 앵커가 정확하다.
    # 구역을 건너뛰면 모든 필드가 앵커 경로로 떨어진다.
    LAYOUTLESS_SOURCES = frozenset({"excel", "email-body"})

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

        # ── B/L No. ───────────────────────────────────────────────
        bl_region = region("bl_no")
        header_region = region("header")
        bl_no = self._pick_bl_no(f"{bl_region.text} {header_region.text}")
        if bl_no:
            f.set_field("bl_no", bl_no, bl_region.confidence or header_region.confidence, "region")
        else:
            found = self._find_by_anchor("bl_no", ocr.bboxes, same_line)
            if found:
                bl_no = self._pick_bl_no(found.text)
                if bl_no:
                    f.set_field("bl_no", bl_no, found.confidence, "anchor")

        # ── Shipper ───────────────────────────────────────────────
        shipper_region = region("shipper")
        shipper = self._clean_party_name(shipper_region.text)
        if shipper:
            f.set_field("shipper", shipper, shipper_region.confidence, "region")
        else:
            found = self._find_by_anchor("shipper", ocr.bboxes, same_line)
            if found:
                value = self._clean_party_name(found.text) or found.text.strip()[:150]
                f.set_field("shipper", value or None, found.confidence, "anchor")

        # ── Consignee / Notify Party ──────────────────────────────
        for field_name, region_name in (
            ("consignee", "consignee"),
            ("notify_party", "notify"),
        ):
            rc = region(region_name)
            value = self._clean_party_name(rc.text)
            if value:
                f.set_field(field_name, value, rc.confidence, "region")
                continue
            # 구역이 비면 앵커로 찾는다. 구역만 보던 시절에는 지면 배치가
            # 없는 입력(엑셀·이메일 본문)에서 이 두 필드가 항상 비었다.
            found = self._find_by_anchor(field_name, ocr.bboxes, same_line)
            if found:
                cleaned = self._clean_party_name(found.text) or found.text.strip()[:150]
                f.set_field(field_name, cleaned or None, found.confidence, "anchor")

        # ── Vessel / Voyage ───────────────────────────────────────
        vessel_region = region("vessel_info")
        vessel, voyage = self._extract_vessel_voyage(vessel_region.text)
        if vessel or voyage:
            f.set_field("vessel", vessel, vessel_region.confidence, "region")
            f.set_field("voyage_no", voyage, vessel_region.confidence, "region")
        else:
            found = self._find_by_anchor("vessel", ocr.bboxes, same_line)
            if found:
                vessel, voyage = self._extract_vessel_voyage(found.text)
                f.set_field("vessel", vessel or found.text.strip()[:100],
                            found.confidence, "anchor")
                f.set_field("voyage_no", voyage, found.confidence, "anchor")

        # ── 선적항 / 양하항 ───────────────────────────────────────
        for field_name, region_name in (
            ("port_of_loading", "port_left"),
            ("port_of_discharge", "port_right"),
        ):
            rc = region(region_name)
            port = self._clean_port_name(rc.text) if rc else None
            if port:
                f.set_field(field_name, port, rc.confidence, "region")
            else:
                found = self._find_by_anchor(field_name, ocr.bboxes, same_line)
                if found:
                    f.set_field(
                        field_name,
                        self._clean_port_name(found.text),
                        found.confidence,
                        "anchor",
                    )

        # ── 화물 명세 ─────────────────────────────────────────────
        cargo_region = region("cargo")
        f.set_field(
            "description_of_goods",
            self._extract_description(cargo_region.text),
            cargo_region.confidence,
            "region",
        )

        # ── 중량 / 용적 ───────────────────────────────────────────
        # TOTAL 라인은 화물 구역에 있는 경우와 별도 컬럼에 있는 경우가 모두 있어
        # 양쪽을 합쳐서 본다. 신뢰도는 두 구역의 평균으로 잡는다.
        weight_region = region("weight")
        f.set_field(
            "gross_weight",
            self._extract_total_weight(f"{cargo_region.text}\n{weight_region.text}"),
            self._merge_confidence(cargo_region, weight_region),
            "region",
        )
        cbm_region = region("measurement")
        f.set_field(
            "measurement",
            self._extract_total_cbm(f"{cargo_region.text}\n{cbm_region.text}"),
            self._merge_confidence(cargo_region, cbm_region),
            "region",
        )

        # ── 날짜 ──────────────────────────────────────────────────
        self._map_dates(f, region("footer"), region("freight"), ocr)

        # ── 발행지 ────────────────────────────────────────────────
        footer_region = region("footer")
        f.set_field(
            "place_of_issue",
            self._extract_place_of_issue(footer_region.text),
            footer_region.confidence,
            "region",
        )

        # ── 운임 ──────────────────────────────────────────────────
        freight_region = region("freight")
        amount = self.RE_AMOUNT.search(freight_region.text)
        f.set_field(
            "total_freight",
            f"${amount.group(1)}" if amount else None,
            freight_region.confidence,
            "region",
        )

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
            f.set_field("date_of_issue", footer_dates[-1], footer.confidence, "region")

        all_dates = freight_dates + footer_dates
        if len(all_dates) >= 2:
            f.set_field(
                "on_board_date",
                all_dates[0],
                freight.confidence if freight_dates else footer.confidence,
                "region",
            )
        elif all_dates and not f.date_of_issue:
            f.set_field("date_of_issue", all_dates[0], footer.confidence, "region")

        # 구역 추출이 실패했으면 앵커로 재시도
        for name in ("date_of_issue", "on_board_date"):
            if getattr(f, name):
                continue
            found = self._find_date_by_anchor(name, ocr.bboxes)
            if found:
                f.set_field(name, found[0], found[1], "anchor")

    # ── 키워드 앵커 fallback ──────────────────────────────────────

    def _find_by_anchor(
        self, field_name: str, bboxes: List[BBox], same_line_only: bool = False
    ) -> Optional[RegionContent]:
        """필드 라벨을 찾아 그 오른쪽/아래 텍스트를 수집한다.

        `same_line_only` 는 지면 배치가 없는 입력(엑셀·이메일 본문)에서 켠다.
        B/L 서식에서는 라벨 아래에 값이 오는 배치가 흔하지만, 그리드에서
        **아래 줄은 다른 필드**다. 아래를 함께 담으면 선적항 값에 양하항과
        화물명세가 붙는다.
        """
        candidates = self.FIELD_ANCHORS.get(field_name, [])
        anchor = self._locate_anchor(bboxes, candidates)
        if anchor is None:
            return None

        line_height = max(anchor.y_max - anchor.y_min, 20)
        values = [
            b
            for b in bboxes
            if (
                # 같은 라인의 오른쪽
                (abs(b.center_y - anchor.center_y) <= line_height * 0.7
                 and b.x_min > anchor.x_max)
                # 또는 바로 아래 한두 줄
                or (not same_line_only
                    and anchor.center_y + line_height * 0.3 < b.center_y
                    < anchor.center_y + line_height * 2.5
                    and anchor.x_min - line_height <= b.x_min
                    <= anchor.x_max + line_height * 4)
            )
        ]
        if not values:
            return None

        values.sort(key=lambda b: (b.center_y, b.x_min))
        picked = values[:10]
        return RegionContent(
            text=" ".join(b.text for b in picked).strip(),
            bboxes=picked,
            confidence_factor=ANCHOR_CONFIDENCE_PENALTY,
        )

    def _find_date_by_anchor(
        self, field_name: str, bboxes: List[BBox]
    ) -> Optional[Tuple[str, float]]:
        """날짜 앵커 근처에서 날짜 패턴을 찾는다. (값, 신뢰도) 반환."""
        candidates = self.FIELD_ANCHORS.get(field_name, [])
        anchor = self._locate_anchor(bboxes, candidates, normalize=r"[^A-Z ]")

        nearby = (
            bboxes
            if anchor is None
            else [b for b in bboxes if abs(b.center_y - anchor.center_y) < 60]
        )
        if not nearby:
            return None

        ordered = sorted(nearby, key=lambda b: b.center_y)
        text = " ".join(b.text for b in ordered)
        dates = [d for d in self.RE_DATE.findall(text) if _is_valid_date_str(d)]
        if not dates:
            return None

        mean_conf = sum(b.confidence for b in nearby) / len(nearby)
        return dates[-1], mean_conf * ANCHOR_CONFIDENCE_PENALTY

    @staticmethod
    def _locate_anchor(
        bboxes: List[BBox], candidates: List[str], normalize: str = r"[^A-Z0-9/ ]"
    ) -> Optional[BBox]:
        """라벨 키워드와 일치하는 bbox 를 찾는다."""
        for bbox in bboxes:
            text = re.sub(normalize, "", bbox.text.upper()).strip()
            for cand in candidates:
                cand_norm = re.sub(normalize, "", cand.upper()).strip()
                if cand_norm and (cand_norm == text or cand_norm in text):
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

    @staticmethod
    def _merge_confidence(*regions: RegionContent) -> float:
        """여러 구역에서 값을 합쳐 뽑을 때의 신뢰도."""
        present = [r for r in regions if r.bboxes]
        if not present:
            return 0.0
        return sum(r.confidence for r in present) / len(present)

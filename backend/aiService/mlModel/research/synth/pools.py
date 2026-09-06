"""AI Hub 선하증권 OCR 라벨 → 값 분포 풀 추출 (설계서 5.1).

`ai/archive_bl_model_v2` 의 field_parser.py 구역 규칙(REGIONS)과 정규식을 재사용한다.
목적은 정확한 필드 추출이 아니라 **현실적인 값 분포 확보**다 — 완벽할 필요 없다.

1회 실행 후 `ai/f3_research/data/pools/value_pools.json` 에 캐시한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from f3_research import config

# ---------------------------------------------------------------------------
# ai/archive_bl_model_v2/src/field_parser.py 의 REGIONS 를 재사용(좌표계 동일:
# 이미지 1654×2340 기준 정규화 비율). 여기서는 bbox 4점 좌표의 중심점만 쓴다.
# ---------------------------------------------------------------------------
REGIONS: dict[str, dict[str, tuple[float, float]]] = {
    "header": {"xr": (0.0, 1.0), "yr": (0.0, 0.13)},
    "bl_no": {"xr": (0.50, 0.85), "yr": (0.13, 0.26)},
    "shipper": {"xr": (0.0, 0.50), "yr": (0.04, 0.17)},
    "consignee": {"xr": (0.0, 0.50), "yr": (0.16, 0.26)},
    "notify": {"xr": (0.0, 0.50), "yr": (0.25, 0.38)},
    "vessel_info": {"xr": (0.0, 0.60), "yr": (0.37, 0.44)},
    "port_left": {"xr": (0.0, 0.28), "yr": (0.40, 0.47)},
    "port_right": {"xr": (0.28, 0.55), "yr": (0.40, 0.47)},
    "cargo": {"xr": (0.05, 0.68), "yr": (0.50, 0.70)},
    "weight": {"xr": (0.60, 0.82), "yr": (0.50, 0.75)},
    "measurement": {"xr": (0.80, 0.97), "yr": (0.50, 0.75)},
    "freight": {"xr": (0.0, 0.55), "yr": (0.73, 0.87)},
    "footer": {"xr": (0.0, 0.55), "yr": (0.83, 0.97)},
}

RE_WEIGHT = re.compile(r"([\d,]+\.?\d*)\s*(?:KGS?|KG)\b", re.IGNORECASE)
RE_CBM = re.compile(r"([\d,]+\.?\d*)\s*(?:CBM|M3|CU\.?\s*M)\b", re.IGNORECASE)
RE_AMOUNT = re.compile(r"\$\s*([\d,]+\.?\d*)")
RE_REF_CODE = re.compile(r"\b([A-Z]{1,4}\d{5,10})\b")  # BL번호·컨테이너번호류 표기 패턴
RE_CONTACT = re.compile(r"(?:TEL|FAX|T\)|F\)|PHONE|MOBILE)[^A-Za-z]*.*$", re.IGNORECASE)
RE_COMPANY_SUFFIX = re.compile(r"CO\.|LTD\.|INC\.|CORP\.|LLC|GMBH|PTE\.|PVT\.", re.IGNORECASE)
RE_NOISE_TOKEN = re.compile(r"\b(?:CY|CFS|FCL|LCL|VIA|TRANSIT|THRU)(?:[/\-]\w+)?\b", re.IGNORECASE)
RE_QTY_WORD = re.compile(r"^\d+\s*(PKG|PCS|CTNS?|ROLLS?|SETS?|BAGS?|BUNDLES?)\b", re.IGNORECASE)

MAX_POOL_SIZE = 4000


@dataclass
class ValuePools:
    company_names: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    vessels: list[str] = field(default_factory=list)
    goods: list[str] = field(default_factory=list)
    weights_kg: list[float] = field(default_factory=list)
    measurements_cbm: list[float] = field(default_factory=list)
    amounts_usd: list[float] = field(default_factory=list)
    reference_codes: list[str] = field(default_factory=list)  # BL번호/컨테이너번호류 패턴
    source_file_count: int = 0

    def to_dict(self) -> dict:
        return {
            "company_names": self.company_names,
            "ports": self.ports,
            "vessels": self.vessels,
            "goods": self.goods,
            "weights_kg": self.weights_kg,
            "measurements_cbm": self.measurements_cbm,
            "amounts_usd": self.amounts_usd,
            "reference_codes": self.reference_codes,
            "source_file_count": self.source_file_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ValuePools":
        return cls(
            company_names=d["company_names"],
            ports=d["ports"],
            vessels=d["vessels"],
            goods=d["goods"],
            weights_kg=d["weights_kg"],
            measurements_cbm=d["measurements_cbm"],
            amounts_usd=d["amounts_usd"],
            reference_codes=d["reference_codes"],
            source_file_count=d["source_file_count"],
        )


def _build_lines(bboxes: list[dict], y_tolerance: float = 15.0) -> list[list[dict]]:
    if not bboxes:
        return []
    sorted_bboxes = sorted(bboxes, key=lambda b: b["_cy"])
    lines: list[list[dict]] = [[sorted_bboxes[0]]]
    for bbox in sorted_bboxes[1:]:
        if abs(bbox["_cy"] - lines[-1][-1]["_cy"]) <= y_tolerance:
            lines[-1].append(bbox)
        else:
            lines[-1] = sorted(lines[-1], key=lambda b: b["_cx"])
            lines.append([bbox])
    lines[-1] = sorted(lines[-1], key=lambda b: b["_cx"])
    return lines


def _extract_regions(bboxes: list[dict], width: float, height: float) -> dict[str, str]:
    region_bboxes: dict[str, list[dict]] = {k: [] for k in REGIONS}
    for bbox in bboxes:
        for name, bounds in REGIONS.items():
            x1, x2 = bounds["xr"][0] * width, bounds["xr"][1] * width
            y1, y2 = bounds["yr"][0] * height, bounds["yr"][1] * height
            if x1 <= bbox["_cx"] <= x2 and y1 <= bbox["_cy"] <= y2:
                region_bboxes[name].append(bbox)
                break  # 구역은 배타적으로 할당(중첩 시 첫 매칭)
    result: dict[str, str] = {}
    for name, items in region_bboxes.items():
        lines = _build_lines(items)
        result[name] = "\n".join(" ".join(b["data"] for b in ln) for ln in lines)
    return result


def _clean_company_name(text: str) -> str | None:
    if not text.strip():
        return None
    text = RE_CONTACT.sub("", text)
    for line in re.split(r"\n", text):
        line = line.strip()
        if not line:
            continue
        if RE_COMPANY_SUFFIX.search(line):
            line = re.sub(r"^[A-Z]{2}\d{5,}\s+", "", line)
            if len(line) > 3:
                return line[:150]
    return None


def _clean_port_name(text: str) -> str | None:
    candidates_comma: list[str] = []
    candidates_plain: list[str] = []
    for ln in text.split("\n"):
        stripped = ln.strip()
        if not stripped or re.match(r"^(TOTAL|SAY|\d+\s*PKG|\d+\s*KG)", stripped, re.I):
            continue
        if re.match(r"^(?:ONE|TWO|THREE|FOUR|FIVE|SIX)\s*\(\d+\)", stripped, re.I):
            continue
        cleaned = RE_NOISE_TOKEN.sub("", stripped)
        cleaned = re.sub(r"\d[\d,.]*\s*(?:KGS?|KG|CBM|M3)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(",").strip()
        if len(cleaned) <= 2:
            continue
        (candidates_comma if "," in cleaned else candidates_plain).append(cleaned)
    result = candidates_comma or candidates_plain
    return result[0][:80] if result else None


def _extract_goods(cargo_text: str) -> str | None:
    lines_out: list[str] = []
    for ln in cargo_text.split("\n"):
        stripped = ln.strip()
        if not stripped or re.match(r"^TOTAL\b", stripped, re.I):
            continue
        stripped = re.sub(r"^[A-Z]{1,4}\d{5,}\s+", "", stripped)
        if RE_QTY_WORD.match(stripped):
            item = RE_QTY_WORD.sub("", stripped).strip()
            item = re.sub(r",?\s*\d[\d,.]*\s*(?:KGS?|KG|CBM|M3)\b.*$", "", item, flags=re.I)
            item = item.strip().rstrip(",")
            if len(item) > 2:
                lines_out.append(item)
    return lines_out[0][:150] if lines_out else None


def _extract_vessel(text: str) -> str | None:
    text = RE_NOISE_TOKEN.sub("", text).strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None
    first = lines[0]
    words = first.split()
    # 앞의 항구명·V.NNN 항차번호 토큰을 제외하고 알파벳 위주 토큰만 선박명으로 취급
    name_words = [w for w in words if re.match(r"^[A-Z][A-Z.\-]*$", w)]
    return " ".join(name_words[:4])[:80] if name_words else None


def build_pools(limit: int | None = None) -> ValuePools:
    """AI Hub 라벨 디렉토리를 순회해 값 분포 풀을 만든다.

    경로가 없으면 명확한 에러로 종료한다(설계서 2절 요구사항).
    """
    label_dir = config.AI_HUB_LABEL_DIR
    if not label_dir.is_dir():
        raise FileNotFoundError(
            f"AI Hub 선하증권 라벨 디렉토리를 찾을 수 없습니다: {label_dir}\n"
            "환경변수 AI_HUB_BL_LABEL_DIR 로 실제 경로를 지정하세요."
        )
    files = sorted(label_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"{label_dir} 에 라벨 JSON 파일이 없습니다.")
    if limit is not None:
        files = files[:limit]

    pools = ValuePools()
    company_seen: set[str] = set()
    port_seen: set[str] = set()
    vessel_seen: set[str] = set()
    goods_seen: set[str] = set()
    ref_seen: set[str] = set()

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        images = doc.get("Images", {})
        width = float(images.get("width") or 1654)
        height = float(images.get("height") or 2340)
        raw_bboxes = doc.get("bbox", [])
        if not raw_bboxes:
            continue

        bboxes = []
        for b in raw_bboxes:
            xs, ys = b.get("x"), b.get("y")
            text = b.get("data")
            if not xs or not ys or not text:
                continue
            bboxes.append(
                {"data": text, "_cx": sum(xs) / len(xs), "_cy": sum(ys) / len(ys)}
            )
        if not bboxes:
            continue

        regions = _extract_regions(bboxes, width, height)
        full_text = " ".join(b["data"] for b in bboxes)

        for region_name in ("shipper", "consignee", "notify"):
            name = _clean_company_name(regions.get(region_name, ""))
            if name and name.upper() not in company_seen:
                company_seen.add(name.upper())
                pools.company_names.append(name)

        for region_name in ("port_left", "port_right"):
            port = _clean_port_name(regions.get(region_name, ""))
            if port and port.upper() not in port_seen:
                port_seen.add(port.upper())
                pools.ports.append(port)

        vessel = _extract_vessel(regions.get("vessel_info", ""))
        if vessel and vessel.upper() not in vessel_seen:
            vessel_seen.add(vessel.upper())
            pools.vessels.append(vessel)

        goods = _extract_goods(regions.get("cargo", ""))
        if goods and goods.upper() not in goods_seen:
            goods_seen.add(goods.upper())
            pools.goods.append(goods)

        for m in RE_WEIGHT.finditer(full_text):
            try:
                pools.weights_kg.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
        for m in RE_CBM.finditer(full_text):
            try:
                pools.measurements_cbm.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
        for m in RE_AMOUNT.finditer(full_text):
            try:
                pools.amounts_usd.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
        for m in RE_REF_CODE.finditer(full_text):
            code = m.group(1)
            if code not in ref_seen and len(pools.reference_codes) < MAX_POOL_SIZE:
                ref_seen.add(code)
                pools.reference_codes.append(code)

        pools.source_file_count += 1

    # 크기 상한(캐시 파일 비대화 방지) — 수치형은 앞부분만 잘라도 분포 특성은 유지된다.
    pools.weights_kg = pools.weights_kg[:MAX_POOL_SIZE]
    pools.measurements_cbm = pools.measurements_cbm[:MAX_POOL_SIZE]
    pools.amounts_usd = pools.amounts_usd[:MAX_POOL_SIZE]

    return pools


def save_pools(pools: ValuePools, path=None) -> None:
    path = path or config.POOLS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pools.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_pools(path=None) -> ValuePools:
    path = path or config.POOLS_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"값 분포 풀 캐시가 없습니다: {path}\n"
            "먼저 `python -m f3_research.cli build-pools` 를 실행하세요."
        )
    return ValuePools.from_dict(json.loads(path.read_text(encoding="utf-8")))

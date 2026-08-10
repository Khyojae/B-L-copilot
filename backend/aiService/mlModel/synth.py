"""
합성 학습 데이터 생성.

기획안 9절이 리스크로 든 "실제 하자 라벨 데이터 부재 — 은행 심사 기록은
기밀로 확보 불가"에 대한 대응이다. 대응책으로 명시된 "공개 하자 유형(ICC)
기반 합성 주입"을 구현한다.

## 라벨링 방침

라벨은 "은행이 하자로 잡는가"이지 "룰이 걸리는가"가 아니다. 둘을 같게 만들면
모델이 룰의 복제본이 되어 얹을 이유가 없어진다.

그래서 두 종류의 잡음을 의도적으로 넣는다.

- **룰이 못 잡는 하자**: 서류는 멀쩡한데 추출 품질이 나빠 은행 제시 단계에서
  문제가 되는 경우. 저신뢰·앵커 추정이 많은 건에 확률적으로 라벨 1 을 준다.
- **룰이 잡지만 실무상 수리되는 건**: 환적 표시가 있어도 컨테이너 운송이면
  UCP 600 Art.20(c) 로 수리된다. 이런 건에 확률적으로 라벨 0 을 준다.

이 잡음이 모델이 배울 여지다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from ocr.types import BLFields
from ruleEngine.types import LCTerms

# 기준 시각. 합성 데이터는 재현 가능해야 하므로 now() 를 쓰지 않는다.
BASE_DATE = datetime(2026, 6, 1)

PORTS = [
    ("BUSAN, KOREA", "PUSAN"),
    ("INCHEON, KOREA", "INCHON"),
    ("TOKYO, JAPAN", "TOKYO"),
    ("SHANGHAI, CHINA", "SHANGHAI"),
    ("SINGAPORE", "SINGAPORE"),
    ("HAMBURG, GERMANY", "HAMBURG"),
    ("ROTTERDAM, NETHERLANDS", "ROTTERDAM"),
    ("LOS ANGELES, USA", "LOS ANGELES"),
]

COMPANIES = [
    "GAE WOON CO., LTD.",
    "DHHJ FRANCHISING CO., LTD.",
    "TRY ENERGY CO., LTD.",
    "HANSOL LOGISTICS INC.",
    "DAEHAN SHIPPING CORP.",
    "PACIFIC TRADING PTE. LTD.",
]

GOODS = [
    "SAW MACHINE",
    "CELL ASSEMBLY",
    "OPTICAL INSTRUMENTS",
    "STRAP, WEBBING",
    "DRILLING MACHINE",
    "TEXTILE FABRIC",
]

VESSELS = ["MSC BIANCA", "HANJIN SEOUL", "EVER GIVEN", "COSCO PRIDE", "HMM ALGECIRAS"]

INCOTERMS_POOL = ["FOB", "CIF", "CFR", "EXW", "DAP"]


@dataclass
class Sample:
    """합성 서류 1건."""

    bl: BLFields
    lc: LCTerms
    label: int                    # 1 = 은행이 하자로 잡음
    injected: List[str]           # 주입한 하자 유형 (평가·디버그용)
    as_of: datetime = BASE_DATE


# 주입 가능한 하자 유형. ICC 공개 하자 통계에서 빈도가 높은 것들이다.
DEFECT_KINDS = (
    "port_mismatch",        # 선적항/양하항 불일치
    "consignee_mismatch",   # 수하인 불일치
    "late_shipment",        # 선적기한 초과
    "expired",              # 유효기간 경과
    "goods_mismatch",       # 물품 명세 불일치
    "overweight",           # 중량 한도 초과
    "partial_shipment",     # 분할선적 금지 위반
    "missing_field",        # 필수 항목 누락
    "freight_deviation",    # 운임 허용범위 이탈
    "stale_presentation",   # 제시기간 경과
)


class SyntheticGenerator:
    """하자를 주입한 학습 데이터를 만든다."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)

    # ── 생성 ──────────────────────────────────────────────────────

    def generate(
        self,
        count: int,
        defect_ratio: float = 0.5,
    ) -> List[Sample]:
        """count 건을 만든다. defect_ratio 만큼 하자를 주입한다."""
        samples: List[Sample] = []
        for _ in range(count):
            inject = self.rng.random() < defect_ratio
            samples.append(self._make_sample(inject))
        return samples

    def split(
        self,
        count: int,
        defect_ratio: float = 0.5,
        train_ratio: float = 0.7,
    ) -> Tuple[List[Sample], List[Sample]]:
        """학습·검증 세트로 나눈다."""
        samples = self.generate(count, defect_ratio)
        self.rng.shuffle(samples)
        cut = int(len(samples) * train_ratio)
        return samples[:cut], samples[cut:]

    # ── 내부 ─────────────────────────────────────────────────────

    def _make_sample(self, inject: bool) -> Sample:
        bl, lc = self._make_clean_pair()
        injected: List[str] = []

        if inject:
            # 실제 하자 건은 대개 한두 개가 겹친다. 3개 이상은 드물다.
            kinds = self.rng.sample(
                DEFECT_KINDS, k=self.rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
            )
            for kind in kinds:
                self._inject(bl, lc, kind)
                injected.append(kind)

        label = 1 if injected else 0
        label = self._apply_label_noise(bl, label, injected)

        return Sample(bl=bl, lc=lc, label=label, injected=injected)

    def _make_clean_pair(self) -> Tuple[BLFields, LCTerms]:
        """하자 없는 B/L 과 L/C 한 쌍."""
        rng = self.rng
        pol_full, pol_short = rng.choice(PORTS)
        pod_full, pod_short = rng.choice([p for p in PORTS if p[0] != pol_full])
        consignee = rng.choice(COMPANIES)
        shipper = rng.choice([c for c in COMPANIES if c != consignee])
        goods = rng.choice(GOODS)
        incoterm = rng.choice(INCOTERMS_POOL)

        on_board = BASE_DATE - timedelta(days=rng.randint(1, 15))
        latest_shipment = on_board + timedelta(days=rng.randint(5, 30))
        expiry = latest_shipment + timedelta(days=rng.randint(10, 40))

        weight = round(rng.uniform(200, 900), 2)
        freight = round(rng.uniform(800, 4000), 2)

        bl = BLFields(
            bl_no=f"{rng.choice(['HG', 'SEAU', 'MSCU', 'KRPU'])}{rng.randint(100000, 999999)}",
            shipper=shipper,
            consignee=consignee,
            notify_party=rng.choice(COMPANIES),
            vessel=rng.choice(VESSELS),
            voyage_no=f"V.{rng.randint(100, 999)}",
            port_of_loading=pol_full,
            port_of_discharge=pod_full,
            description_of_goods=f"{goods} {incoterm}",
            gross_weight=f"{weight} KG",
            measurement=f"{round(rng.uniform(10, 300), 2)} CBM",
            date_of_issue=_fmt(on_board),
            place_of_issue=pol_short,
            on_board_date=_fmt(on_board),
            total_freight=f"${freight:,.2f}",
        )
        # 추출 신뢰도. 대부분 높고 일부가 낮은 실제 분포를 흉내낸다.
        for name in bl.to_dict():
            if getattr(bl, name):
                bl.confidence[name] = round(rng.betavariate(9, 1), 4)
                bl.provenance[name] = "region" if rng.random() > 0.12 else "anchor"

        lc = LCTerms(
            lc_no=f"LC-{rng.randint(2024, 2026)}-{rng.randint(100, 999)}",
            port_of_loading=pol_short,
            port_of_discharge=pod_short,
            consignee=consignee,
            description_of_goods=goods,
            latest_shipment_date=_fmt(latest_shipment),
            expiry_date=_fmt(expiry),
            max_gross_weight_kg=round(weight * rng.uniform(1.1, 1.5), 2),
            freight_amount=freight,
            incoterms=incoterm,
            partial_shipment=rng.choice(["ALLOWED", "PROHIBITED"]),
            transhipment=rng.choice(["ALLOWED", "PROHIBITED"]),
            documents_required=["COMMERCIAL INVOICE", "PACKING LIST", "BILL OF LADING"],
        )
        return bl, lc

    def _inject(self, bl: BLFields, lc: LCTerms, kind: str) -> None:
        """하자 한 종류를 주입한다."""
        rng = self.rng

        if kind == "port_mismatch":
            other = rng.choice([p for p in PORTS if p[1] != lc.port_of_loading])
            bl.port_of_loading = other[0]

        elif kind == "consignee_mismatch":
            bl.consignee = rng.choice([c for c in COMPANIES if c != lc.consignee])

        elif kind == "late_shipment":
            deadline = parse_or(lc.latest_shipment_date, BASE_DATE)
            bl.on_board_date = _fmt(deadline + timedelta(days=rng.randint(1, 20)))

        elif kind == "expired":
            expiry = parse_or(lc.expiry_date, BASE_DATE)
            bl.date_of_issue = _fmt(expiry + timedelta(days=rng.randint(1, 30)))

        elif kind == "goods_mismatch":
            lc.description_of_goods = f"{lc.description_of_goods}, SPARE PARTS"

        elif kind == "overweight":
            limit = lc.max_gross_weight_kg or 1000.0
            bl.gross_weight = f"{round(limit * rng.uniform(1.05, 1.8), 2)} KG"

        elif kind == "partial_shipment":
            lc.partial_shipment = "PROHIBITED"
            bl.description_of_goods = f"{bl.description_of_goods} PARTIAL SHIPMENT"

        elif kind == "missing_field":
            target = rng.choice(["bl_no", "consignee", "vessel", "notify_party"])
            bl.set_field(target, None, 0.0, "region")

        elif kind == "freight_deviation":
            base = lc.freight_amount or 1000.0
            factor = rng.choice([rng.uniform(0.3, 0.85), rng.uniform(1.15, 2.5)])
            bl.total_freight = f"${base * factor:,.2f}"

        elif kind == "stale_presentation":
            bl.on_board_date = _fmt(BASE_DATE - timedelta(days=rng.randint(22, 60)))

    def _apply_label_noise(
        self, bl: BLFields, label: int, injected: List[str]
    ) -> int:
        """라벨과 룰 결과를 일부러 어긋나게 한다.

        이 잡음이 없으면 라벨이 룰의 결정론적 함수가 되어, 모델이 룰을
        외우는 것 외에 배울 게 없다.
        """
        rng = self.rng

        # 룰은 통과하지만 추출 품질이 나빠 은행 제시에서 문제가 되는 건.
        if label == 0:
            confidences = list(bl.confidence.values())
            mean_conf = sum(confidences) / len(confidences) if confidences else 1.0
            anchored = sum(1 for s in bl.provenance.values() if s == "anchor")
            risk = (1.0 - mean_conf) + anchored * 0.03
            if rng.random() < min(0.30, risk):
                return 1

        # 룰은 걸리지만 실무상 수리되는 건.
        # 환적 표시는 컨테이너 운송이면 UCP 600 Art.20(c) 로 수리된다.
        if label == 1 and injected and all(
            k in {"partial_shipment", "stale_presentation"} for k in injected
        ):
            if rng.random() < 0.20:
                return 0

        return label


# ── 유틸 ─────────────────────────────────────────────────────────

def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def parse_or(value: Optional[str], fallback: datetime) -> datetime:
    from ruleEngine.checks import parse_date

    return parse_date(value) or fallback if value else fallback

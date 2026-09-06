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
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from f1_intake.types import BLFields
from f3_rules.types import LCTerms

from .corpus import BLRecord, CorpusSampler

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


# ── 개발셋 · 평가셋 (기획안 v2 10.3) ─────────────────────────────
#
# "룰 개발에 사용한 선적과 평가에 사용하는 선적을 분리하고, 평가셋은 개발
# 기간 중 열람하지 않는다. 룰엔진은 정답을 보면서 만들면 성능이 자명하게
# 부풀려지므로, 이 분리는 성능 수치의 의미를 지키는 최소 조건이다."
DEV = "dev"
EVAL = "eval"

# 두 세트의 시드 간격.
#
# **1 을 더하면 안 된다.** `--seed 42` 의 평가셋이 `--seed 43` 의 개발셋과
# 같아지고, 시드를 바꿔 가며 평균을 내는 순간(문서의 42~46 평균이 그렇다)
# 분리가 조용히 무너진다. 간격이 시드 범위보다 크면 그 겹침이 생기지 않는다.
_EVAL_SEED_OFFSET = 1_000_003


def seed_for(seed: int, split: str) -> int:
    return seed if split == DEV else seed + _EVAL_SEED_OFFSET


def partition_corpus(
    records: Sequence[BLRecord], split: str
) -> List[BLRecord]:
    """말뭉치도 나눈다. 같은 실물 B/L 이 양쪽에 나오면 분리가 반쪽이 된다.

    2건 미만이면 나눌 수 없어 양쪽이 같은 것을 본다(테스트 픽스처가 그렇다).
    조용히 넘어가지 않도록 `SyntheticGenerator.corpus_shared` 로 알린다.
    """
    if len(records) < 2:
        return list(records)
    return list(records[0::2] if split == DEV else records[1::2])


@dataclass
class Sample:
    """합성 서류 1건."""

    bl: BLFields
    lc: LCTerms
    label: int                    # 1 = 은행이 하자로 잡음
    injected: List[str]           # 주입한 하자 유형 (평가·디버그용)
    as_of: datetime = BASE_DATE
    # 어느 세트에서 나왔는지. 개발셋 표본이 평가 보고에 섞여도 수치는
    # 그럴듯하게 나오므로, 표본 자신이 출처를 들고 다녀야 검사할 수 있다.
    split: str = DEV


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

# 같은 필드에 쓰는 하자 쌍. 함께 주입하면 나중 것이 앞의 것을 덮어쓰는데,
# `injected` 에는 둘 다 남아 서류에 없는 하자를 라벨이 주장하게 된다.
# 그 상태로 유형별 재현율을 재면 검출기가 아니라 생성기의 결함이 측정된다.
#
# late_shipment 는 선적일을 L/C 기한 뒤로(=최근), stale_presentation 은
# 기준일 22~60일 전으로 민다. 둘 다 on_board_date 이고 방향이 반대다.
CONFLICTING_KINDS = (
    ("late_shipment", "stale_presentation"),
)


# 실물 말뭉치에서 기준 서류를 고를 때 다시 뽑아 보는 횟수.
#
# 실물은 지어낸 서류와 달리 룰에 걸리는 것이 섞여 있다 — 항목명이 값에
# 딸려 들어왔거나, 서식이 달라 항구 칸에 엉뚱한 값이 들어온 건들이다.
# 그런 서류를 '하자 없는 기준'으로 쓰면 라벨 0 에 위반이 붙어, 정밀도가
# 데이터 탓으로 떨어지고 그 원인이 보이지 않는다.
#
# 무한 재시도는 하지 않는다. 말뭉치 전체가 룰에 걸리는 상황(룰이 잘못됐거나
# 말뭉치가 이상하거나)에서 조용히 멈추는 대신, 몇 번 시도하고 넘어가되
# `corpus_rejects` 로 세어 드러낸다.
_CLEAN_BASE_TRIES = 10


class SyntheticGenerator:
    """하자를 주입한 학습 데이터를 만든다.

    `corpus` 를 주면 B/L 을 지어내지 않고 **실물 라벨 데이터셋에서 파싱한
    서류**를 쓴다. L/C 는 그 B/L 에서 역산하고, 하자 주입과 라벨링은 그대로다.

    즉 바뀌는 것은 **서류이지 정답이 아니다.** "은행이 반려했다"는 사실은
    어떤 공개 데이터에도 없으므로 라벨은 여전히 합성이다. 이 구분을 흐리면
    발표에서 과장이 된다 (`corpus.py` 머리말의 표).
    """

    def __init__(
        self,
        seed: int = 42,
        corpus: Optional[Sequence[BLRecord]] = None,
        split: str = DEV,
    ) -> None:
        if split not in (DEV, EVAL):
            raise ValueError(f"split 은 {DEV!r} 또는 {EVAL!r} 여야 합니다: {split!r}")
        self.split = split
        self.rng = random.Random(seed_for(seed, split))

        records = partition_corpus(corpus, split) if corpus else []
        # 말뭉치가 작아 양쪽이 같은 서류를 보는 상태. 수치를 인용하기 전에
        # 확인해야 한다.
        self.corpus_shared = bool(corpus) and len(corpus) < 2
        self.sampler = CorpusSampler(records, self.rng) if records else None
        # 실물이라 기준 서류로 못 쓴 건수. 0 이 아니면 말뭉치나 룰을 봐야 한다.
        self.corpus_rejects = 0

    @property
    def uses_corpus(self) -> bool:
        return self.sampler is not None

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

    # 예전에는 한 스트림을 학습·검증으로 잘라 쓰는 `split()` 이 있었다.
    # 그 구조에서는 룰을 고칠 때 본 서류가 곧 평가셋이라 v2 10.3 의 분리
    # 요건을 만족할 수 없다. 세트마다 생성기를 따로 만드는 쪽으로 바꿨다.

    # ── 내부 ─────────────────────────────────────────────────────

    def _make_sample(self, inject: bool) -> Sample:
        bl, lc = self._make_clean_pair()
        injected: List[str] = []

        if inject:
            # 실제 하자 건은 대개 한두 개가 겹친다. 3개 이상은 드물다.
            kinds = _drop_conflicts(
                self.rng.sample(
                    DEFECT_KINDS, k=self.rng.choices([1, 2, 3], weights=[6, 3, 1])[0]
                )
            )
            for kind in kinds:
                self._inject(bl, lc, kind)
                injected.append(kind)

        label = 1 if injected else 0
        label = self._apply_label_noise(bl, label, injected)

        return Sample(
            bl=bl, lc=lc, label=label, injected=injected, split=self.split
        )

    def _make_clean_pair(self) -> Tuple[BLFields, LCTerms]:
        """하자 없는 B/L 과 L/C 한 쌍."""
        if self.sampler is not None:
            pair = self._clean_pair_from_corpus()
            if pair is not None:
                return pair
        return self._invented_clean_pair()

    # ── 실물 말뭉치 경로 ──────────────────────────────────────────

    def _clean_pair_from_corpus(self) -> Optional[Tuple[BLFields, LCTerms]]:
        """실물 B/L 을 골라 L/C 를 역산한다. 룰에 걸리면 다시 뽑는다.

        '하자 없음'의 기준을 키워드 목록이 아니라 **룰엔진 자신**으로 둔다.
        여기에 판정 로직을 복제하면 룰이 늘 때마다(오늘 5건이 늘었다) 두
        곳을 고쳐야 하고, 한쪽을 잊으면 기준 서류에 하자가 섞여 든다.
        """
        engine = _rule_engine()
        for _ in range(_CLEAN_BASE_TRIES):
            record = self.sampler.sample()
            bl = record.to_fields()
            self._reanchor_dates(bl)
            if not bl.no_of_original_bl:
                # 라벨 데이터셋은 이 필드가 생기기 전에 만들어져 원본 통수가
                # 없다. 흔한 표기값으로 채운다 — 안 채우면 D032(원본 통수
                # 미표시) 가 매번 걸려 실물 말뭉치를 통째로 못 쓴다.
                bl.no_of_original_bl = "THREE (3)"
            if not record.confidence_is_real:
                self._redraw_confidence(bl)
            lc = self._derive_lc(bl)
            if not engine.verify(bl, lc, as_of=BASE_DATE).violations:
                return bl, lc
            self.corpus_rejects += 1
        return None

    def _redraw_confidence(self, bl: BLFields) -> None:
        """신뢰도를 다시 뽑는다. **판정 경로(구역/앵커)는 실물 그대로 둔다.**

        라벨 JSON 은 정답 텍스트라 신뢰도가 전 필드 1.0 이다. 그대로 쓰면
        `_apply_label_noise` 의 "룰이 못 잡는 하자" 채널이 죽는다 — 그 잡음은
        낮은 신뢰도에서 나오는데 분산이 0 이기 때문이다.

        채널이 죽으면 라벨이 룰의 결정론적 함수에 가까워져 수치가 좋아진다.
        **데이터가 좋아져서가 아니라 어려운 케이스가 사라져서다.** 실측하면
        룰 단독 F1 이 0.9302 에서 0.9730 으로 뛰는데, 그 상승분은 실력이 아니라
        평가셋이 쉬워진 값이다. 그걸 성과로 보고하면 발표에서 거짓이 된다.

        앵커로 찾은 값에는 추출기와 같은 감점을 준다. 신뢰도만 무작위로 뽑고
        판정 경로를 무시하면 둘이 따로 놀아, `anchor_derived_ratio` 와
        `mean_confidence` 의 상관이 실물과 달라진다.
        """
        from f1_intake.types import ANCHOR_CONFIDENCE_PENALTY

        for name in bl.to_dict():
            if not getattr(bl, name):
                continue
            score = self.rng.betavariate(9, 1)
            if bl.provenance.get(name) == "anchor":
                score *= ANCHOR_CONFIDENCE_PENALTY
            bl.confidence[name] = round(score, 4)

    def _reanchor_dates(self, bl: BLFields) -> None:
        """실물 B/L 의 날짜를 기준 시각 근처로 옮긴다. **형식은 보존한다.**

        실측하면 라벨 데이터셋의 날짜는 2002~2017 년에 흩어져 있고, 더 나쁜
        것은 **서류 안에서도 서로 안 맞는다** — 발행일 2006-09-06 에 선적일
        2013-06-11 같은 건이 흔하다. 원본 서식의 날짜가 채워 넣은 값이지
        실제 거래 기록이 아니기 때문이다.

        그대로 쓰면 300건 전건이 D018(제시기간 경과)에 걸린다. 기준 시각이
        2026 년이므로 당연하고, 그건 서류의 하자가 아니라 **말뭉치와 기준
        시각이 어긋난 것**이다.

        그래서 값은 옮기되 **표기 형식은 그대로 둔다.** `SEP 06, 2006`·
        `16-AUG-2009`·`09-11-2015` 같은 형식 다양성이야말로 합성이 못 만드는
        실물의 성질이고, `parse_date` 의 형식 목록을 실제로 시험하는 것도
        이쪽이다. 값을 realistic 하게 만들려다 형식을 표준화해 버리면 얻으려던
        것을 잃는다.
        """
        on_board = BASE_DATE - timedelta(days=self.rng.randint(1, 15))
        # 발행일은 선적일과 같거나 며칠 뒤다. 본선적재부기가 나중에 붙는
        # 경우가 있어 앞설 수도 있으나, 기준 서류는 단순한 쪽으로 둔다.
        issued = on_board + timedelta(days=self.rng.randint(0, 3))

        for name, moment in (("on_board_date", on_board),
                             ("date_of_issue", issued)):
            original = getattr(bl, name)
            if original:
                setattr(bl, name, _reformat(original, moment))

    def _derive_lc(self, bl: BLFields) -> LCTerms:
        """실물 B/L 에서 그와 맞아떨어지는 L/C 조건을 만든다.

        실제 거래에서는 L/C 가 먼저고 서류가 그에 맞춰 작성되지만, 여기서는
        서류만 실물이므로 방향을 뒤집는다. 목표는 '이 서류가 하자가 아닌
        L/C'를 만드는 것이고, 하자는 그 다음에 `_inject` 가 넣는다.

        **조건을 지어내지 않는다.** B/L 에서 읽을 수 없는 항목은 `None` 으로
        둔다 — 없는 한도를 만들어 넣으면 룰이 실제보다 많이 평가되어
        `skipped_ratio` 가 실물 분포에서 멀어진다. 그 피처를 실물로 만들려고
        말뭉치를 쓰는 것이므로 본말이 뒤집힌다.
        """
        rng = self.rng

        shipped = parse_or(bl.on_board_date or bl.date_of_issue, BASE_DATE)
        latest_shipment = shipped + timedelta(days=rng.randint(5, 30))
        expiry = latest_shipment + timedelta(days=rng.randint(10, 40))

        weight = _parse_kg(bl.gross_weight)
        freight = _parse_money(bl.total_freight)

        # 금지 조건은 서류에 해당 표시가 없을 때만 켠다. 무작위로 켜면
        # 실물 문구에 걸려 기준 서류가 하자가 된다 — 그건 서류의 결함이
        # 아니라 우리가 만든 L/C 의 결함이다.
        text = " ".join(
            v for v in (bl.description_of_goods, bl.port_of_loading,
                        bl.port_of_discharge) if v
        ).upper()

        return LCTerms(
            lc_no=f"LC-{rng.randint(2024, 2026)}-{rng.randint(100, 999)}",
            port_of_loading=_lc_place(bl.port_of_loading),
            port_of_discharge=_lc_place(bl.port_of_discharge),
            consignee=bl.consignee,
            # 실무에서 통지처 지정은 갈린다. D010 이 그 구분으로 켜지고 꺼진다.
            notify_party=bl.notify_party if rng.random() < 0.6 else None,
            description_of_goods=_lc_goods(bl.description_of_goods),
            latest_shipment_date=_fmt(latest_shipment),
            expiry_date=_fmt(expiry),
            max_gross_weight_kg=(round(weight * rng.uniform(1.1, 1.5), 2)
                                 if weight else None),
            freight_amount=freight,
            incoterms=_lc_incoterms(bl.description_of_goods),
            partial_shipment=("PROHIBITED"
                              if rng.random() < 0.5 and "PARTIAL" not in text
                              else "ALLOWED"),
            transhipment=("PROHIBITED"
                          if rng.random() < 0.5 and "TRANSHIP" not in text
                          and "TRANSIT" not in text
                          else "ALLOWED"),
            documents_required=["COMMERCIAL INVOICE", "PACKING LIST",
                                "BILL OF LADING"],
        )

    # ── 지어내는 경로 (말뭉치가 없을 때) ──────────────────────────

    def _invented_clean_pair(self) -> Tuple[BLFields, LCTerms]:
        """하자 없는 B/L 과 L/C 를 처음부터 지어낸다."""
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

        # 통지처는 L/C 가 지정할 수도, 안 할 수도 있다. 실무에서 갈리는
        # 지점이고, D010 이 그 구분에 따라 켜지고 꺼진다. 전건에 지정을 넣으면
        # 조건부 룰을 만들어 놓고 조건이 항상 참인 데이터로 재는 셈이 된다.
        notify_party = rng.choice(COMPANIES)
        lc_notify = notify_party if rng.random() < 0.6 else None

        bl = BLFields(
            bl_no=f"{rng.choice(['HG', 'SEAU', 'MSCU', 'KRPU'])}{rng.randint(100000, 999999)}",
            shipper=shipper,
            consignee=consignee,
            notify_party=notify_party,
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
            no_of_original_bl="THREE (3)",
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
            notify_party=lc_notify,
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
            if target == "notify_party":
                # 통지처 누락은 L/C 가 지정했을 때만 하자다. 지정이 없는 채로
                # 비우고 label=1 을 붙이면 **하자가 아닌 서류를 하자라고 가르치는
                # 것**이 된다. 그 라벨에 맞추려면 룰이 정상 서류를 하자로 잡아야
                # 하므로, 재현율을 올리려는 시도가 정밀도를 무너뜨린다.
                lc.notify_party = lc.notify_party or rng.choice(COMPANIES)

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

def _drop_conflicts(kinds: List[str]) -> List[str]:
    """같은 필드를 두고 다투는 하자 중 뒤에 오는 것을 뺀다.

    표본 순서를 그대로 존중해 앞의 것을 남긴다 — 어느 쪽을 살릴지는
    무작위여야 특정 유형이 과소 표집되지 않는다.
    """
    kept: List[str] = []
    for kind in kinds:
        rivals = {b for a, b in CONFLICTING_KINDS if a == kind}
        rivals |= {a for a, b in CONFLICTING_KINDS if b == kind}
        if rivals & set(kept):
            continue
        kept.append(kind)
    return kept


def _reformat(original: str, moment: datetime) -> str:
    """원본과 **같은 표기 형식**으로 새 날짜를 쓴다.

    형식을 알아내지 못하면 원본을 그대로 둔다. 표준 형식으로 바꿔 버리면
    파서가 실제로 만나는 형식 다양성이 데이터에서 사라진다 — 실물을 쓰는
    이유 중 하나가 그것이다.
    """
    from f3_rules.checks import DATE_FORMATS

    cleaned = re.sub(r"\s+", " ", str(original).strip().upper())
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        return moment.strftime(fmt).upper()
    return original


_RULE_ENGINE = None


def _rule_engine():
    """기준 서류 검증용 룰엔진. 한 번만 만든다 (YAML 파싱이 매번 들어간다)."""
    global _RULE_ENGINE
    if _RULE_ENGINE is None:
        from f3_rules import RuleEngine

        _RULE_ENGINE = RuleEngine()
    return _RULE_ENGINE


def _lc_place(value: Optional[str]) -> Optional[str]:
    """B/L 의 항구 표기에서 L/C 표기를 만든다.

    L/C(44E/44F)는 "BUSAN" 처럼 짧고 서류는 "BUSAN, KOREA" 처럼 길다. 서류
    값을 그대로 복사하면 두 표기가 항상 같아져, `match_place` 의 토큰 비교와
    항구 이명 흡수가 한 번도 실제로 동작하지 않는 데이터가 된다.
    """
    if not value:
        return None
    head = re.split(r"[,/(]", value, maxsplit=1)[0].strip()
    return head or value.strip()


def _lc_goods(value: Optional[str]) -> Optional[str]:
    """B/L 화물 명세에서 L/C 45A 를 만든다.

    `contains_keywords` 가 L/C 값을 쉼표로 잘라 전부 서류에 있는지 본다.
    실물 명세는 "BRUSH BOARD 3 / FCL DELIVERY / SHIPPER'S LOAD..." 처럼
    길고 지저분하므로, 앞쪽 품명 부분만 취한다.

    **낱말을 골라 이어붙이지 않는다.** 그렇게 하면 "MEN'S 100% COTTON" 에서
    "MEN COTTON" 이 나오는데, 그 문자열은 원문에 없으므로 서류가 자기 자신의
    명세와 불일치하는 L/C 가 만들어진다. 실제로 그렇게 짰다가 300건 중
    105건이 D006 에 걸렸다. 원문에 **그대로 있는 연속 구간**만 잘라 쓴다.
    """
    if not value:
        return None
    head = re.split(r"[/\n]", value, maxsplit=1)[0]
    match = re.search(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})?", head)
    return match.group(0).upper() if match else None


def _lc_incoterms(value: Optional[str]) -> Optional[str]:
    """화물 명세에 거래조건이 적혀 있으면 그것을 L/C 조건으로 삼는다.

    없으면 `None` 이다. 지어내면 D015·D026 이 서류에 없는 조건을 요구하게 된다.
    """
    if not value:
        return None
    from f3_rules.checks import INCOTERMS

    upper = value.upper()
    for term in INCOTERMS:
        if re.search(rf"\b{term}\b", upper):
            return term
    return None


def _parse_kg(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    from f3_rules.checks import parse_quantity

    return parse_quantity(value, "KG")


def _parse_money(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    from f3_rules.checks import parse_amount

    amount = parse_amount(value)
    return amount if amount else None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def parse_or(value: Optional[str], fallback: datetime) -> datetime:
    from f3_rules.checks import parse_date

    return parse_date(value) or fallback if value else fallback

"""정합성이 완전한 선적 세트 생성 (설계서 5.2).

선적 1건 = B/L + L/C + 상업송장 + 포장명세서. 내부 정합성이 완전한 상태로 생성한다.
`injector.py` 가 이 결과의 사본을 받아 하자를 주입한다 — generator 자체는 항상
"수리 가능한" 완결 상태만 만든다(정합 제약: DERIVE, SUM, EQ, 일자 순서).

파라미터로 노출: 항로, 컨테이너 수, L/C 조건 복잡도, 거래처, 은행 (기획안 10.3 ②).
시드 고정 — 생성기·주입 규칙·난수 시드를 저장소에 포함해 제3자 재생성 가능하게 한다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from f3_research import config
from f3_research.features import EXTRACTION_CHECKED_FIELDS
from f3_research.schema import (
    DocConsistencyInputs,
    ExtractionQualityInputs,
    HistoryStats,
    LCTerms,
    RuleEngineOutcome,
    ShipmentDates,
    ShipmentSnapshot,
)
from f3_research.synth.pools import ValuePools

REQUIRED_ORIGINAL_COUNT = 3  # 통상적인 B/L 원본 통수 요건(단순화된 상수 가정)

CARGO_TYPES = (
    "ELECTRONICS",
    "TEXTILE",
    "MACHINERY",
    "CHEMICALS",
    "FOOD",
    "AUTOMOTIVE_PARTS",
    "GENERAL_MERCHANDISE",
    "FURNITURE",
)

EXTRACTION_SOURCES = ("pdf", "scan", "json", "manual")
EXTRACTION_SOURCE_WEIGHTS = (0.50, 0.30, 0.15, 0.05)
# 소스별 노이즈 배율 — 스캔본은 OCR 품질이 낮아 필드 신뢰도가 더 흔들린다.
SOURCE_NOISE_MULTIPLIER = {"pdf": 0.6, "scan": 1.6, "json": 0.2, "manual": 1.0}

# ---------------------------------------------------------------------------
# :47A: 조건문 공용 문구 풀 — 검증가능/검증불가 분할 (설계서 §5.3.2, HANDOFF.md 9단계).
#
# 왜 나뉘는가: v3까지는 무하자 건과 인젝터가 **같은 단일 풀**에서 조건을 뽑아,
# "검증불가 조건의 비율"이 주입해도 변하지 않고 조건 "개수"만 변했다(그 개수는
# 이미 lc_47a_condition_count 가 갖고 있어 llm_47a_verifiable_ratio 가 무정보였다).
# 이제 풀을 두 부류로 나누고 무하자/하자가 서로 다른(그러나 겹치는) 혼합비로
# 뽑는다 — sample_47a_conditions()·CLEAN_47A_UNVERIFIABLE_RATIO_RANGE(이 파일)·
# FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE(injector.py) 참고.
#
# 검증가능(verifiable) = 제시된 서류 세트만으로 충족 여부를 확인할 수 있다
# (서류 명사·표기 동사 위주 — BILL OF LADING/INVOICE/CERTIFICATE/PACKING LIST,
# MARKED/STATED/SHOW/EVIDENCE). 검증불가(unverifiable) = 서류 밖의 행위·시점을
# 요구한다(외부 행위 동사 NOTIFY/CONFIRM/ARRANGE/INFORM/ADVISE, 서류 밖 당사자·채널
# BY EMAIL/BY FAX/APPLICANT, 시점 표현 WITHIN...DAYS OF — 실무에서 UCP600
# Art.14(h)가 "비서류적 조건"으로 무시하는 부류와 같은 종류다).
#
# ⚠️ 워터마크 금지(HANDOFF.md 3절이 이미 세 번 잡아낸 함정과 동종): 어느 쪽 풀의
# 문구도 하자에만 등장하지 않는다 — 무하자 건도 두 풀 모두에서 뽑는다(아래
# CLEAN_47A_UNVERIFIABLE_RATIO_RANGE). 길이는 약 40~180자로 자연스럽게 분포한다
# (고정 템플릿 금지).
# ---------------------------------------------------------------------------
LC_47A_VERIFIABLE_POOL: tuple[str, ...] = (
    "BILL OF LADING MUST BE MARKED FREIGHT PREPAID AND CLEAN ON BOARD",
    "PACKING LIST MUST SHOW NET AND GROSS WEIGHT FOR EACH CARTON SEPARATELY",
    "SHIPPING MARKS ON ALL PACKAGES MUST BE IDENTICAL TO THOSE STATED IN THE INVOICE",
    "DOCUMENTS SHOWING A SHORT FORM OR BLANK BACK BILL OF LADING ARE NOT ACCEPTABLE",
    "INVOICE MUST BE MANUALLY SIGNED BY AN AUTHORIZED OFFICER OF THE BENEFICIARY",
    "WEIGHT AND MEASUREMENT CERTIFICATE ISSUED BY AN INDEPENDENT SURVEYOR IS REQUIRED",
    "CERTIFICATE OF ORIGIN MUST BE LEGALIZED BY THE CHAMBER OF COMMERCE",
    "FUMIGATION CERTIFICATE ISSUED BY A GOVERNMENT-APPROVED AGENCY MUST BE PRESENTED",
    "BENEFICIARY CERTIFICATE STATING GOODS ARE OF KOREAN ORIGIN IS REQUIRED",
    "DOCUMENTS MUST BE ISSUED IN ENGLISH ONLY",
    "ALL DOCUMENTS MUST BE PRESENTED IN ONE SET WITHIN THE VALIDITY OF THIS CREDIT",
    "THIRD PARTY DOCUMENTS ARE NOT ACCEPTABLE UNDER THIS CREDIT",
    "A COPY OF THE EXPORT LICENSE MUST ACCOMPANY THE ORIGINAL SHIPPING DOCUMENTS",
    "INSURANCE POLICY MUST COVER INSTITUTE CARGO CLAUSES A INCLUDING WAR RISK",
    "ADDITIONAL CONDITION: BENEFICIARY CERTIFICATE MUST SHOW THE HS CODE OF THE GOODS "
    "AS STATED IN THE COMMERCIAL INVOICE",
    "FURTHER CONDITION: THE BILL OF LADING AND PACKING LIST MUST SHOW IDENTICAL "
    "SHIPPING MARKS AND CONTAINER NUMBERS",
    "PACKING LIST MUST PROVIDE EVIDENCE OF FUMIGATION TREATMENT FOR ALL WOODEN "
    "PACKAGING MATERIALS",
)

LC_47A_UNVERIFIABLE_POOL: tuple[str, ...] = (
    "BENEFICIARY MUST NOTIFY APPLICANT BY EMAIL WITHIN THREE DAYS OF SHIPMENT",
    "PARTIAL SHIPMENT UNDER THIS CREDIT REQUIRES PRIOR WRITTEN APPROVAL FROM THE APPLICANT",
    "FURTHER CONDITION: DOCUMENTS MUST CROSS-REFERENCE PRIOR CORRESPONDENCE DATED "
    "WITHIN THIRTY DAYS OF SHIPMENT",
    "ADDITIONAL CONDITION: BENEFICIARY MUST CERTIFY COMPLIANCE IN FREE TEXT REGARDING "
    "QUALITY INSPECTION PER BUYER SPECIFICATION SHEET",
    "BENEFICIARY MUST ARRANGE PRE-SHIPMENT INSPECTION BY A THIRD PARTY AGENCY "
    "NOMINATED BY THE APPLICANT",
    "BENEFICIARY MUST CONFIRM CONTAINER STUFFING WAS SUPERVISED BY THE APPLICANT'S "
    "REPRESENTATIVE",
    "SHIPPING COMPANY MUST INFORM THE APPLICANT OF THE VESSEL SCHEDULE PRIOR TO LOADING",
    "BENEFICIARY MUST ADVISE THE APPLICANT BY FAX IMMEDIATELY AFTER SHIPMENT",
    "APPLICANT MUST ARRANGE CARGO INSURANCE DIRECTLY WITH A LOCAL INSURER AFTER ARRIVAL",
    "BENEFICIARY MUST INFORM THE ISSUING BANK OF ANY CHANGE IN SHIPPING SCHEDULE "
    "WITHIN TWO DAYS OF SHIPMENT",
    "DISCREPANT DOCUMENTS WILL ONLY BE ACCEPTED SUBJECT TO PRIOR APPROVAL BY THE "
    "ISSUING BANK",
    "BENEFICIARY MUST NOTIFY THE APPLICANT'S BANK BY FAX NOT LATER THAN TWO DAYS "
    "AFTER THE DATE OF SHIPMENT",
)

# 하위호환/참고용 — 두 풀의 합집합. 조건 텍스트 총량 상한 추정(llm_features.py
# `_lc_complexity` 독스트링) 등 "부류 무관하게 존재하는 문구 전체"가 필요한
# 자리에서만 쓴다. 샘플링 자체는 아래 sample_47a_conditions() 가 두 풀을
# 개별적으로 참조한다 — 이 튜플에서 직접 뽑지 않는다.
LC_47A_CONDITION_POOL: tuple[str, ...] = LC_47A_VERIFIABLE_POOL + LC_47A_UNVERIFIABLE_POOL

# 무하자 건의 검증불가 혼합비 범위(설계서 §5.3.2 "중첩 요건"). 하자
# (injector.FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE, 0.3~0.9)와 0.3~0.6 구간에서
# 겹친다 — 하자는 혼합비를 이동시킬 뿐 분리하지 않는다.
CLEAN_47A_UNVERIFIABLE_RATIO_RANGE: tuple[float, float] = (0.0, 0.6)


def sample_47a_conditions(
    rng: random.Random,
    condition_count: int,
    unverifiable_ratio_range: tuple[float, float],
) -> str:
    """:47A: 조건문을 검증가능/검증불가 두 풀에서 혼합비대로 뽑아 합친다.

    `unverifiable_ratio_range`에서 뽑은 혼합비만큼 `LC_47A_UNVERIFIABLE_POOL`에서,
    나머지는 `LC_47A_VERIFIABLE_POOL`에서 채운다. 무하자 건(이 파일,
    `CLEAN_47A_UNVERIFIABLE_RATIO_RANGE`)과 룰 밖 하자 `freeform_47a_unmet`
    (injector.py, `FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE`)이 이 함수를 공유하고
    범위만 달리 넘긴다 — 조건 "개수"가 아니라 "혼합비"가 신호축이다(설계서 §5.3.2).
    """
    if condition_count <= 0:
        return ""
    ratio = rng.uniform(*unverifiable_ratio_range)
    n_unverifiable = min(round(condition_count * ratio), condition_count, len(LC_47A_UNVERIFIABLE_POOL))
    n_verifiable = min(condition_count - n_unverifiable, len(LC_47A_VERIFIABLE_POOL))
    # 두 풀 모두 조건 개수 상한(6)보다 훨씬 크므로 실제로는 일어나지 않지만,
    # 방어적으로 한쪽이 모자라면 다른 쪽에서 채운다.
    shortfall = condition_count - (n_unverifiable + n_verifiable)
    if shortfall > 0:
        n_unverifiable = min(n_unverifiable + shortfall, len(LC_47A_UNVERIFIABLE_POOL))
        shortfall = condition_count - (n_unverifiable + n_verifiable)
    if shortfall > 0:
        n_verifiable = min(n_verifiable + shortfall, len(LC_47A_VERIFIABLE_POOL))
    chosen = rng.sample(LC_47A_UNVERIFIABLE_POOL, k=n_unverifiable) + rng.sample(
        LC_47A_VERIFIABLE_POOL, k=n_verifiable
    )
    rng.shuffle(chosen)
    return "; ".join(chosen)

# ---------------------------------------------------------------------------
# L/C 필드 보강 (설계서 5.3.1 "생성기에 추가할 필드", HANDOFF.md 4단계).
#
# 실제 룰엔진(21룰)이 요구하나 SynthShipment 에 없던 필드들 — 없으면 해당 룰이
# 영구히 같은 값(D001 은 항상 위반, D003/D005B/D006/D002/D007B/D017/D015/D016 은
# 항상 skip)이 되어 XGBoost 에 정보가 0이면서 열만 차지한다.
# ---------------------------------------------------------------------------

# Incoterms 2020 전 조건(11개). D015(Incoterms 미표시) 검사의 lc.incoterms 값이자
# ruleEngine/checks.py::INCOTERMS 와 동일한 코드 집합이다 — 여기서는 채널 독립을
# 지키려고(리뷰어 아님에도 불필요한 결합을 만들지 않으려고) import 하지 않고
# 별도로 유지한다.
INCOTERMS_2020: tuple[str, ...] = (
    "EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
    "CPT", "CIP", "DAP", "DPU", "DDP",
)

# L/C :46A: 요구서류 목록 — BILL OF LADING 은 항상 포함시킨다(D016 이 이걸 찾는다).
# 나머지는 lc_required_doc_count 만큼 이 풀에서 채운다.
_OTHER_REQUIRED_DOCUMENT_TYPES: tuple[str, ...] = (
    "COMMERCIAL INVOICE",
    "PACKING LIST",
    "CERTIFICATE OF ORIGIN",
    "INSURANCE POLICY",
    "BENEFICIARY CERTIFICATE",
    "INSPECTION CERTIFICATE",
    "WEIGHT AND MEASUREMENT CERTIFICATE",
    "FUMIGATION CERTIFICATE",
)

_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 품명·당사자명 표기 변동에 쓰는 약어 대응표(설계서 5.3: "약어·어순·단위 표기 차이").
_WORDING_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("PIECES", "PCS"),
    ("PACKAGES", "PKGS"),
    ("PACKAGE", "PKG"),
    ("CARTONS", "CTNS"),
    ("ELECTRONICS", "ELEC"),
    ("ELECTRONIC", "ELEC"),
    ("MACHINERY", "MACH"),
    ("GENERAL", "GEN"),
    ("MERCHANDISE", "MDSE"),
    ("AUTOMOTIVE", "AUTO"),
    ("CHEMICALS", "CHEM"),
    ("FURNITURE", "FURN"),
    ("ASSORTED", "ASST"),
    ("AND", "&"),
)

_COMPANY_SUFFIX_VARIANTS: tuple[tuple[str, str], ...] = (
    ("CO., LTD.", "CO LTD"),
    ("CO., LTD.", "CO.,LTD."),
    ("CORP.", "CORPORATION"),
    ("INC.", "INCORPORATED"),
    ("PTE. LTD.", "PTE LTD"),
    ("LTD.", "LIMITED"),
)


def _apply_abbreviations(text: str, rng: random.Random, probability: float) -> str:
    words = text.split(" ")
    out = []
    for w in words:
        replaced = w
        for full, abbr in _WORDING_ABBREVIATIONS:
            if w.upper() == full and rng.random() < probability:
                replaced = abbr
                break
        out.append(replaced)
    return " ".join(out)


def _random_char_edits(text: str, rng: random.Random, n_ops: int) -> str:
    chars = list(text) if text else ["X"]
    for _ in range(n_ops):
        op = rng.choice(("sub", "ins", "del", "swap_words"))
        if op == "sub" and chars:
            i = rng.randrange(len(chars))
            if chars[i] != " ":
                chars[i] = rng.choice(_ALPHA)
        elif op == "ins":
            i = rng.randrange(len(chars) + 1)
            chars.insert(i, rng.choice(_ALPHA))
        elif op == "del" and len(chars) > 1:
            i = rng.randrange(len(chars))
            del chars[i]
        elif op == "swap_words":
            words = "".join(chars).split(" ")
            if len(words) > 1:
                i, j = rng.sample(range(len(words)), 2)
                words[i], words[j] = words[j], words[i]
                chars = list(" ".join(words))
    return "".join(chars)


def vary_wording(text: str, rng: random.Random, ratio_range: tuple[float, float]) -> str:
    """품명 표기 변동(약어·어순·문자 편집) — 무하자 기저 변동과 하자 이동에 공용으로
    쓰인다(설계서 5.3 "무하자 건에도 같은 축의 변동을 준다", "하자는 분포를 이동시킬
    뿐 분리하지 않는다"). ratio_range 는 목표 편집 강도(대략치)이며 정확한
    dc_max_edit_distance_ratio 를 보장하지는 않는다 — 자연스러운 겹침을 위한
    의도적 근사치다.
    """
    if not text:
        return text
    varied = _apply_abbreviations(text, rng, probability=0.6)
    ratio = rng.uniform(*ratio_range)
    n_ops = max(0, round(ratio * len(varied)))
    if n_ops:
        varied = _random_char_edits(varied, rng, n_ops)
    return varied


def vary_company_suffix(name: str, rng: random.Random, strength: float) -> str:
    """당사자명 표기 변동(구두점·법인격 약어) — 무하자 건 자연 변동의 근거이자
    `signer_authority_ambiguous` 하자 이동의 축(설계서 5.3)."""
    if not name or rng.random() > strength:
        return name
    varied = name
    for full, alt in _COMPANY_SUFFIX_VARIANTS:
        if full in varied:
            return varied.replace(full, alt)
    return varied.replace(", ", " ").replace(".", "")


def natural_deviation_ratio(
    rng: random.Random,
    base_hi: float,
    extra_hi: float = 0.0,
    extra_beta: tuple[float, float] = (1.0, 5.0),
) -> float:
    """`dc_qty/weight/amount_deviation_ratio` 축의 공용 비율 생성기(HANDOFF.md 4b단계).

    ⚠️ 적대적 검증 실측: 이 세 축은 무하자 건에서 **정확히 0.0000**이었다(B/L 수량이
    포장명세서 합계·중량·송장 금액과 코드상 항상 완전히 같았다) — 하자만 이 축을
    움직이면 자연 변동 없이 결정론적으로 분리되는, HANDOFF.md 3절이 이미 두 번 잡아낸
    것과 같은 종류의 워터마크가 된다(설계서 1절 중첩 요건).

    `base_hi`만 쓰면(무하자 건, `extra_hi=0`) 반올림·계량방식 차이·부대비용 같은
    현실적 사유로 작은 변동(대략 0~5%)을 만든다. `injector.py`(하자 이동)는 같은
    `base_hi` 위에 우측 꼬리가 긴 Beta(1,5) 분포로 `extra_hi`를 더한다 — 대부분의
    하자는 작게 벗어나고 일부만 크게 벗어나는 현실적 모양이며, 하자 최솟값이 여전히
    무하자 상한 근처에 걸쳐 있어 분포가 겹친다(설계서 5.3 "하자는 분포를 이동시킬
    뿐 분리하지 않는다").
    """
    ratio = rng.uniform(0.0, base_hi)
    if extra_hi:
        ratio += rng.betavariate(*extra_beta) * extra_hi
    return ratio


@dataclass
class GeneratorParams:
    """기획안 10.3 ② 노출 파라미터. seed 는 재현성의 근거."""

    seed: int
    base_count: int
    counterparty_pool_size: int = 150
    bank_pool_size: int = 20


@dataclass
class EntityPools:
    """거래처·은행·화물유형 latent 엔티티 — 이력 피처(Group 6) 계산의 근거가 되는 풀.

    `counterparty_propensity`/`cargo_type_propensity`는 엔티티별 잠재 하자 성향
    (설계서 4절 Group 6 규칙 3)이다. `dataset.py`가 이 풀과는 별도로 생성하는
    이력 기간(history period, `generate_history_shipments`)이 이 성향을 실제로
    실현한 관측 비율을 만든다 — X의 행(`generate_base_shipments`)과 이력 기간
    선적은 서로 다른 선적 집합이며, 이력 기간은 X에 절대 들어가지 않는다
    (설계서 4절 Group 6 규칙 1, 라벨 누수 재발 방지).
    """

    counterparty_ids: list[str]
    counterparty_names: dict[str, str]
    counterparty_propensity: dict[str, float]
    bank_ids: list[str]
    bank_strictness: dict[str, float]
    cargo_type_propensity: dict[str, float]


def _draw_multiplier(rng: random.Random, value_range: tuple[float, float]) -> float:
    """Beta(2,2) 표본을 [low, high] 로 스케일한 승수(평균은 (low+high)/2).

    은행 strictness·거래처/화물유형 잠재 성향(설계서 4절 Group 6 규칙 3)이 공유하는
    추출 방식이다. Beta(2,2)는 종형(가장자리 쏠림 없이 평균 근처에 몰리는) 분포라
    극단값이 uniform 보다 드물다.
    """
    low, high = value_range
    return round(low + (high - low) * rng.betavariate(2.0, 2.0), 4)


def build_entity_pools(pools: ValuePools, params: GeneratorParams, rng: random.Random) -> EntityPools:
    names = pools.company_names or ["GENERIC TRADING CO., LTD."]
    counterparty_ids = [f"CP{idx:04d}" for idx in range(params.counterparty_pool_size)]
    counterparty_names = {
        cid: rng.choice(names) for cid in counterparty_ids
    }
    # 거래처별 잠재 하자 성향(설계서 4절 Group 6 규칙 3) — HISTORY 피처군이 정당한
    # 신호를 갖는 유일한 근거. v2는 이 성향이 없어 hist_counterparty_defect_rate 가
    # 누수 운반체로만 존재했다.
    counterparty_propensity = {
        cid: _draw_multiplier(rng, config.COUNTERPARTY_PROPENSITY_RANGE) for cid in counterparty_ids
    }
    bank_ids = [f"BANK{idx:03d}" for idx in range(params.bank_pool_size)]
    bank_strictness = {
        bid: _draw_multiplier(rng, config.BANK_STRICTNESS_RANGE) for bid in bank_ids
    }
    # 화물유형별 잠재 하자 성향(설계서 4절 Group 6 규칙 3).
    cargo_type_propensity = {
        ct: _draw_multiplier(rng, config.CARGO_TYPE_PROPENSITY_RANGE) for ct in CARGO_TYPES
    }
    return EntityPools(
        counterparty_ids,
        counterparty_names,
        counterparty_propensity,
        bank_ids,
        bank_strictness,
        cargo_type_propensity,
    )


@dataclass
class SynthShipment:
    """정합성이 완전한 선적 원시 데이터. injector.py 가 사본을 만들어 오염시킨다."""

    base_shipment_id: str
    shipment_id: str
    counterparty_id: str
    bank_id: str
    bank_strictness: float
    counterparty_propensity: float  # 설계서 4절 Group 6 규칙 3 — 거래처 잠재 하자 성향
    cargo_type: str
    cargo_type_propensity: float  # 설계서 4절 Group 6 규칙 3 — 화물유형 잠재 하자 성향

    bl_no: str  # 설계서 5.3.1 — D001(B/L 번호 누락)의 근거. 없으면 D001 이 항상 위반된다.

    shipper: str
    consignee: str
    invoice_consignee: str
    notify_party: str
    lc_consignee: str | None  # L/C 지정 수하인 — 정상 상태에서는 consignee 와 동일.
    # D005B(수하인 불일치)의 근거 — 이게 없으면 D005B 는 항상 skip 된다(설계서 5.3.1).

    port_of_loading: str
    port_of_discharge: str
    lc_port_of_discharge: str  # L/C :44F: — EQ 제약: 정상 상태에서는 port_of_discharge 와 동일
    lc_port_of_loading: str | None  # L/C :44E: — EQ 제약: 정상 상태에서는 port_of_loading 과 동일.
    # D003(선적항 불일치)의 근거 — 이게 없으면 D003 은 구조적으로 발화할 수 없다(설계서 5.3.1).

    vessel: str
    voyage_no: str

    goods_description: str
    invoice_goods_description: str
    lc_goods_description: str | None  # L/C :45A: — EQ 제약: 정상 상태에서는 goods_description 과 동일.
    # D006(화물 명세 불일치)의 근거.

    package_qty: int
    packing_list_qty_sum: int  # SUM 제약: 정상 상태에서는 package_qty 와 동일

    gross_weight_kg: float
    packing_list_weight_sum: float
    measurement_cbm: float  # 용적(CBM) — D007B(용적 한도 초과)의 근거.

    unit_price_usd: float
    invoice_amount_usd: float  # DERIVE 제약: 정상 상태에서는 package_qty * unit_price_usd
    freight_amount_usd: float  # 운임 — D017(운임 허용범위 이탈)의 근거.

    original_bl_count: int
    required_original_count: int

    # 서류 간 정합성(Group 2)의 "약한 자연 변동" 축. 정상 건도 소액의 확률로
    # 관행 문구·행정 표기 차이를 갖는다 — customary_wording_missing 하자가
    # 이 확률을 이동시킬 뿐 새 신호를 만들지 않는다(설계서 5.3 중첩 요건).
    admin_note_conflict: bool

    lc_present: bool
    lc_required_doc_count: int | None
    lc_documents_required: list[str]  # :46A: 요구서류 목록 — D016(요구서류 목록에 B/L 없음)의 근거.
    lc_47a_text: str
    lc_has_special_clause: bool
    lc_is_transferable: bool
    lc_partial_shipment_allowed: bool
    lc_transshipment_allowed: bool
    lc_amount_tolerance_pct: float
    lc_expiry_date: date | None
    lc_latest_shipment_date: date | None  # :44C: — D002(선적기한 초과)의 근거.
    lc_presentation_period_days: int | None
    lc_max_gross_weight_kg: float | None  # D007(중량 한도 초과)의 근거.
    lc_max_measurement_cbm: float | None  # D007B(용적 한도 초과)의 근거.
    lc_freight_amount: float | None  # D017(운임 허용범위 이탈)의 근거.
    lc_incoterms: str | None  # D015(Incoterms 미표시)의 근거.

    bl_issue_date: date
    onboard_date: date
    presentation_date: date

    extraction_source: str
    field_confidences: dict[str, float] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    no_evidence_fields: list[str] = field(default_factory=list)

    def copy(self) -> "SynthShipment":
        return replace(
            self,
            field_confidences=dict(self.field_confidences),
            missing_fields=list(self.missing_fields),
            no_evidence_fields=list(self.no_evidence_fields),
            lc_documents_required=list(self.lc_documents_required),
        )


def _sample_extraction_quality(
    rng: random.Random, field_accuracy: dict[str, float]
) -> tuple[str, dict[str, float], list[str], list[str]]:
    source = rng.choices(EXTRACTION_SOURCES, weights=EXTRACTION_SOURCE_WEIGHTS, k=1)[0]
    multiplier = SOURCE_NOISE_MULTIPLIER[source]
    confidences: dict[str, float] = {}
    missing: list[str] = []
    no_evidence: list[str] = []
    for f in EXTRACTION_CHECKED_FIELDS:
        acc = field_accuracy.get(f, 0.9)
        # 실측 정확도가 낮을수록(=필드가 흔들릴수록) 신뢰도 노이즈를 키운다(설계서 5.1).
        noise_strength = (1.0 - acc) * multiplier
        conf = max(0.0, min(1.0, rng.gauss(0.97, 0.03) - rng.uniform(0, noise_strength * 3)))
        if conf < 0.15 and rng.random() < 0.5:
            missing.append(f)
            continue
        confidences[f] = round(conf, 4)
        if conf < 0.6 and rng.random() < 0.3:
            no_evidence.append(f)
    return source, confidences, missing, no_evidence


def _build_shipment(
    base_id: str,
    counterparty_id: str,
    bank_id: str,
    cargo_type: str,
    pools: ValuePools,
    entities: EntityPools,
    rng: random.Random,
    field_accuracy: dict[str, float],
) -> SynthShipment:
    """정합성이 완전한 선적 1건을 생성한다.

    `generate_base_shipments`(X의 행이 되는 기준 선적)와 `generate_history_shipments`
    (X에 절대 들어가지 않는 이력 기간 선적, 설계서 4절 Group 6 규칙 1)가 공유하는
    유일한 생성 로직 — 두 경로가 같은 필드 분포·정합 제약을 따라야 이력 기간이
    "같은 모집단에서 뽑은 과거 표본"이라는 전제가 성립한다.
    """
    ports = pools.ports or ["BUSAN, KOREA", "LOS ANGELES, USA"]
    vessels = pools.vessels or ["OCEAN STAR"]
    goods = pools.goods or ["GENERAL CARGO"]
    weights = pools.weights_kg or [500.0]
    amounts = pools.amounts_usd or [5000.0]
    # measurements_cbm/reference_codes 는 이미 ValuePools 에 있던 풀이다(설계서 5.3.1
    # "measurement_cbm 은 이미 값 분포 풀에 있을 수 있다 — 새 풀을 추가하기 전에
    # 확인하라") — pools.py 가 이미 CBM 표기(RE_CBM)와 참조코드(RE_REF_CODE)를 뽑아
    # 두고 있었고, SynthShipment 필드로만 없었을 뿐이다.
    measurements = pools.measurements_cbm or [10.0]
    reference_codes = pools.reference_codes or ["BLKR0000001"]
    epoch = date(2023, 1, 1)

    bank_strictness = entities.bank_strictness[bank_id]
    counterparty_propensity = entities.counterparty_propensity[counterparty_id]
    cargo_type_propensity = entities.cargo_type_propensity[cargo_type]

    pol, pod = rng.sample(ports, 2) if len(ports) >= 2 else (ports[0], ports[0])
    vessel = rng.choice(vessels)
    voyage_no = f"{rng.randint(1, 999):03d}"
    # B/L 번호(설계서 5.3.1) — pools.reference_codes 재사용. D001(B/L 번호 누락)의 근거.
    bl_no = rng.choice(reference_codes)
    goods_desc = rng.choice(goods)
    # 무하자 건도 송장 품명 표기가 B/L 과 완전히 같지 않다(약어·어순·문자 변동).
    # dc_max_edit_distance_ratio 의 자연 기저 분포(설계서 5.3 표: 0.00~0.40 근방).
    # ⚠️ HANDOFF.md 9단계: 0.30→0.34로 확대(설계서 §5.3.2 처방 "무하자 쪽 혼합비
    # 범위를 넓힌다"와 동일 원리를 goods_wording_diff 축에 적용) — 9단계에서
    # :47A: 조건 샘플링 방식이 바뀌며 공유 RNG 스트림이 밀려, goods_wording_diff
    # 단일 피처 최대 AUC가 학습셋 0.845→0.857로 0.85를 넘었다(llm_goods_invoice_
    # semantic_equiv). 하자(injector._apply_goods_wording_diff, ratio_range
    # 0.15~0.55)를 건드리지 않고 무하자 쪽 상한만 넓혀 0.805(학습)/0.809(평가)로
    # 되돌렸다 — 둘 다 분포 겹침 유지.
    invoice_goods_desc = vary_wording(goods_desc, rng, ratio_range=(0.0, 0.34))

    package_qty = rng.randint(5, 500)
    gross_weight = round(rng.choice(weights) * rng.uniform(0.8, 1.3), 1)
    # 용적(CBM, 설계서 5.3.1) — 중량과 같은 승수 패턴으로 뽑는다. D007B 의 근거.
    measurement_cbm = round(rng.choice(measurements) * rng.uniform(0.8, 1.3), 2)
    unit_price = round(rng.choice(amounts) / max(package_qty, 1) * rng.uniform(0.5, 1.5), 2)
    unit_price = max(unit_price, 0.5)

    # 서류 간 수량·중량·금액 비교축(Group 2)의 무하자 자연 변동(HANDOFF.md 4b단계
    # "워터마크 위험" — natural_deviation_ratio() docstring 참고). 반올림·계량방식
    # 차이·부대비용 정도의 작은 이동(대략 0~5%)이며, injector.py 의
    # qty_sum_mismatch/weight_sum_mismatch/invoice_amount_mismatch 하자가 같은 축
    # 위에 더 큰 이동을 얹는다(겹치는 분포, 워터마크 아님).
    packing_list_qty_sum = max(
        0, round(package_qty * (1 + rng.choice((-1, 1)) * natural_deviation_ratio(rng, 0.05)))
    )
    packing_list_weight_sum = round(
        gross_weight * (1 + rng.choice((-1, 1)) * natural_deviation_ratio(rng, 0.04)), 1
    )
    invoice_amount = round(
        package_qty * unit_price * (1 + rng.choice((-1, 1)) * natural_deviation_ratio(rng, 0.05)), 2
    )
    # 운임(설계서 5.3.1) — 전용 값 분포 풀이 없으므로 총중량 기반 $/KG 근사로 만든다.
    # D017(운임 허용범위 이탈)의 근거.
    freight_amount = round(max(50.0, gross_weight * rng.uniform(0.3, 1.2)), 2)

    issue_date = epoch + timedelta(days=rng.randint(0, 900))
    onboard_date = issue_date + timedelta(days=rng.randint(0, 4))
    presentation_date = onboard_date + timedelta(days=rng.randint(2, 18))

    lc_present = rng.random() > 0.05  # 5% 는 L/C 없는 거래(설계서 4절 예외)
    lc_expiry = onboard_date + timedelta(days=rng.randint(20, 90)) if lc_present else None
    # 최종 선적기한(:44C:, 설계서 5.3.1) — 적재일 이후이며 유효기일보다 앞서야 한다.
    # lc_expiry 는 최소 onboard+20일이므로 onboard+0~15 범위는 항상 그 이전이다.
    lc_latest_shipment = onboard_date + timedelta(days=rng.randint(0, 15)) if lc_present else None
    lc_presentation_period = rng.choice([14, 21, 21, 21, 30]) if lc_present else None
    # Incoterms 2020 코드(설계서 5.3.1) — D015(Incoterms 미표시)의 근거.
    lc_incoterms = rng.choice(INCOTERMS_2020) if lc_present else None
    lc_required_doc_count = rng.randint(3, 7) if lc_present else None
    # :46A: 요구서류 목록(설계서 5.3.1) — BILL OF LADING 을 항상 포함시킨다.
    # D016(요구서류 목록에 B/L 없음)이 이걸 찾는다.
    if lc_present:
        extra_needed = max(0, lc_required_doc_count - 1)
        extra_docs = rng.sample(
            _OTHER_REQUIRED_DOCUMENT_TYPES,
            k=min(extra_needed, len(_OTHER_REQUIRED_DOCUMENT_TYPES)),
        )
        lc_documents_required = ["BILL OF LADING", *extra_docs]
    else:
        lc_documents_required = []
    # 중량·용적 한도, 운임(설계서 5.3.1) — 정상 상태에서는 실제 값 이상/동일이어야
    # D007/D007B/D017 이 정상 건에서 위반 없이 평가된다.
    lc_max_gross_weight_kg = round(gross_weight * rng.uniform(1.05, 1.5), 1) if lc_present else None
    lc_max_measurement_cbm = round(measurement_cbm * rng.uniform(1.05, 1.5), 2) if lc_present else None
    lc_freight_amount = freight_amount if lc_present else None

    # :47A: 조건 1~6개, 검증가능/검증불가 두 풀에서 혼합비
    # CLEAN_47A_UNVERIFIABLE_RATIO_RANGE(대략 0.0~0.6)로 섞어 뽑는다(설계서
    # §5.3.2 분할 + 중첩 요건, HANDOFF.md 9단계). 무하자 건도 검증불가 조건을
    # 일부 포함해야 injector.py 의 freeform_47a_unmet 이 혼합비를 "이동"만 시키고
    # "분리"하지 않는다(같은 함정을 세 번 잡아낸 HANDOFF.md 3절과 동종 워터마크
    # 방지). 고정 템플릿("CONDITION N: ...")도 쓰지 않는다.
    condition_count = rng.randint(1, 6)
    if lc_present:
        lc_47a_text = sample_47a_conditions(rng, condition_count, CLEAN_47A_UNVERIFIABLE_RATIO_RANGE)
    else:
        lc_47a_text = ""

    consignee_name = entities.counterparty_names[counterparty_id]
    # 송장 수하인 표기도 B/L 과 완전히 동일하지 않다(구두점·법인격 약어 변동).
    # dc_party_name_mismatch_count 의 자연 기저 분포 근거(설계서 5.3 표).
    invoice_consignee_name = vary_company_suffix(consignee_name, rng, strength=0.25)

    # 서류 간 정합성의 약한 자연 변동 — customary_wording_missing 하자가
    # 이 확률을 이동시킬 뿐(설계서 5.3), 그 자체로는 하자와 무관한 배경 잡음.
    admin_note_conflict = rng.random() < 0.07

    source, confidences, missing, no_evidence = _sample_extraction_quality(rng, field_accuracy)

    return SynthShipment(
        base_shipment_id=base_id,
        shipment_id=base_id,
        counterparty_id=counterparty_id,
        bank_id=bank_id,
        bank_strictness=bank_strictness,
        counterparty_propensity=counterparty_propensity,
        cargo_type=cargo_type,
        cargo_type_propensity=cargo_type_propensity,
        bl_no=bl_no,
        shipper=rng.choice(pools.company_names) if pools.company_names else "GENERIC SHIPPER CO., LTD.",
        consignee=consignee_name,
        invoice_consignee=invoice_consignee_name,
        notify_party=rng.choice(pools.company_names) if pools.company_names else "GENERIC NOTIFY CO., LTD.",
        lc_consignee=consignee_name if lc_present else None,
        port_of_loading=pol,
        port_of_discharge=pod,
        lc_port_of_discharge=pod,
        lc_port_of_loading=pol if lc_present else None,
        vessel=vessel,
        voyage_no=voyage_no,
        goods_description=goods_desc,
        invoice_goods_description=invoice_goods_desc,
        lc_goods_description=goods_desc if lc_present else None,
        package_qty=package_qty,
        packing_list_qty_sum=packing_list_qty_sum,
        gross_weight_kg=gross_weight,
        packing_list_weight_sum=packing_list_weight_sum,
        measurement_cbm=measurement_cbm,
        unit_price_usd=unit_price,
        invoice_amount_usd=invoice_amount,
        freight_amount_usd=freight_amount,
        original_bl_count=REQUIRED_ORIGINAL_COUNT,
        required_original_count=REQUIRED_ORIGINAL_COUNT,
        admin_note_conflict=admin_note_conflict,
        lc_present=lc_present,
        lc_required_doc_count=lc_required_doc_count,
        lc_documents_required=lc_documents_required,
        lc_47a_text=lc_47a_text,
        lc_has_special_clause=lc_present and rng.random() < 0.3,
        lc_is_transferable=lc_present and rng.random() < 0.1,
        lc_partial_shipment_allowed=(not lc_present) or rng.random() < 0.6,
        lc_transshipment_allowed=(not lc_present) or rng.random() < 0.7,
        lc_amount_tolerance_pct=rng.choice([0, 5, 10]) if lc_present else 0,
        lc_expiry_date=lc_expiry,
        lc_latest_shipment_date=lc_latest_shipment,
        lc_presentation_period_days=lc_presentation_period,
        lc_max_gross_weight_kg=lc_max_gross_weight_kg,
        lc_max_measurement_cbm=lc_max_measurement_cbm,
        lc_freight_amount=lc_freight_amount,
        lc_incoterms=lc_incoterms,
        bl_issue_date=issue_date,
        onboard_date=onboard_date,
        presentation_date=presentation_date,
        extraction_source=source,
        field_confidences=confidences,
        missing_fields=missing,
        no_evidence_fields=no_evidence,
    )


def generate_base_shipments(
    pools: ValuePools,
    entities: EntityPools,
    params: GeneratorParams,
    field_accuracy: dict[str, float],
) -> list[SynthShipment]:
    """`params.base_count` 개의 정합성 완전한 기준 선적을 생성한다. 이 선적들이
    (변형을 거쳐) X의 행이 된다."""
    rng = random.Random(params.seed)
    shipments: list[SynthShipment] = []
    for i in range(params.base_count):
        base_id = f"S{i:05d}"
        counterparty_id = rng.choice(entities.counterparty_ids)
        bank_id = rng.choice(entities.bank_ids)
        cargo_type = rng.choice(CARGO_TYPES)
        shipments.append(
            _build_shipment(base_id, counterparty_id, bank_id, cargo_type, pools, entities, rng, field_accuracy)
        )
    return shipments


def generate_history_shipments(
    pools: ValuePools,
    entities: EntityPools,
    field_accuracy: dict[str, float],
    rng: random.Random,
) -> list[SynthShipment]:
    """거래처마다 별도의 과거 기간(history period) 선적을 생성한다(설계서 4절
    Group 6 규칙 1). 이 선적들은 `generate_base_shipments`의 산출물과 완전히
    분리된 집합이며 **X의 행으로 절대 들어가지 않는다** — `dataset.py`가 채널 B로
    라벨링해 관측 비율만 집계하고 선적 자체는 버린다.

    거래처별 건수는 `config.HISTORY_SHIPMENT_COUNT_RANGE`(예 0~50건)에서 균등하게
    뽑는다(규칙 4 — 건수가 적을수록 관측 비율이 잠재 성향에서 벗어나는 관측 잡음의
    근거, `hist_counterparty_shipment_count`가 그 신뢰도 피처다). 0건이면 그
    거래처는 콜드스타트다.
    """
    lo, hi = config.HISTORY_SHIPMENT_COUNT_RANGE
    shipments: list[SynthShipment] = []
    for counterparty_id in entities.counterparty_ids:
        n_hist = rng.randint(lo, hi)
        for j in range(n_hist):
            bank_id = rng.choice(entities.bank_ids)
            cargo_type = rng.choice(CARGO_TYPES)
            hist_id = f"HIST-{counterparty_id}-{j:04d}"
            shipments.append(
                _build_shipment(hist_id, counterparty_id, bank_id, cargo_type, pools, entities, rng, field_accuracy)
            )
    return shipments


def to_snapshot(
    shipment: SynthShipment,
    rule_outcome: RuleEngineOutcome,
    history: HistoryStats,
) -> ShipmentSnapshot:
    """SynthShipment(+채널 A 출력 +이력 통계) → ShipmentSnapshot.

    이 함수가 두 개의 독립 채널(rule_sim, review)의 출력을 피처 스키마로 모으는
    유일한 지점이다. review.py 의 출력(y)은 여기 들어오지 않는다 — y 는 dataset.py 가
    별도 컬럼으로 보관한다(피처와 라벨의 경로를 코드 상에서도 분리해 둔다).

    `rule_outcome` 은 fs-2(HANDOFF.md 3단계)부터 `RuleEngineOutcome` 이다 —
    현재는 `synth/rule_sim.py`(임시 대역)가 만들지만, 실제 룰엔진을 쓰는
    `rule_adapter.evaluate_shipment()` 도 같은 타입을 반환하므로 5단계 전환 시
    이 함수는 바뀌지 않는다.
    """
    doc_consistency = DocConsistencyInputs(
        party_name_pairs=(
            ("consignee", shipment.consignee, shipment.invoice_consignee),
            ("goods_description", shipment.goods_description, shipment.invoice_goods_description),
        ),
        bl_qty=float(shipment.package_qty),
        packing_qty_sum=float(shipment.packing_list_qty_sum),
        bl_weight=shipment.gross_weight_kg,
        packing_weight_sum=shipment.packing_list_weight_sum,
        invoice_amount=shipment.invoice_amount_usd,
        computed_amount=round(shipment.package_qty * shipment.unit_price_usd, 2),
        conflict_field_count=(
            (1 if shipment.port_of_discharge != shipment.lc_port_of_discharge and shipment.lc_present else 0)
            + (1 if shipment.admin_note_conflict else 0)
        ),
    )
    extraction_quality = ExtractionQualityInputs(
        field_confidences=dict(shipment.field_confidences),
        missing_fields=tuple(shipment.missing_fields),
        no_evidence_fields=tuple(shipment.no_evidence_fields),
        checked_field_count=len(EXTRACTION_CHECKED_FIELDS),
        source=shipment.extraction_source,  # type: ignore[arg-type]
    )
    lc = (
        LCTerms(
            required_doc_count=shipment.lc_required_doc_count,
            field_47a_text=shipment.lc_47a_text,
            has_special_clause=shipment.lc_has_special_clause,
            is_transferable=shipment.lc_is_transferable,
            partial_shipment_allowed=shipment.lc_partial_shipment_allowed,
            transshipment_allowed=shipment.lc_transshipment_allowed,
            amount_tolerance_pct=shipment.lc_amount_tolerance_pct,
        )
        if shipment.lc_present
        else None
    )
    dates = ShipmentDates(
        lc_expiry_date=shipment.lc_expiry_date,
        bl_issue_date=shipment.bl_issue_date,
        onboard_date=shipment.onboard_date,
        presentation_date=shipment.presentation_date,
        presentation_period_days=shipment.lc_presentation_period_days,
    )
    return ShipmentSnapshot(
        shipment_id=shipment.shipment_id,
        base_shipment_id=shipment.base_shipment_id,
        rule_outcome=rule_outcome,
        doc_consistency=doc_consistency,
        extraction_quality=extraction_quality,
        lc=lc,
        dates=dates,
        history=history,
    )

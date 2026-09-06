"""
F2 안전 정책 — 클래스 정의, 필드→클래스 매핑, 허용 단계표, 신뢰도 상수.

## 이 파일이 안전 불변식을 담는 이유

`HANDOFF.md` §4.2 는 이 표를 "`policy.py` 안의 상수(코드)다. YAML 이
아니다" 라고 못박는다. `rules.yaml`(F3 룰 카탈로그)을 데이터로 둔 근거는
"화면·리포트가 조문을 인용해야 한다"였다 — 인용 **대상**이라 데이터가
맞다. 반면 "컨테이너 번호는 LLM 에 보내지 않는다"는 인용할 조문이 아니라
**안전 불변식**이다. YAML 이면 사전 편집자가 한 줄 고쳐 컨테이너 번호를
Gemini 로 보낼 수 있고 사전 데이터 리뷰 수준만 거친 채 배포될 수 있다.
코드면 diff 에 남아 코드 리뷰를 거치고 테스트가 회귀를 잡는다. "결정론으로
판정 가능한 것에 LLM 을 태우지 않는다"(§1)는 한 번이라도 어기면 "오류
검출률 100%" 주장 자체가 무너지므로 이 불변식은 설정이 아니라 코드다.

같은 이유로 `allows()` 는 **단일 진입점**이다. 캐스케이드(T9)가 각 단계
진입 전에 반드시 이 함수를 통해서만 묻는다. 캐스케이드 여기저기서
`if term_class in (...)` 를 산발적으로 검사하면 새 단계를 추가할 때 한
군데를 빠뜨려도 아무도 알아채지 못한다.

`LLM_FORBIDDEN` 이 `allows()` 안에서 다시 걸러지는 것도 이중 방어다 —
`CLASSES[...].allowed_stages` 표에 실수로 `STAGE_LLM` 을 넣어도
`LLM_FORBIDDEN` 이 최종 거부한다. 두 자료구조가 어긋나면 버그지만, 그
버그의 실패 방향이 "LLM 을 더 막는 쪽"이길 원해서 안전한 쪽을 이중으로
잠근다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

# ── 단계 상수 ────────────────────────────────────────────────────
#
# `Evidence.stage` 가 싣는 값과 정확히 같은 문자열이어야 한다. 정수가
# 아니라 문자열인 이유: 응답 JSON 에 그대로 나가는 값이라 정수를 쓰면
# 게이트웨이·화면이 매핑표를 따로 들고 있어야 한다.
STAGE_FORMAT = "format"
STAGE_EXACT = "exact"
STAGE_ALIAS = "alias"
STAGE_PATTERN = "pattern"
STAGE_SIMILARITY = "similarity"
STAGE_LLM = "llm"

# 캐스케이드가 단계를 도는 순서. 여기 한 곳에 순서를 두면 "①②③ 은 맞으면
# 즉시 종결"(`HANDOFF.md` §4.1) 같은 정지 조건을 구현할 때 순서를 따로
# 정의하지 않아도 된다.
STAGE_ORDER: Tuple[str, ...] = (
    STAGE_FORMAT,
    STAGE_EXACT,
    STAGE_ALIAS,
    STAGE_PATTERN,
    STAGE_SIMILARITY,
    STAGE_LLM,
)


@dataclass(frozen=True)
class TermClass:
    """용어 클래스 1개의 정책.

    `needs_glossary=False` 인 클래스(`party_name`·`goods`)는 사전을 전혀
    조회하지 않는다 — `format` 단계만 허용되는 것과 같은 사실을 다른
    각도에서 본 것이다. 별도 플래그를 두는 이유: 로더(T4)가 "사전이
    필요한 클래스는 카탈로그에 항목이 있어야 한다"를 검증할 때
    `allowed_stages` 만으로는 "사전이 아예 필요 없는 클래스"와 "사전은
    필요한데 이번 카탈로그에 항목이 0건인 클래스"를 구분할 수 없다.
    """

    key: str
    label: str  # 한국어 표시명. HANDOFF §4.2 표의 클래스명 그대로.
    needs_glossary: bool
    allowed_stages: FrozenSet[str]
    default_authority: str  # Evidence.authority 기본값. 근거 표준의 이름.


# `HANDOFF.md` §4.2 표를 그대로 코드화한다. `party_name`/`goods` 는 표에서
# 한 행("party_name/goods 고유명사·품명")으로 묶여 있지만 실제로는 서로
# 다른 값(당사자명 vs 품명)이라 별도 클래스로 나눈다 — 사전 미필요·format
# 전용이라는 정책은 같지만, `FIELD_CLASS` 에서 어느 필드가 어느 클래스인지
# 갈라야 한다.
_ALL_STAGES: FrozenSet[str] = frozenset(STAGE_ORDER)

CLASSES: Dict[str, TermClass] = {
    "port": TermClass(
        "port", "항구·지명", True, _ALL_STAGES, "UN/LOCODE",
    ),
    "transport_doc": TermClass(
        "transport_doc", "운송서류 용어", True, _ALL_STAGES, "ISBP 821",
    ),
    "delivery": TermClass(
        "delivery", "인도 관련", True, _ALL_STAGES, "ISBP 821",
    ),
    "practice_phrase": TermClass(
        "practice_phrase", "관행 문구", True, _ALL_STAGES, "ISBP 821",
    ),
    "price_term": TermClass(
        "price_term", "가격조건", True, _ALL_STAGES, "Incoterms 2020",
    ),
    # party_suffix — 상호 접미(Co., Ltd. 등)만. format(공백·NFKC)과
    # pattern(접미 사전 조회)만 허용한다. exact/alias 를 막는 이유는 접미가
    # 상호 문자열 전체의 exact/alias 대상이 되면 "GAE WOON CO.,LTD" 전체를
    # 사전에 등록해야 하는데, 그건 party_name 이 format 전용이라는 정책과
    # 정면으로 모순된다. pattern 단계가 접미 토큰만 잘라 검사한다.
    "party_suffix": TermClass(
        "party_suffix", "당사자 상호 접미", True,
        frozenset({STAGE_FORMAT, STAGE_PATTERN}), "ISO 20275",
    ),
    # qty_unit/volume_unit — ④유사도까지만. Rec 20 코드 집합은 닫혀 있어
    # "비슷한 단위"가 존재하지 않는다 — 사전에 없으면 유사도 후보가 아니라
    # 모르는 단위라고 말해야 한다(`Notice(not_covered)`, `HANDOFF.md` §4.1).
    "qty_unit": TermClass(
        "qty_unit", "수량 단위", True,
        frozenset({STAGE_FORMAT, STAGE_EXACT, STAGE_ALIAS, STAGE_PATTERN}),
        "UN/ECE Rec 20",
    ),
    "volume_unit": TermClass(
        "volume_unit", "용적 단위", True,
        frozenset({STAGE_FORMAT, STAGE_EXACT, STAGE_ALIAS, STAGE_PATTERN}),
        "UN/ECE Rec 20",
    ),
    # container_no/hs_code — pattern(결정론 검증기) 단독. "표준 표기 중
    # 하나를 고르는" 문제가 아니라 "형식적으로 유효한가"를 체크섬·정규식으로
    # 판정하는 문제라 exact/alias/유사도가 의미가 없다 — 컨테이너 번호는
    # 유일값이라 "표준 컨테이너 번호"라는 개념 자체가 없다.
    "container_no": TermClass(
        "container_no", "컨테이너 번호", True,
        frozenset({STAGE_PATTERN}), "ISO 6346",
    ),
    "hs_code": TermClass(
        "hs_code", "품목 분류", True,
        frozenset({STAGE_PATTERN}), "HS 2022",
    ),
    # party_name/goods — format 전용. 사전 조회·유사도·LLM·철자 교정·약어
    # 확장을 전부 금지한다(`HANDOFF.md` §4.8 "고유명사·품명 절제") — 회사명·
    # 품명은 정답이 하나로 정해지지 않으므로, "정답"과 대조해 고치는 행위
    # 자체가 이 기능의 위험 신호다.
    "party_name": TermClass(
        "party_name", "당사자 고유명사", False,
        frozenset({STAGE_FORMAT}), "표기 정규화",
    ),
    "goods": TermClass(
        "goods", "품명", False,
        frozenset({STAGE_FORMAT}), "표기 정규화",
    ),
}

# ⑤ LLM 진입 자체를 금지하는 클래스. `HANDOFF.md` §4.2 표에서 "⑤ LLM" 열이
# "금지"인 7개 클래스와 정확히 같아야 한다 — `allows()` 의 이중 방어가 이
# 집합을 최종 판정자로 쓴다.
LLM_FORBIDDEN: FrozenSet[str] = frozenset(
    {
        "party_suffix",
        "qty_unit",
        "volume_unit",
        "container_no",
        "hs_code",
        "party_name",
        "goods",
    }
)


def allows(term_class: str, stage: str) -> bool:
    """`term_class` 가 `stage` 에 진입해도 되는가. 캐스케이드의 단일 진입점.

    모르는 클래스는 무조건 거부한다 — 허용 쪽을 기본값으로 잡으면 카탈로그에
    오탈자로 새 `category` 가 섞여 들어왔을 때 검증되지 않은 값이 조용히
    모든 단계를 통과한다. "판정 가능한 것에만 판정을 허용한다"를 클래스
    자체에도 적용한다.
    """
    cls = CLASSES.get(term_class)
    if cls is None:
        return False
    # LLM_FORBIDDEN 이 allowed_stages 보다 우선한다 — 모듈 docstring의
    # "이중 방어" 논거.
    if stage == STAGE_LLM and term_class in LLM_FORBIDDEN:
        return False
    return stage in cls.allowed_stages


# ── 필드 → 클래스 매핑 ───────────────────────────────────────────
#
# `f1_intake/types.py:BL_FIELD_NAMES` 와 `f1_intake/doc_types.py:SPECS` 의 실제 필드
# 이름을 확인하고 썼다(추측하지 않았다). 세 서류(선하증권·상업송장·
# 포장명세서)에서 필드명이 겹치는 경우(`shipper`/`seller`, `consignee`/
# `buyer`, `gross_weight`, `measurement`, `description_of_goods` 등)는 같은
# 키로 한 번만 적는다 — 매핑은 필드 "이름" 기준이지 서류 종류 기준이 아니다.
#
# ## 매핑에서 의도적으로 뺀 필드
#
# - **식별자류**(`bl_no`·`invoice_no`·`lc_no`) — 대응 클래스가 없다. 서류
#   고유 번호는 정렬할 대상이 아니라 그 자체가 키다.
# - **날짜류**(`date_of_issue`·`invoice_date`·`packing_date`·
#   `on_board_date`) — 날짜 정규화는 F1(`mt700.py`)의 몫이고 12개 클래스
#   어디에도 날짜가 없다.
# - **선박명·항차**(`vessel`·`voyage_no`) — 고유명사이지만 `party_name`도
#   `goods`도 아니고, 선명 표준화 사전은 이번 범위(§4.6 적재량 표)에 없다.
# - **금액류**(`total_freight`·`total_amount`) — 통화·금액 형식 검증은
#   이번 클래스 목록에 없다. `total_freight` 에 운임 지불조건 문구
#   ("FREIGHT PREPAID")가 섞여 들어올 가능성도 검토했지만, 실제 필드 정의
#   (`BLFields.total_freight: Optional[str]`)가 "총 운임" 수치 자리로
#   설계돼 있어 `delivery` 클래스로 단정하지 않았다. T14 코퍼스가 근거를
#   주면 재검토 대상이다.
#
# `transport_doc`/`delivery` 두 클래스는 **어떤 필드에도 매핑하지 못했다.**
# 현재 `BLFields`/`DocumentSpec` 어디에도 "SHIPPED ON BOARD", "CLEAN ON
# BOARD", "FREIGHT PREPAID" 같은 운송서류 관행 문구를 담을 전용 필드가
# 없다 — F1 이 별도 필드로 뽑지 않는 이상 F2 가 교정할 대상 자체가 없다.
# T9 또는 F1 필드 확장이 이 공백을 메워야 한다 — 지어내지 않고 비워 둔다.
FIELD_CLASS: Dict[str, str] = {
    # 항구·지명. place_of_issue 도 포함한 이유: B/L 발행지는 실무상 거의
    # 언제나 항구·도시명이라(`FIELD_LABELS["place_of_issue"] == "발행지"`)
    # 표기 불일치(부산/Pusan/PUS)가 다른 항구 필드와 똑같이 나타난다.
    "port_of_loading": "port",
    "port_of_discharge": "port",
    "place_of_issue": "port",
    # 가격조건. Incoterms 2020 장소 병기 규칙(`HANDOFF.md` §4.9)이 적용된다.
    "incoterms": "price_term",
    # 당사자 고유명사. B/L 의 shipper/consignee/notify_party, 상업송장의
    # seller/buyer 가 실질적으로 같은 역할(송하인/수하인 쌍)이다.
    "shipper": "party_name",
    "consignee": "party_name",
    "notify_party": "party_name",
    "seller": "party_name",
    "buyer": "party_name",
    # 수량 단위. 값이 "숫자 + Rec 20 코드"(예: "1,234.50 KGS", "500 CTN")인
    # 필드들 — 단위 토큰 부분만 pattern/exact/alias 대상이다.
    "gross_weight": "qty_unit",
    "net_weight": "qty_unit",
    "quantity": "qty_unit",
    "package_count": "qty_unit",
    # 용적 단위. CBM/MTQ 계열.
    "measurement": "volume_unit",
}

# 자유서식 필드 → 그 안에서 스캔할 수 있는 클래스들.
#
# `description_of_goods`·`marks` 는 값 전체가 한 클래스가 아니라 문장 안에
# 여러 클래스가 span 으로 섞여 나타날 수 있다. **주의**: HANDOFF 본문은
# 예시로 "marks_and_numbers" 필드명을 들지만, 실제
# `doc_types.py:_PACKING_LIST.fields` 의 필드명은 `marks` 다 — 이 저장소에
# `marks_and_numbers` 필드는 존재하지 않는다.
#
# `container_no`/`hs_code` 가 `FIELD_CLASS` 에 전혀 등장하지 않는 이유가
# 여기서 풀린다: 이 저장소의 어떤 `BLFields`/`DocumentSpec` 도 컨테이너
# 번호·HS 코드를 담는 전용 필드를 갖고 있지 않다(`BL_FIELD_NAMES`·`SPECS`
# 전수 확인). 실무에서 이 값들은 화물 명세·화인 텍스트 안에 섞여 등장하니
# span 스캔이 두 클래스가 F2 에 진입하는 **유일한 경로**다.
#
# `shipper`/`consignee`/`notify_party`/`seller`/`buyer` 가 다시 등장하는
# 이유: `FIELD_CLASS` 에서 이 필드들은 이미 `party_name`(값 전체, format
# 전용) 대상인데, 동시에 값 끝의 상호 접미(`party_suffix`, span 전용)도
# 스캔해야 한다. `HANDOFF.md` §4.8 의 `"GAE WOON CO.,LTD"` 예시가 이 이중
# 처리다 — 필드 전체는 party_name 규칙(포맷만), 접미 토큰만 party_suffix
# 규칙(패턴 사전 조회)을 탄다.
#
# `transport_doc`·`delivery`·`practice_phrase` 가 자유서식에만 걸리는 이유도
# 같다. "Surrendered B/L"·"D/O"·"FREIGHT PREPAID" 를 담는 전용 필드가
# 어디에도 없다(`BL_FIELD_NAMES` 전수 확인). `total_freight` 는 이름이
# 그럴듯하지만 답이 아니다 — `field_parser.py:408` 이 그 자리에 금액만
# 넣는다(`f"${amount.group(1)}"`). 관행 문구가 들어올 수 없는 필드다.
#
# 그래서 이 셋은 화물 명세·화인 본문의 span 스캔이 **유일한 진입 경로**다.
# 여기에 넣지 않으면 세 클래스가 사전만 있고 절대 발동하지 않는 죽은
# 코드가 된다. 전용 필드를 F1 이 뽑게 되면 그때 `FIELD_CLASS` 로 옮긴다.
FIELD_SCAN_CLASSES: Dict[str, Tuple[str, ...]] = {
    "description_of_goods": (
        "goods", "hs_code", "container_no", "practice_phrase",
        "transport_doc", "delivery",
    ),
    "marks": ("container_no", "goods", "practice_phrase", "transport_doc"),
    "shipper": ("party_suffix",),
    "consignee": ("party_suffix",),
    "notify_party": ("party_suffix",),
    "seller": ("party_suffix",),
    "buyer": ("party_suffix",),
}


# `Suggestion.suggestion_id` 파생 해시에 들어간다(`HANDOFF.md` §4.7).
# 캐스케이드 로직(단계 순서·정지 조건·신뢰도 계산식)이 바뀌면 올린다 —
# 카탈로그를 안 바꿔도 로직이 바뀌면 같은 입력이 다른 출력을 낼 수 있고,
# 그 변화가 옛 id 재사용으로 가려지면 안 된다.
CASCADE_VERSION = "f2-cascade-1"


# ── 신뢰도 상수 ──────────────────────────────────────────────────
#
# 값의 출처는 전부 `HANDOFF.md` §4.1 단계표다. ⑤(LLM) 상한이 ⓪(format)
# 보다도 낮은 게 의도다 — LLM 이 결정론 경로를 신뢰도로 이기는 상황을
# 구조적으로 막는다.
CONF_FORMAT = 0.92
CONF_EXACT = 0.99
CONF_ALIAS = 0.95
CONF_PATTERN_VERIFIED = 0.97  # 결정론 검증(체크디지트 등) 통과
CONF_PATTERN = 0.90  # 형식만 맞고 결정론 검증은 통과 못함/해당 없음

# 이 미만이면 제안을 만들지 않는다(`Unevaluated` 로 유보). §1 원칙
# "제안하지 않는 것이 틀리게 제안하는 것보다 낫다"의 수치화다.
MIN_CONFIDENCE = 0.60

# ⑤단계 신뢰도 상한. min(LLM_CONFIDENCE_CAP, 0.55 + 0.30*s) 식의 그 0.85.
LLM_CONFIDENCE_CAP = 0.85

# ④유사도 최고 점수가 이 미만이면 제안 없음 → Unevaluated.
SIMILARITY_FLOOR = 0.55

# ④유사도 후보가 정확히 1건이고 점수가 이 이상이면 ⑤를 건너뛰고 종결.
SINGLE_CANDIDATE_FLOOR = 0.85

# ④유사도 후보 풀에서 남기는 상위 개수.
TOP_K = 5


# ── 환경변수 ─────────────────────────────────────────────────────


def _env_flag(name: str) -> bool:
    """환경변수를 불리언으로. 미설정은 거짓이다.

    `f1_intake/pipeline.py:27` 에 이미 같은 함수가 있지만 **임포트하지 않고
    복사했다.** `ocr.pipeline` 을 임포트하면 그 파일이 끌고 오는
    `OCRExtractor`/`LLMFieldExtractor` 등 무거운 체인이 `terms` 에도
    따라붙는데, `terms` 는 F6 이 `ocr` 를 몰라도 가볍게 끌어 쓸 자리다
    (`keys.py` 모듈 docstring과 같은 논거). 패키지 간 결합보다 이 3줄의
    중복이 싸다는 것이 `HANDOFF.md` §4.4/§6.3 의 판단이고 이 함수도 같다.
    """
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def llm_select_enabled() -> bool:
    """⑤단계(LLM 후보 선정)를 켤지. 기본값은 꺼짐 — 외부 API 호출이라서다
    (`LLM_STRUCTURED_EXTRACT` 선례와 동일, `.env.example` 규약)."""
    return _env_flag("TERMS_LLM_SELECT")


def glossary_version_override() -> Optional[str]:
    """판정에 쓸 표준 사전 버전 지정. 비어 있으면 `None`(로더가
    `effective_date` 최신 버전을 고른다)."""
    value = (os.getenv("TERMS_GLOSSARY_VERSION") or "").strip()
    return value or None


def llm_max_items() -> int:
    """⑤단계 한 번에 묶어 물을 항목 수 상한. 기본 20건. 늘리면 선적 10초
    응답 예산이 위험해진다(`HANDOFF.md` §4.4 "배치")."""
    raw = (os.getenv("TERMS_LLM_MAX_ITEMS") or "").strip()
    return int(raw) if raw else 20


def llm_timeout() -> float:
    """⑤단계 타임아웃(초). 기본 8.0 — 기획안의 선적 1건 10초 안에 든다.

    6.0 → 20.0 → 8.0 으로 두 번 움직였다. 경위를 남겨 둔다.

    처음 6.0 은 추정이었다. `gemini-3.7-flash` 로 실측하니 2.46~15.89초 +
    503 이 섞여 성공한 호출조차 대부분 잘렸고, 그래서 20.0 으로 올리며 선적
    예산도 25초로 재협상했다. 그런데 그 다음이 진짜였다 — **429, 무료 등급
    하루 20건.** 지연이 아니라 할당량이 제약이었다.

    답은 예산을 올리는 것이 아니라 모델을 바꾸는 것이었다. ⑤가 하는 일은
    후보 5개 중 번호 하나 고르기라 lite 모델로 충분하고,
    `gemini-3.5-flash-lite` 는 선적 1건을 **1.1초**(8회 전건 성공)에 끝낸다.
    그래서 예산 재협상을 되돌리고 타임아웃만 8.0 으로 둔다 — 결정론 경로
    1.3ms 를 더해도 10초 안이고, 넘치면 폴백이 받는다.

    **모델을 무거운 쪽으로 바꾸려면 이 값과 기획안 10초를 함께 다시 재라.**
    재시도는 넣지 않는다 — 예산을 두 배로 먹고, 어댑터가 재시도를 안 하는
    것도 의도다.
    """
    raw = (os.getenv("TERMS_LLM_TIMEOUT") or "").strip()
    return float(raw) if raw else 8.0


__all__ = [
    "CASCADE_VERSION",
    "CLASSES",
    "CONF_ALIAS",
    "CONF_EXACT",
    "CONF_FORMAT",
    "CONF_PATTERN",
    "CONF_PATTERN_VERIFIED",
    "FIELD_CLASS",
    "FIELD_SCAN_CLASSES",
    "LLM_CONFIDENCE_CAP",
    "LLM_FORBIDDEN",
    "MIN_CONFIDENCE",
    "SIMILARITY_FLOOR",
    "SINGLE_CANDIDATE_FLOOR",
    "STAGE_ALIAS",
    "STAGE_EXACT",
    "STAGE_FORMAT",
    "STAGE_LLM",
    "STAGE_ORDER",
    "STAGE_PATTERN",
    "STAGE_SIMILARITY",
    "TOP_K",
    "TermClass",
    "allows",
    "glossary_version_override",
    "llm_max_items",
    "llm_select_enabled",
    "llm_timeout",
]

"""[채널 A 확장] LLM 피처 배관 — Group 7(LLM_SEMANTIC) 산출 (계획서 8단계 Task 3·4).

`compute_features_batch()` 는 `synth/review.compute_labels()` 와 형태를 의도적으로
맞춘다 — 10단계에서 Gemini 전송 로직이 이 인터페이스 뒤에 그대로 슬롯인다.

지금은 오프라인 백엔드만 구현한다(설계서 5.5 "두 개의 백엔드" 패턴을 Group 7 에도
적용). 실제 LLM 호출은 전혀 없다 — `config.LLM_FEATURE_BACKEND` 기본값 `"offline"`
은 문서 텍스트만으로 계산하는 결정론적 휴리스틱이다.

★★ HANDOFF.md 불변식 2 (라벨 누수 차단, 이 파일에서 가장 중요한 부분) ★★
LLM 이 피처(채널 A)와 라벨(채널 B)을 동시에 만들면 두 채널이 같은 모델 계열의
상위 잠재변수(토크나이저·salience 편향)를 공유하게 되어, 결합 AUC 가 올라가도
그게 진짜 신호인지 채널 결합 아티팩트인지 **이 저장소의 어떤 통계 검정으로도
구분할 수 없다.** 유일한 방어선은 설정 조합 자체를 거부하는 것이다 —
`check_channel_independence()` 가 `compute_features_batch()` 진입 시 가장 먼저
실행되고, `dataset.generate_dataset()` 도 어떤 생성 작업을 시작하기 전에 먼저
호출한다(계획서 8단계 Task 4 "이 검사는 어떤 작업도 하기 전에 발화해야 한다").

★ 채널 독립(설계서 1절) ★ 이 모듈은 `synth/review.py` 를 import 하지 않으며 그
반대도 마찬가지다. `render.render_document_set()` 이 이미 렌더링해 둔 텍스트만
받는다(`items: list[tuple[shipment_id, document_text]]`) — 어떤 선적 사본을
렌더링했는지(진실 vs 관측값)는 호출부(`dataset.py`)의 책임이다.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from f3_research import config
from f3_research.cache import JsonlCache
from f3_research.schema import LLMFeatures

NAN = float("nan")

# 오프라인 휴리스틱 버전 — 계산 로직을 바꾸면 이 값을 올린다. content hash 에
# 포함되므로, 로직이 바뀌면 이전 캐시가 자동으로 무효화되고 재계산된다
# (review.py::PROMPT_VERSION 과 같은 패턴, 설계서 12절 "판정 캐시 키에 모델
# ID와 프롬프트 버전이 포함된다").
LLM_FEATURE_HEURISTIC_VERSION = "v2"  # v1→v2: 9단계, 47A 언어적 단서 분류기 추가


# ---------------------------------------------------------------------------
# Task 4 — 채널 독립 가드 (HANDOFF.md 불변식 2, 이 파일 전체에서 가장 중요한 함수)
# ---------------------------------------------------------------------------


def check_channel_independence(
    llm_feature_backend: str | None = None, reviewer_backend: str | None = None
) -> None:
    """LLM_FEATURE_BACKEND='gemini' 이면서 REVIEWER_BACKEND 도 실전 LLM 이면 거부한다.

    "실전 LLM" = `"constant_table"` 이외의 모든 값(현재는 `"claude"` 뿐이지만,
    앞으로 어떤 값이 추가되든 화이트리스트가 아니라 constant_table 만 예외로
    두는 방향이 안전하다 — 새 백엔드를 깜빡 여기 추가 안 해도 기본적으로 막힌다).

    `compute_features_batch()` 와 `dataset.generate_dataset()` 양쪽에서 **어떤
    작업(캐시 조회·선적 생성 등)도 시작하기 전에** 가장 먼저 호출해야 한다
    (계획서 8단계 Task 4).
    """
    llm_feature_backend = llm_feature_backend if llm_feature_backend is not None else config.LLM_FEATURE_BACKEND
    reviewer_backend = reviewer_backend if reviewer_backend is not None else config.REVIEWER_BACKEND
    if llm_feature_backend == "gemini" and reviewer_backend != "constant_table":
        raise RuntimeError(
            "채널 독립 위반: LLM_FEATURE_BACKEND='gemini' 이면서 "
            f"REVIEWER_BACKEND={reviewer_backend!r} 입니다.\n"
            "같은 모델 계열이 피처(채널 A)와 라벨(채널 B)을 동시에 만들면 상위\n"
            "잠재변수(모델 계열·토크나이저·salience 편향)를 공유하게 되어, 결합\n"
            "AUC 가 올라가도 그게 진짜 신호인지 채널 결합 아티팩트인지 구분할\n"
            "방법이 없습니다(HANDOFF.md 불변식 2 — 어떤 통계 검정도 이걸 못 잡습니다).\n"
            "REVIEWER_BACKEND 를 'constant_table' 로 두거나 LLM_FEATURE_BACKEND 를\n"
            "'null' 또는 'offline' 으로 두세요."
        )


# ---------------------------------------------------------------------------
# 문서 텍스트 파싱 — render.render_document_set() 이 만드는 정확한 레이블
# 형식에 의존한다(그 함수의 렌더링 텍스트는 캐시 키의 근거라 바뀌지 않는다,
# render.py 모듈 docstring 참고). 여기서는 텍스트를 바꾸지 않고 **읽기만** 한다.
# ---------------------------------------------------------------------------

_BL_HEADER = "선하증권(Bill of Lading)"
_LC_HEADER = "신용장(Letter of Credit) 조건"
_INVOICE_HEADER = "상업송장(Commercial Invoice)"
_PACKING_HEADER = "포장명세서(Packing List)"

_SECTION_SPLIT_RE = re.compile(r"\n=== (.+?) ===\n")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _split_sections(document_text: str) -> dict[str, str]:
    """`render.render_document_set()` 이 만든 '=== 헤더 ===' 구획으로 나눈다."""
    parts = _SECTION_SPLIT_RE.split("\n" + document_text)
    sections: dict[str, str] = {}
    # parts[0] 은 첫 헤더 이전(보통 빈 문자열). 이후 [헤더, 본문, 헤더, 본문, ...] 반복.
    for i in range(1, len(parts), 2):
        header = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections[header] = body
    return sections


def _field(section_text: str, label: str) -> str | None:
    """정확히 알려진 레이블("Label: value")의 값을 찾는다. 라벨 자체에 콜론이
    있는 경우(:47A: 부가조건 등)도 처리하려면 greedy `.+` 로 마지막 콜론을
    구분자로 잡아야 한다."""
    pattern = rf"^{re.escape(label)}: (.*)$"
    m = re.search(pattern, section_text, re.M)
    if m is None:
        return None
    value = m.group(1).strip()
    return value or None


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    m = _NUMBER_RE.search(value)
    return float(m.group()) if m else None


def _extract_fields(document_text: str) -> dict[str, Any]:
    """LLM 피처 계산에 필요한 값만 문서 텍스트에서 뽑아낸다.

    ★ 채널 독립: 여기 있는 건 서류에 실제로 적힌 값뿐이다. `injected_defects`,
    룰 코드, 룰 발화 벡터는 애초에 `render_document_set()` 출력에 없다(그
    함수의 계약, render.py 참고) — 이 함수가 그걸 다시 확인할 필요가 없다.
    """
    sections = _split_sections(document_text)
    bl = sections.get(_BL_HEADER, "")
    lc = sections.get(_LC_HEADER, "")
    invoice = sections.get(_INVOICE_HEADER, "")
    packing = sections.get(_PACKING_HEADER, "")

    lc_47a_text = _field(lc, ":47A: 부가조건")
    lc_present = lc_47a_text is not None

    return {
        "bl_consignee": _field(bl, "Consignee"),
        "bl_goods": _field(bl, "Goods Description"),
        "bl_qty": _parse_number(_field(bl, "Package Quantity")),
        "bl_weight": _parse_number(_field(bl, "Gross Weight")),
        "invoice_consignee": _field(invoice, "Consignee"),
        "invoice_goods": _field(invoice, "Goods Description"),
        "invoice_amount": _parse_number(_field(invoice, "Invoice Amount")),
        "unit_price": _parse_number(_field(invoice, "Unit Price")),
        "packing_qty": _parse_number(_field(packing, "Package Quantity (sum)")),
        "packing_weight": _parse_number(_field(packing, "Weight (sum)")),
        "lc_present": lc_present,
        "lc_47a_text": lc_47a_text or "",
        "lc_required_doc_count": _parse_number(_field(lc, ":46A: 필요서류 종수")),
    }


# ---------------------------------------------------------------------------
# 토큰 집합 유사도 — offline 백엔드의 유일한 "의미론적" 근사. 실제 의미
# 이해는 10단계 Gemini 백엔드의 몫이다(이 함수들은 그 자리표시자).
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.upper()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _overlap_coefficient(a: str, b: str) -> float:
    """Szymkiewicz–Simpson 중첩계수 = |A∩B| / min(|A|,|B|).

    자카드(대칭 유사도)와 달리 "한쪽이 다른 쪽 표현을 포함/부분집합으로
    감싸는가"를 잡는 비대칭 지표다 — `vary_wording()` 이 만드는 약어/어순
    변형(생성기 5.3 표기 변동)에서 자카드와 다르게 움직이므로 두 번째 의미론적
    피처(`llm_goods_invoice_semantic_equiv`)로 쓸 근거가 된다.
    """
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


# ---------------------------------------------------------------------------
# :47A: 조건 검증가능성 분류 — 언어적 단서만 사용 (설계서 §5.3.2 "오프라인 분류기는
# 오라클이면 안 된다", HANDOFF.md 9단계).
#
# ★★ 여기가 이 파일에서 두 번째로 중요한 방어선이다 ★★ generator.LC_47A_VERIFIABLE_POOL
# / LC_47A_UNVERIFIABLE_POOL(풀 소속)은 이 모듈에서 import 하지 않는다 — 그
# 정보로 분류하면 주입량(§5.3.2 혼합비)을 그대로 되읽는 오라클이 되어, 무하자/하자
# 혼합비 범위를 아무리 겹치게 잡아도 이 피처 하나가 완전분리를 만든다(설계서
# §5.3.2 경고). 이 함수가 아는 것은 조건문의 표면 텍스트뿐이다.
#
# 검증가능 신호: 서류 명사(BILL OF LADING/INVOICE/CERTIFICATE/PACKING LIST),
# 표기·기재 동사(MARKED/STATED/SHOW/EVIDENCE). 검증불가 신호: 외부 행위 동사
# (NOTIFY/CONFIRM/ARRANGE/INFORM/ADVISE), 서류 밖 당사자·채널(BY EMAIL/BY FAX/
# APPLICANT), 시점 표현(WITHIN...DAYS OF).
#
# 이 분류기는 **틀린다** — 단서가 하나도 없는 문장(예: "DOCUMENTS MUST BE ISSUED
# IN ENGLISH ONLY")은 검증불가 쪽으로 기본값이 매겨진다. 그 오분류가 곧 무하자/
# 하자 분포가 겹치는 현실적 잡음이다(§5.3.2 "이 분류기는 틀린다. 그 오분류가 곧
# 현실적인 중첩이며, 없으면 워터마크다"). `tests/test_llm_features.py` 의
# 정확도 검사가 이 분류기를 참 라벨(풀 소속) 대비 **0.95 미만**으로 묶어 둔다 —
# 나중에 "개선"해서 오라클로 만드는 걸 막기 위해서다.
# ---------------------------------------------------------------------------

_47A_VERIFIABLE_MARKERS: tuple[str, ...] = (
    "BILL OF LADING",
    "INVOICE",
    "CERTIFICATE",
    "PACKING LIST",
    "MARKED",
    "STATED",
    "SHOW",
    "EVIDENCE",
)
_47A_UNVERIFIABLE_MARKERS: tuple[str, ...] = (
    "NOTIFY",
    "CONFIRM",
    "ARRANGE",
    "INFORM",
    "ADVISE",
    "BY EMAIL",
    "BY FAX",
    "APPLICANT",
)
_47A_TIMING_CLAUSE_RE = re.compile(r"WITHIN.*DAYS OF")


def _is_unverifiable_47a_condition(condition_text: str) -> bool:
    """조건문 1건을 언어적 단서만으로 검증가능/검증불가 판정한다(위 방어선 참고).

    단서가 동점(흔히 0 대 0, 즉 어느 신호도 못 찾음)이면 검증불가로 기운다 —
    "확인할 근거 문구를 못 찾았다"를 "서류만으로는 확인 못 한다"는 보수적
    기본값으로 다루는 것이며, 이 기본값 자체가 §5.3.2 가 요구하는 오분류의
    근원 중 하나다(근거 문구가 없는 검증가능 조건 일부가 여기서 틀린다).
    """
    t = condition_text.upper()
    verifiable_score = sum(1 for marker in _47A_VERIFIABLE_MARKERS if marker in t)
    unverifiable_score = sum(1 for marker in _47A_UNVERIFIABLE_MARKERS if marker in t)
    if _47A_TIMING_CLAUSE_RE.search(t):
        unverifiable_score += 1
    return unverifiable_score >= verifiable_score


def _classify_47a_conditions(lc_47a_text: str) -> tuple[float | None, int | None]:
    """:47A: 조건문 전체를 조건 단위로 나눠 분류하고 (검증가능 비율, 검증불가
    개수)를 낸다. 조건이 하나도 없으면(L/C 없음 등) 근거가 없으므로 (None, None)."""
    conditions = [c.strip() for c in lc_47a_text.split(";") if c.strip()]
    if not conditions:
        return None, None
    unverifiable_flags = [_is_unverifiable_47a_condition(c) for c in conditions]
    unverifiable_count = sum(unverifiable_flags)
    verifiable_ratio = (len(conditions) - unverifiable_count) / len(conditions)
    return verifiable_ratio, unverifiable_count


def _numeric_conflict(a: float | None, b: float | None, threshold: float = 0.10) -> int:
    if a is None or b is None:
        return 0
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0
    return 1 if abs(a - b) / denom > threshold else 0


def _lc_complexity(lc_47a_text: str) -> float:
    """:47A: 조건 개수·길이에서 정규화한 복잡도 점수(0~1 근방).

    generator.py 무하자 건 기준 condition_count 1~6, 조건당 40~180자
    (LC_47A_CONDITION_POOL) → 자연 상한을 조건 6개·800자 근방으로 잡는다.
    """
    condition_count = len([c for c in lc_47a_text.split(";") if c.strip()])
    length = len(lc_47a_text)
    return 0.5 * min(condition_count / 6.0, 1.0) + 0.5 * min(length / 800.0, 1.0)


def _offline_features(document_text: str) -> LLMFeatures:
    """설계서 §5.5 "두 개의 백엔드" 패턴의 오프라인 쪽 — 결정론적 휴리스틱.

    ★ 지터 없음. 이 계산은 문서 텍스트만의 순수 함수다 — 호출 순서·배치 크기에
    의존하는 요소가 전혀 없다(계획서 8단계 Task 3 "결정성" 요건을 지터를 아예
    안 씀으로써 만족한다). 나중에 지터가 필요해지면 반드시 콘텐츠 해시로만
    시드해야 한다(공유 RNG·호출 순서 금지).

    47A verifiable/unverifiable 두 피처는 9단계(§5.3.2, HANDOFF.md)부터
    `_classify_47a_conditions()`(위 "언어적 단서" 분류기)로 값을 낸다 — 풀 소속이
    아니라 문장 텍스트만 본다. L/C 가 없거나 조건이 하나도 없으면 여전히
    근거가 없으므로 NaN 이다.
    """
    f = _extract_fields(document_text)

    bl_goods = f["bl_goods"] or ""
    invoice_goods = f["invoice_goods"] or ""
    goods_semantic_equiv = _jaccard(bl_goods, invoice_goods) if (bl_goods or invoice_goods) else None
    goods_invoice_semantic_equiv = (
        _overlap_coefficient(bl_goods, invoice_goods) if (bl_goods or invoice_goods) else None
    )

    bl_consignee = f["bl_consignee"] or ""
    invoice_consignee = f["invoice_consignee"] or ""
    party_pairs = [(bl_consignee, invoice_consignee)] if (bl_consignee or invoice_consignee) else []
    party_equivs = [_jaccard(a, b) for a, b in party_pairs]
    party_semantic_equiv_min = min(party_equivs) if party_equivs else None

    computed_amount = (
        f["bl_qty"] * f["unit_price"] if f["bl_qty"] is not None and f["unit_price"] is not None else None
    )
    doc_conflict_count = (
        (1 if goods_semantic_equiv is not None and goods_semantic_equiv < 0.5 else 0)
        + (1 if party_semantic_equiv_min is not None and party_semantic_equiv_min < 0.5 else 0)
        + _numeric_conflict(f["bl_qty"], f["packing_qty"])
        + _numeric_conflict(f["bl_weight"], f["packing_weight"])
        + _numeric_conflict(f["invoice_amount"], computed_amount)
    )

    lc_complexity_score = _lc_complexity(f["lc_47a_text"]) if f["lc_present"] else None
    verifiable_47a_ratio, unverifiable_47a_count = (
        _classify_47a_conditions(f["lc_47a_text"]) if f["lc_present"] else (None, None)
    )

    return LLMFeatures(
        verifiable_47a_ratio=verifiable_47a_ratio,
        unverifiable_47a_count=unverifiable_47a_count,
        goods_semantic_equiv=goods_semantic_equiv,
        goods_invoice_semantic_equiv=goods_invoice_semantic_equiv,
        party_semantic_equiv_min=party_semantic_equiv_min,
        doc_conflict_count=doc_conflict_count,
        lc_complexity_score=lc_complexity_score,
    )


def _content_hash(backend: str, document_text: str) -> str:
    key = f"{backend}|{LLM_FEATURE_HEURISTIC_VERSION}|{document_text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _record_from_features(
    h: str, shipment_id: str, feats: LLMFeatures, *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    record = {
        "hash": h,
        "shipment_id": shipment_id,
        "verifiable_47a_ratio": feats.verifiable_47a_ratio,
        "unverifiable_47a_count": feats.unverifiable_47a_count,
        "goods_semantic_equiv": feats.goods_semantic_equiv,
        "goods_invoice_semantic_equiv": feats.goods_invoice_semantic_equiv,
        "party_semantic_equiv_min": feats.party_semantic_equiv_min,
        "doc_conflict_count": feats.doc_conflict_count,
        "lc_complexity_score": feats.lc_complexity_score,
    }
    if extra:
        # model_version 은 서버 측 무통보 모델 교체를 사후에 감지하는 유일한 단서다
        # (계획서 10단계 Task 1 "silent server-side model rotation"). 캐시에 남겨
        # 두면 나중에 캐시 파일만 훑어도 교체 시점을 특정할 수 있다.
        record["model"] = config.GEMINI_FEATURE_MODEL
        record["model_version"] = extra.get("model_version")
        record["input_tokens"] = extra.get("input_tokens")
        record["output_tokens"] = extra.get("output_tokens")
    return record


def _features_from_record(record: dict[str, Any]) -> LLMFeatures:
    return LLMFeatures(
        verifiable_47a_ratio=record.get("verifiable_47a_ratio"),
        unverifiable_47a_count=record.get("unverifiable_47a_count"),
        goods_semantic_equiv=record.get("goods_semantic_equiv"),
        goods_invoice_semantic_equiv=record.get("goods_invoice_semantic_equiv"),
        party_semantic_equiv_min=record.get("party_semantic_equiv_min"),
        doc_conflict_count=record.get("doc_conflict_count"),
        lc_complexity_score=record.get("lc_complexity_score"),
    )


# ---------------------------------------------------------------------------
# Gemini 백엔드 (계획서 10단계, HANDOFF.md "10단계 실측"의 숫자 위에서 구현한다)
#
# 설계는 synth/review.py 의 claude 백엔드(설계서 5.5)와 의도적으로 대칭이다 —
# 프롬프트 버전 상수, content-hash 에 모델 ID·프롬프트 버전 포함, 재시도 후
# constant_table류 폴백(여기서는 offline), API 키 부재 시 명확한 에러. 다른 점은
# 전송 계층뿐이다: claude 는 Batches API(폴링)를 쓰고, gemini 는 동기 호출을
# 스레드풀 동시성 + RPM 토큰버킷으로 병렬화한다(무료 등급 분당 호출 한도 때문 —
# Batches API 에 준하는 절감 경로가 없다).
# ---------------------------------------------------------------------------

# 프롬프트 버전 — build_gemini_prompt() 의 문구를 바꾸면 이 값을 올린다.
# _gemini_content_hash() 가 모델 ID(config.GEMINI_FEATURE_MODEL)와 이 값을 함께
# 해시하므로, 모델이나 프롬프트가 바뀌면 캐시가 자동으로 무효화되고 재계산된다
# (review.py::PROMPT_VERSION 과 같은 패턴, 설계서 12절 체크리스트).
GEMINI_PROMPT_VERSION = "v1"


class GeminiSchemaViolation(Exception):
    """Gemini 응답이 7개 정량 지표 스키마를 어겼을 때(review.SchemaViolation 대응)."""


# response_schema — Pydantic 모델이 아니라 평범한 dict 를 쓴다. Pydantic 모델을
# 넘기면 SDK 가 automatic function calling 경로로 들어가며 경고를 낸다는 걸
# 스모크 테스트로 실측했다(HANDOFF.md 10단계). additionalProperties 같은 JSON
# Schema 전용 키워드는 Gemini 구조적 출력이 지원하지 않으므로 넣지 않는다.
_GEMINI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verifiable_47a_ratio": {"type": "number"},
        "unverifiable_47a_count": {"type": "integer"},
        "goods_semantic_equiv": {"type": "number"},
        "goods_invoice_semantic_equiv": {"type": "number"},
        "party_semantic_equiv_min": {"type": "number"},
        "doc_conflict_count": {"type": "integer"},
        "lc_complexity_score": {"type": "number"},
    },
    "required": [
        "verifiable_47a_ratio",
        "unverifiable_47a_count",
        "goods_semantic_equiv",
        "goods_invoice_semantic_equiv",
        "party_semantic_equiv_min",
        "doc_conflict_count",
        "lc_complexity_score",
    ],
}

_GEMINI_RATIO_FIELDS: tuple[str, ...] = (
    "verifiable_47a_ratio",
    "goods_semantic_equiv",
    "goods_invoice_semantic_equiv",
    "party_semantic_equiv_min",
    "lc_complexity_score",
)
_GEMINI_COUNT_FIELDS: tuple[str, ...] = ("unverifiable_47a_count", "doc_conflict_count")


def build_gemini_prompt(document_text: str) -> str:
    """계획서 10단계 Task 2 — 실측 검증된 프롬프트(HANDOFF.md 10단계 스모크 테스트).

    ★★ 라벨 누수 차단 (HANDOFF.md 불변식 2, 이 함수에서 가장 중요한 규칙) ★★
    정량 지표 7개만 요청한다. 하자 여부·수리/거절 판정은 절대 요청하지 않는다 —
    묻는 순간 이 채널이 review.py(채널 B)와 같은 잠재변수를 공유하게 되어
    누수가 되고, 이 저장소의 어떤 통계 검정도 그걸 못 잡는다(review.py 상단
    docstring과 동일 경고). `injected_defects`/`covered_by_rule`/룰 코드/
    ACCEPTED/REJECTED 는 이 함수뿐 아니라 `document_text`(render_document_set()
    출력)에도 절대 없다 — `tests/test_llm_features_gemini.py` 가 금지 문자열
    부재를 강제한다.
    """
    return (
        "당신은 무역서류 분석기입니다. 아래 서류에서 정량 지표만 산출하세요.\n"
        "하자 여부·수리/거절 판정은 절대 하지 마세요.\n\n"
        f"{document_text}\n\n"
        "다음 7개 정량 지표만 JSON으로 산출하세요(다른 텍스트 없이):\n"
        "verifiable_47a_ratio(0~1), unverifiable_47a_count(0 이상 정수),\n"
        "goods_semantic_equiv(0~1), goods_invoice_semantic_equiv(0~1),\n"
        "party_semantic_equiv_min(0~1), doc_conflict_count(0 이상 정수),\n"
        "lc_complexity_score(0~1)."
    )


def _gemini_content_hash(document_text: str) -> str:
    """캐시 키 — 모델 ID·프롬프트 버전·문서 내용을 함께 해시한다(review.content_hash
    와 같은 이유: 모델이나 프롬프트가 바뀐 뒤에도 낡은 결과를 조용히 재사용하는
    사고를 막는다, 설계서 12절 체크리스트)."""
    key = f"gemini|{config.GEMINI_FEATURE_MODEL}|{GEMINI_PROMPT_VERSION}|{document_text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def parse_gemini_response(text: str) -> LLMFeatures:
    """Gemini 구조적 출력 텍스트 → 검증된 LLMFeatures(review.parse_verdict_response 대응).

    계약 위반(필드 누락·타입 오류) 또는 NaN/inf 는 GeminiSchemaViolation 으로
    거부한다(재시도 대상, Task 3). 0~1 비율은 **클램프**한다 — 환각으로 나온
    `47.0` 같은 값을 그대로 흘려보내면 피처 분포를 조용히 망가뜨리는데, 어떤
    기존 테스트도 그걸 잡지 못한다(계획서 10단계 Task 3 경고).
    """
    # raw_decode 는 **첫 JSON 객체까지만** 읽고 뒤에 남은 텍스트를 무시한다.
    # gemma-* 는 response_schema 를 지키면서도 객체 뒤에 여분 텍스트를 덧붙이는
    # 경우가 있어(실측: "Extra data: line 10 column 1"), json.loads 로는 전량
    # 파싱 실패했다. gemini-* 는 여분을 붙이지 않아 동작 차이가 없다.
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text.strip())
    except json.JSONDecodeError as exc:
        raise GeminiSchemaViolation(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GeminiSchemaViolation("응답이 object 가 아닙니다")

    values: dict[str, float] = {}
    for name in (*_GEMINI_RATIO_FIELDS, *_GEMINI_COUNT_FIELDS):
        if name not in parsed:
            raise GeminiSchemaViolation(f"필드 누락: {name}")
        raw = parsed[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise GeminiSchemaViolation(f"{name} 가 숫자가 아닙니다: {raw!r}")
        value = float(raw)
        if math.isnan(value) or math.isinf(value):
            raise GeminiSchemaViolation(f"{name} 가 NaN/inf 입니다: {raw!r}")
        values[name] = value

    for name in _GEMINI_RATIO_FIELDS:
        values[name] = max(0.0, min(1.0, values[name]))

    return LLMFeatures(
        verifiable_47a_ratio=values["verifiable_47a_ratio"],
        unverifiable_47a_count=int(round(values["unverifiable_47a_count"])),
        goods_semantic_equiv=values["goods_semantic_equiv"],
        goods_invoice_semantic_equiv=values["goods_invoice_semantic_equiv"],
        party_semantic_equiv_min=values["party_semantic_equiv_min"],
        doc_conflict_count=int(round(values["doc_conflict_count"])),
        lc_complexity_score=values["lc_complexity_score"],
    )


def _require_gemini_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "config.LLM_FEATURE_BACKEND='gemini' 이지만 GEMINI_API_KEY 환경변수가 "
            "설정되어 있지 않습니다.\n"
            "  - API 키가 있다면: `export GEMINI_API_KEY=...` 후 다시 실행하세요.\n"
            "  - API 키가 없다면: LLM_FEATURE_BACKEND(또는 환경변수 "
            "DEFECT_MODEL_LLM_FEATURE_BACKEND)를 'offline' 으로 두세요(기본값).\n"
            "  - 캐시(ai/f3_research/data/llm_features/*.jsonl)에 이미 있는 건은 "
            "API 키 없이도 재사용됩니다(review.py 판정 캐시와 같은 재현성 아티팩트)."
        )
    return api_key


def _get_gemini_client(client: Any | None = None) -> Any:
    if client is not None:
        return client
    _require_gemini_api_key()
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - 환경에 google-genai 미설치 시
        raise RuntimeError(
            "gemini 백엔드를 쓰려면 `google-genai` 패키지가 필요합니다. "
            "`uv add google-genai` (또는 `pip install google-genai`) 후 다시 시도하세요."
        ) from exc
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """503(ServerError)·429(rate limit, ClientError)만 재시도 대상으로 본다.

    HANDOFF.md 10단계 실측: "503 은 예외가 아니라 상시 발생한다. 백오프·재시도는
    선택이 아니라 필수." 그 외(인증 오류 등 4xx)는 재시도해도 같은 결과가
    나올 결정론적 오류라 즉시 폴백한다(재시도 예산 낭비 방지).
    """
    try:
        from google.genai import errors
    except ImportError:  # pragma: no cover - google-genai 미설치 환경
        return False
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return getattr(exc, "code", None) == 429
    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    """예외에 실린 HTTP 응답의 Retry-After 헤더를 읽는다(있으면 백오프보다 우선)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sleep_backoff(attempt: int, retry_after: float | None) -> None:
    """지수 백오프 + 지터. Retry-After 헤더가 있으면 그 값을 그대로 쓴다."""
    if retry_after is not None:
        delay = max(0.0, retry_after)
    else:
        delay = min(
            config.GEMINI_BACKOFF_BASE_SECONDS * (2**attempt),
            config.GEMINI_BACKOFF_MAX_SECONDS,
        )
    jitter = random.uniform(0.0, config.GEMINI_BACKOFF_JITTER_SECONDS)
    time.sleep(delay + jitter)


class _RateLimiter:
    """토큰 버킷 방식 RPM 리미터 — 무료 등급의 분당 호출 한도를 지킨다.

    스레드풀에서 여러 워커가 동시에 `acquire()` 를 부를 수 있으므로 락으로
    "다음 허용 시각"을 원자적으로 예약한다(간단한 leaky-bucket 근사).
    """

    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_allowed)
            self._next_allowed = start + self._interval
        wait = start - now
        if wait > 0:
            time.sleep(wait)


def _call_gemini_single(
    client: Any,
    document_text: str,
    *,
    max_retries: int,
    rate_limiter: "_RateLimiter",
) -> tuple[LLMFeatures | None, dict[str, Any]]:
    """문서 1건을 Gemini 로 호출한다 — 실패는 절대 예외로 새어나가지 않는다
    (계획서 10단계 "Failures must never be fatal — a partial run has to be
    resumable"). 최종 실패 시 (None, meta) 를 반환해 호출부가 offline 로 폴백한다.
    """
    prompt = build_gemini_prompt(document_text)
    meta: dict[str, Any] = {
        "attempts": 0,
        "retries": 0,
        "model_version": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "error": None,
    }
    attempt = 0
    try:
        while True:
            rate_limiter.acquire()
            meta["attempts"] += 1
            try:
                response = client.models.generate_content(
                    model=config.GEMINI_FEATURE_MODEL,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": _GEMINI_RESPONSE_SCHEMA,
                        "temperature": 0,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - google.genai.errors.APIError 등
                meta["error"] = repr(exc)
                if attempt < max_retries and _is_retryable_gemini_error(exc):
                    _sleep_backoff(attempt, _retry_after_seconds(exc))
                    attempt += 1
                    meta["retries"] = attempt
                    continue
                return None, meta

            usage = getattr(response, "usage_metadata", None)
            meta["model_version"] = getattr(response, "model_version", None)
            meta["input_tokens"] = getattr(usage, "prompt_token_count", None) or 0
            meta["output_tokens"] = getattr(usage, "candidates_token_count", None) or 0

            try:
                text = getattr(response, "text", None)
                if text is None:
                    raise GeminiSchemaViolation("응답에 text 파트가 없습니다")
                feats = parse_gemini_response(text)
            except GeminiSchemaViolation as exc:
                meta["error"] = str(exc)
                if attempt < max_retries:
                    _sleep_backoff(attempt, None)
                    attempt += 1
                    meta["retries"] = attempt
                    continue
                return None, meta

            meta["error"] = None
            return feats, meta
    except Exception as exc:  # noqa: BLE001 - 예상치 못한 버그도 폴백 경로로 흡수한다
        meta["error"] = f"unexpected: {exc!r}"
        return None, meta


def _run_gemini_batch(
    items: list[tuple[str, str]],
    *,
    client: Any | None,
    cache: JsonlCache,
    max_retries: int,
    max_concurrency: int,
    rpm_limit: int,
) -> tuple[dict[str, LLMFeatures | None], int, list[dict[str, Any]], int]:
    """Gemini 배치 호출 본체 — (by_id, fallback_count, call_records, cache_hits).

    `call_records` 는 실제로 호출을 시도한 건만 담는다(캐시 히트는 제외) —
    `cli.py::cmd_llm_pilot` 이 토큰·재시도·model_version 리포트에 쓴다.
    """
    by_id: dict[str, LLMFeatures | None] = {}
    pending: list[tuple[str, str, str]] = []
    cache_hits = 0

    for shipment_id, document_text in items:
        h = _gemini_content_hash(document_text)
        cached = cache.get(h)
        if cached is not None:
            by_id[shipment_id] = _features_from_record(cached)
            cache_hits += 1
            continue
        pending.append((shipment_id, document_text, h))

    call_records: list[dict[str, Any]] = []
    fallback_count = 0

    if pending:
        # 캐시가 전부 히트면 클라이언트를 아예 만들지 않는다(API 키도 필요 없다) —
        # review.py::judge_batch_claude 와 같은 지연 해석 패턴.
        resolved_client = _get_gemini_client(client)
        rate_limiter = _RateLimiter(rpm_limit)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            future_to_item = {
                pool.submit(
                    _call_gemini_single,
                    resolved_client,
                    document_text,
                    max_retries=max_retries,
                    rate_limiter=rate_limiter,
                ): (shipment_id, document_text, h)
                for shipment_id, document_text, h in pending
            }
            for future in concurrent.futures.as_completed(future_to_item):
                shipment_id, document_text, h = future_to_item[future]
                feats, meta = future.result()
                record = dict(meta)
                record["shipment_id"] = shipment_id
                record["success"] = feats is not None
                call_records.append(record)
                if feats is not None:
                    # backend 를 레코드에 명시한다 — 캐시 키(해시)에는 백엔드가
                    # 들어 있지만 파일을 눈으로 봐서는 알 수 없다. 재현성
                    # 아티팩트는 사람이 읽고 출처를 판별할 수 있어야 한다.
                    cache.put(
                        _record_from_features(
                            h, shipment_id, feats, extra={**meta, "backend": "gemini"}
                        )
                    )
                    by_id[shipment_id] = feats
                else:
                    fallback_count += 1
                    by_id[shipment_id] = _offline_features(document_text)

    return by_id, fallback_count, call_records, cache_hits


@dataclass
class GeminiPilotReport:
    """`cli.py::cmd_llm_pilot` 출력용 요약(계획서 10단계 Task 5)."""

    total: int
    successes: int
    fallbacks: int
    cache_hits: int
    total_input_tokens: int
    total_output_tokens: int
    wall_clock_seconds: float
    observed_rpm: float
    model_versions: list[str] = field(default_factory=list)
    retries_total: int = 0
    errors: list[str] = field(default_factory=list)

    def estimated_cost_usd(self) -> float:
        return (
            self.total_input_tokens / 1_000_000 * config.GEMINI_INPUT_PRICE_PER_MTOK
            + self.total_output_tokens / 1_000_000 * config.GEMINI_OUTPUT_PRICE_PER_MTOK
        )


def run_gemini_pilot(
    items: list[tuple[str, str]],
    *,
    client: Any | None = None,
    cache: JsonlCache | None = None,
) -> GeminiPilotReport:
    """N건에 대해 Gemini 백엔드를 실행하고 관측치를 요약한다(계획서 10단계 Task 5).

    `compute_features_batch()` 와 달리 (by_id, fallback_count) 2튜플 계약에
    묶이지 않는다 — 파일럿 CLI 전용 진입점이라 토큰·재시도·model_version 같은
    풍부한 관측치를 그대로 반환한다. 채널 독립 가드는 여기서도 가장 먼저 돈다.
    """
    check_channel_independence(llm_feature_backend="gemini")

    resolved_cache = cache if cache is not None else JsonlCache(config.LLM_FEATURE_CACHE_FILE)

    start = time.monotonic()
    by_id, fallback_count, call_records, cache_hits = _run_gemini_batch(
        items,
        client=client,
        cache=resolved_cache,
        max_retries=config.GEMINI_MAX_RETRIES,
        max_concurrency=config.GEMINI_MAX_CONCURRENCY,
        rpm_limit=config.GEMINI_RPM_LIMIT,
    )
    wall_clock = time.monotonic() - start

    successes = sum(1 for r in call_records if r["success"])
    total_input_tokens = sum(r.get("input_tokens") or 0 for r in call_records)
    total_output_tokens = sum(r.get("output_tokens") or 0 for r in call_records)
    retries_total = sum(r.get("retries") or 0 for r in call_records)
    total_attempts = sum(r.get("attempts") or 0 for r in call_records)
    model_versions = sorted({r["model_version"] for r in call_records if r.get("model_version")})
    errors = [f"{r['shipment_id']}: {r['error']}" for r in call_records if r.get("error")]
    observed_rpm = (total_attempts / wall_clock * 60.0) if wall_clock > 0 else 0.0

    return GeminiPilotReport(
        total=len(items),
        successes=successes,
        fallbacks=fallback_count,
        cache_hits=cache_hits,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        wall_clock_seconds=wall_clock,
        observed_rpm=observed_rpm,
        model_versions=model_versions,
        retries_total=retries_total,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 공개 진입점 — dataset.py 의 유일한 접점(review.compute_labels() 와 형태를
# 의도적으로 맞춘다, 계획서 8단계 Task 3).
# ---------------------------------------------------------------------------


def compute_features_batch(
    items: list[tuple[str, str]],
    *,
    backend: str | None = None,
    client: Any | None = None,
    cache: JsonlCache | None = None,
) -> tuple[dict[str, LLMFeatures | None], int]:
    """`(shipment_id, document_text)` 목록 → (shipment_id -> LLMFeatures|None, 폴백 건수).

    `client` 는 Gemini 백엔드가 쓰는 자리(테스트 mock 주입용, review.py 의
    `client` 인자와 같은 역할) — offline/null 백엔드는 사용하지 않는다.

    반환 dict 의 값이 `None` 이면 `ShipmentSnapshot.llm=None` 이 되어
    `features.py` 가 `llm_available=0.0`·나머지 NaN 으로 인코딩한다(스키마 계약).
    gemini 백엔드는 이 값을 절대 `None` 으로 두지 않는다 — 실패하면 offline
    휴리스틱으로 폴백한 `LLMFeatures` 를 채운다(계획서 10단계 "Failures must
    never be fatal", `fallback_count` 로 폴백 건수만 알린다).
    """
    backend = backend if backend is not None else config.LLM_FEATURE_BACKEND

    # Task 4: 어떤 작업(캐시 조회 포함)도 시작하기 전에 가장 먼저 검사한다.
    check_channel_independence(llm_feature_backend=backend)

    if backend == "null":
        return {shipment_id: None for shipment_id, _ in items}, 0

    if backend == "gemini":
        resolved_cache = cache if cache is not None else JsonlCache(config.LLM_FEATURE_CACHE_FILE)
        by_id, fallback_count, _call_records, _cache_hits = _run_gemini_batch(
            items,
            client=client,
            cache=resolved_cache,
            max_retries=config.GEMINI_MAX_RETRIES,
            max_concurrency=config.GEMINI_MAX_CONCURRENCY,
            rpm_limit=config.GEMINI_RPM_LIMIT,
        )
        return by_id, fallback_count

    if backend != "offline":
        raise ValueError(f"알 수 없는 LLM_FEATURE_BACKEND: {backend!r}")

    # ⚠️ offline 백엔드는 **캐시에 쓰지 않는다.**
    #
    # 캐시는 "비싼 호출의 재현성 아티팩트"다(설계서 5.5 — 제3자가 키 없이 동일
    # 데이터셋을 재생성할 수 있게 하는 것이 목적). offline 은 순수 결정론 함수라
    # 재계산이 파일 I/O 보다 싸고, 캐시에 남길 재현 가치도 없다.
    #
    # 실제로 이 경로가 캐시를 쓰던 동안 git 추적 파일이 **80,163건 / 24.7MB** 까지
    # 불어났다(Gemini 는 7건). 캐시 키에 backend 접두가 있어 교차 서빙 사고는
    # 없었지만, 재현성 아티팩트로 커밋할 파일이 오프라인 휴리스틱 결과로 뒤덮이는
    # 것은 그 자체로 결함이다. 호출 인자로 cache 를 명시적으로 넘긴 경우에만
    # (테스트가 캐시 동작을 검사하는 경우) 캐시를 쓴다.
    by_id: dict[str, LLMFeatures | None] = {}
    for shipment_id, document_text in items:
        if cache is not None:
            h = _content_hash(backend, document_text)
            cached = cache.get(h)
            if cached is not None:
                by_id[shipment_id] = _features_from_record(cached)
                continue
            feats = _offline_features(document_text)
            cache.put(_record_from_features(h, shipment_id, feats))
        else:
            feats = _offline_features(document_text)
        by_id[shipment_id] = feats

    return by_id, 0

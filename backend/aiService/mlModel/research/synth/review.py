"""[채널 B] 모의 심사기 (설계서 5.5).

`injected_defects[]` → 은행 판정 `y ∈ {0=수리, 1=하자}`.

★★ 라벨 누수 차단 불변식 (설계서 1절) ★★
이 모듈은 `synth/rule_sim.py` 를 import 하지 않는다. 룰엔진도 import 하지 않는다.

두 개의 교체 가능한 백엔드를 제공하고 `config.REVIEWER_BACKEND` 로 고른다(설계서 5.5).

- `constant_table`: 룰 발화 여부와 무관하게, ICC/ISBP 공표 하자 유형별 은행
  적발 확률(p_detect)과 은행 재량 노이즈만으로 y 를 결정한다. 기본값·오프라인.
- `claude`: Claude 가 서류 세트(B/L·L/C·송장·포장명세서)만 읽고 UCP600/ISBP
  심사역 관점에서 판정한다. **`injected_defects`, `covered_by_rule`, 룰 코드,
  룰 발화 벡터를 프롬프트에 절대 넣지 않는다** — 채널 독립이 "import 안 함"보다
  훨씬 강한 형태로 성립한다(채널 B가 주입 내역 자체를 모른다).

`injector.py` 는 두 채널의 공통 "원료"(injected_defects)를 만들 뿐이며 그
자체로는 어느 채널에도 유리하게 치우치지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
from typing import Any

from f3_research import config
from f3_research.cache import JsonlCache
from f3_research.render import render_document_set
from f3_research.synth.generator import SynthShipment
from f3_research.synth.injector import Defect

__all__ = [
    "P_DETECT",
    "judge",
    "render_document_set",
    "content_hash",
    "build_prompt",
    "ReviewCache",
    "parse_verdict_response",
    "judge_batch_claude",
    "compute_labels",
    "SchemaViolation",
]

# ICC/ISBP 공표 하자 유형 분포 근거의 유형별 적발 확률 상수 테이블(설계서 5.5 예시).
# rule_sim.py(폐기)의 RULE_FIRE_PROB_RANGE(0.85~0.95, 전 유형 동일)와는 독립적으로
# 유형마다 다른 값을 쓴다 — 두 채널이 같은 하자에도 다른 강도로 반응해야
# "룰 발화 ≠ 은행 판정" 관계가 만들어진다.
#
# HANDOFF.md 4b단계(인젝터 재정렬) 갱신 — injector.py 의 COVERED_SPECS/UNCOVERED_SPECS
# 재편에 맞춰 키를 동기화한다. 룰 커버 하자(covered_by_rule=True)는 은행도 거의
# 확실히 잡는다는 전제로 0.85~0.95 대역을 유지한다. 룰 밖 5종(qty/weight/amount/
# consignee 불일치, 원본 통수 부족)의 값은 숫자를 좋게 만들려고 고른 것이 아니라
# ICC 하자 유형 분포 근거다 — 설계서 5.3.1 "룰 밖" 표: 송장·B/L 간 수량·금액
# 불일치는 UCP600 Art.14(d)(서류 상충 금지)·18(c)(송장 기재사항) 위반으로 은행이
# 문면심사에서 가장 먼저·가장 엄격하게 걸러내는 하자 범주다(수량 0.85, 금액 0.85).
# 중량은 계량 방식 차이를 은행이 관행상 더 관대하게 보는 편이라 0.75로 낮춘다.
# 나머지 4종(freeform_47a_unmet 등)은 v3 값을 그대로 유지한다(변경 없음).
P_DETECT: dict[str, float] = {
    "expiry_exceeded": 0.95,
    "presentation_period_exceeded": 0.95,
    "pol_mismatch": 0.90,
    "pod_mismatch": 0.90,
    "bl_consignee_mismatch": 0.90,
    "goods_desc_mismatch": 0.85,
    "weight_over_limit": 0.85,
    "freight_tolerance_breach": 0.80,
    "required_field_missing": 0.90,
    "latest_shipment_exceeded": 0.95,
    "qty_sum_mismatch": 0.85,  # UCP600 Art.14(d)/18(c) — 송장·B/L 수량 불일치는 고적발 범주
    "weight_sum_mismatch": 0.75,  # 계량 방식 차이 — 은행이 관행상 더 관대
    "invoice_amount_mismatch": 0.85,  # 금액은 결제 직결이라 엄격(amount_tolerance_boundary 개명)
    "invoice_consignee_mismatch": 0.80,  # UCP600 Art.14(d) 서류 간 상충(consignee_mismatch 개명)
    "insufficient_originals": 0.85,
    "freeform_47a_unmet": 0.35,
    "goods_wording_diff": 0.45,
    "signer_authority_ambiguous": 0.30,
    "customary_wording_missing": 0.25,
}


def _logit(p: float, eps: float = 1e-6) -> float:
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _judge_constant_table(
    defects: list[Defect],
    bank_strictness: float,
    rng: random.Random,
    *,
    base_false_defect_rate: float,
    lenient_rate: float,
    counterparty_propensity: float = 1.0,
    cargo_type_propensity: float = 1.0,
) -> int:
    """P(하자) = 1 - Π(1 - p_detect) 에 은행 재량 노이즈를 적용해 y 를 뽑는다.

    은행 strictness 는 기존과 동일하게 p_detect 를 직접 배율 조정한다(하위 호환).
    거래처·화물유형 잠재 하자 성향(설계서 4절 Group 6 규칙 3)은 **로그오즈 이동**
    으로 반영한다 — 다중 하자 건은 p_detect 곱이 이미 1 근처로 포화돼 있어
    단순 배율로는 성향의 효과가 거의 사라지기 때문이다(성향이 커도 이미 1인
    확률은 더 커질 수 없다). 로그오즈 이동은 포화된 확률에서도 유의미한 이동을
    남긴다 — 이 경로가 있어야 이력 기간(history period)에서 관측한 비율이
    잠재 성향을 향해 실제로 수렴하고, HISTORY 피처군이 정당한 신호를 갖는다
    (v2는 이 경로가 없어 성향이 누수 운반체로만 존재했다).
    """
    if not defects:
        p_base = min(1.0, base_false_defect_rate * bank_strictness)
    else:
        p_no_detect = 1.0
        for defect in defects:
            p_detect = P_DETECT.get(defect.type, 0.5) * bank_strictness
            p_detect = max(0.0, min(1.0, p_detect))
            p_no_detect *= 1.0 - p_detect
        p_base = 1.0 - p_no_detect

    logit_shift = math.log(max(counterparty_propensity, 1e-6)) + math.log(max(cargo_type_propensity, 1e-6))
    p_defect = _sigmoid(_logit(p_base) + logit_shift) if logit_shift != 0.0 else p_base

    y = 1 if rng.random() < p_defect else 0
    if y == 1 and rng.random() < lenient_rate:
        y = 0  # 은행 재량으로 수리(레니언트) — 오탐 억제 케이스의 근거
    return y


def judge(
    defects: list[Defect],
    bank_strictness: float,
    rng: random.Random,
    *,
    base_false_defect_rate: float = config.BASE_FALSE_DEFECT_RATE,
    lenient_rate: float = config.LENIENT_RATE,
    counterparty_propensity: float = 1.0,
    cargo_type_propensity: float = 1.0,
) -> int:
    """하위 호환용 진입점 — 항상 constant_table 백엔드를 쓴다.

    데이터셋 생성 파이프라인(dataset.py)은 `compute_labels()` 를 통해 백엔드를
    선택한다. 이 함수는 백엔드 선택이 필요 없는 단발성 호출(테스트 등)을 위해 남긴다.
    """
    return _judge_constant_table(
        defects,
        bank_strictness,
        rng,
        base_false_defect_rate=base_false_defect_rate,
        lenient_rate=lenient_rate,
        counterparty_propensity=counterparty_propensity,
        cargo_type_propensity=cargo_type_propensity,
    )


# ---------------------------------------------------------------------------
# Claude 백엔드 (설계서 5.5 "두 개의 백엔드")
# ---------------------------------------------------------------------------

_VERDICT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ACCEPTED", "REJECTED"]},
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "field": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["code", "field", "rationale"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "reasons", "confidence"],
    "additionalProperties": False,
}


class SchemaViolation(Exception):
    """Claude 응답이 구조적 출력 계약(verdict/reasons/confidence)을 어겼을 때."""


# 프롬프트 버전 — build_prompt()/render_document_set() 의 문구를 바꾸면 이 값을
# 올린다. content_hash() 가 모델 ID(config.CLAUDE_REVIEW_MODEL)와 이 값을 함께
# 해시하므로, 모델이나 프롬프트가 바뀌면 캐시가 자동으로 무효화되고 재판정된다
# (설계서 12절 체크리스트 "판정 캐시 키에 모델 ID와 프롬프트 버전이 포함된다").
PROMPT_VERSION = "v1"


def content_hash(shipment: SynthShipment) -> str:
    """선적 내용 해시 — 캐시 키(설계서 5.5 "판정 캐시가 재현성 아티팩트다").

    문서 내용뿐 아니라 모델 ID·프롬프트 버전도 함께 해시한다 — 둘 중 하나만
    바뀌어도 이전 캐시 항목이 자동으로 무효화되고 재판정되게 하기 위함이다
    (설계서 12절 체크리스트, 검증자 지적: 문서 텍스트만 해시하면 모델·프롬프트가
    바뀐 뒤에도 낡은 판정을 조용히 재사용하게 된다).
    """
    document_text = render_document_set(shipment)
    key = f"{config.CLAUDE_REVIEW_MODEL}|{PROMPT_VERSION}|{document_text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def build_prompt(document_text: str) -> str:
    """Claude 심사 프롬프트. `injected_defects`/`covered_by_rule`/룰 코드/룰
    발화 벡터는 절대 넣지 않는다 — document_text 는 render_document_set() 의
    반환값이어야 한다(그 함수 자체가 이 불변식을 지킨다)."""
    return (
        "당신은 UCP600 과 ISBP 관행에 정통한 신용장 매입은행의 서류 심사역입니다.\n"
        "아래 서류 세트(선하증권, 신용장 조건, 상업송장, 포장명세서)만 보고,\n"
        "서류가 신용장 조건 및 UCP600/ISBP 관행에 부합하는지 판단하세요.\n"
        "서류에 나타나지 않은 정보나 배경지식을 가정하지 말고, 아래 텍스트에\n"
        "실제로 적힌 내용만으로 판단하세요.\n\n"
        f"{document_text}\n"
        "위 서류 세트를 심사해 ACCEPTED(수리) 또는 REJECTED(하자)로 판정하세요.\n"
        "REJECTED 인 경우 각 하자마다 코드(code), 관련 필드(field), 판단 근거\n"
        "(rationale)를 제시하고, 전체 판정에 대한 확신도(confidence, 0~1)를 함께 주세요."
    )


# 판정 캐시 — `ai/f3_research/data/reviews/*.jsonl` (설계서 5.5).
#
# 선적 내용 해시 → 판정을 기록한다. 캐시가 있으면 API를 호출하지 않는다.
# 캐시 파일은 저장소에 포함(커밋)한다 — 제3자가 키 없이 동일 데이터셋을
# 재생성할 수 있게 하는 재현성 아티팩트다.
#
# 계획서 8단계 Task 1: 구현은 `cache.JsonlCache` 로 일반화되어 옮겨졌다(LLM
# 피처 캐시, `llm_features.py` 와 공유). 이 별칭은 하위 호환용이다 —
# `tests/test_review_claude.py::test_review_cache_round_trip` 가 이 이름으로
# 참조한다.
ReviewCache = JsonlCache


def parse_verdict_response(text: str) -> dict[str, Any]:
    """구조적 출력 텍스트 → 검증된 verdict dict. 계약 위반 시 SchemaViolation."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaViolation(f"JSON 파싱 실패: {exc}") from exc

    if not isinstance(parsed, dict):
        raise SchemaViolation("응답이 object 가 아닙니다")
    if parsed.get("verdict") not in ("ACCEPTED", "REJECTED"):
        raise SchemaViolation(f"verdict 값이 유효하지 않습니다: {parsed.get('verdict')!r}")
    reasons = parsed.get("reasons")
    if not isinstance(reasons, list):
        raise SchemaViolation("reasons 가 배열이 아닙니다")
    for r in reasons:
        if not isinstance(r, dict) or not all(k in r for k in ("code", "field", "rationale")):
            raise SchemaViolation(f"reasons 항목 형식이 잘못되었습니다: {r!r}")
    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise SchemaViolation(f"confidence 가 숫자가 아닙니다: {confidence!r}")
    return parsed


def _require_api_key() -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "config.REVIEWER_BACKEND='claude' 이지만 ANTHROPIC_API_KEY 환경변수가 "
            "설정되어 있지 않습니다.\n"
            "  - API 키가 있다면: `export ANTHROPIC_API_KEY=...` 후 다시 실행하세요.\n"
            "  - API 키가 없다면: config.REVIEWER_BACKEND(또는 환경변수 "
            "DEFECT_MODEL_REVIEWER_BACKEND)를 'constant_table' 로 두세요(기본값).\n"
            "  - 캐시(ai/f3_research/data/reviews/*.jsonl)에 이미 있는 건은 "
            "API 키 없이도 재사용됩니다(설계서 5.5 재현성 아티팩트)."
        )
    return api_key


def _get_client(client: Any | None = None) -> Any:
    if client is not None:
        return client
    _require_api_key()
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - 환경에 anthropic 미설치 시
        raise RuntimeError(
            "claude 백엔드를 쓰려면 `anthropic` 패키지가 필요합니다. "
            "`uv add anthropic` (또는 `pip install anthropic`) 후 다시 시도하세요."
        ) from exc
    return anthropic.Anthropic()


def _call_claude_batch(
    prompts: dict[str, str],
    *,
    client: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """{custom_id: prompt} → {custom_id: {"parsed": ...} | {"error": ...}}.

    Batches API 사용(설계서 5.5: "Batch API 로 호출한다... 오프라인 생성이므로
    50% 절감"). structured output 으로 verdict 스키마를 강제한다.
    """
    resolved_client = _get_client(client)

    # 요청은 일반 dict 로 구성한다(anthropic SDK의 batch_create_params 타입은
    # pydantic 모델을 감싼 dict-호환 TypedDict 이므로 그대로 받아들인다) — 이
    # 모듈이 anthropic 패키지의 내부 타입 경로에 하드 의존하지 않도록 하기 위함이다.
    requests = [
        {
            "custom_id": cid,
            "params": {
                "model": config.CLAUDE_REVIEW_MODEL,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
                "output_config": {
                    "format": {"type": "json_schema", "schema": _VERDICT_JSON_SCHEMA}
                },
            },
        }
        for cid, prompt in prompts.items()
    ]

    batch = resolved_client.messages.batches.create(requests=requests)
    while True:
        batch = resolved_client.messages.batches.retrieve(batch.id)
        if batch.processing_status == "ended":
            break
        time.sleep(config.CLAUDE_BATCH_POLL_INTERVAL_SECONDS)

    outcomes: dict[str, dict[str, Any]] = {}
    for result in resolved_client.messages.batches.results(batch.id):
        cid = result.custom_id
        if result.result.type != "succeeded":
            outcomes[cid] = {"error": result.result.type}
            continue
        msg = result.result.message
        if getattr(msg, "stop_reason", None) == "refusal":
            outcomes[cid] = {"error": "refusal"}
            continue
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            outcomes[cid] = {"error": "no_text_block"}
            continue
        try:
            parsed = parse_verdict_response(text)
        except SchemaViolation as exc:
            outcomes[cid] = {"error": f"schema_violation: {exc}"}
            continue
        outcomes[cid] = {"parsed": parsed}
    return outcomes


def judge_batch_claude(
    shipments: list[SynthShipment],
    defects_by_id: dict[str, list[Defect]],
    bank_strictness_by_id: dict[str, float],
    rng_by_id: dict[str, random.Random],
    *,
    client: Any | None = None,
    cache: ReviewCache | None = None,
    max_retries: int = config.CLAUDE_MAX_RETRIES,
) -> tuple[dict[str, int], int]:
    """claude 백엔드로 여러 선적을 일괄 판정한다.

    반환: (shipment_id -> y, 폴백 건수). 실패·거부·스키마 위반은 재시도
    `max_retries`회 후 constant_table 로 폴백하고, 폴백 건수를 반환한다
    (설계서 5.5 — 데이터셋 매니페스트에 기록하는 근거).
    """
    cache = cache if cache is not None else ReviewCache(config.REVIEW_CACHE_FILE)

    y_by_id: dict[str, int] = {}
    doc_by_id: dict[str, str] = {}
    hash_by_id: dict[str, str] = {}
    pending: dict[str, SynthShipment] = {}

    for s in shipments:
        doc = render_document_set(s)
        h = content_hash(s)
        doc_by_id[s.shipment_id] = doc
        hash_by_id[s.shipment_id] = h
        cached = cache.get(h)
        if cached is not None and cached.get("verdict") in ("ACCEPTED", "REJECTED"):
            y_by_id[s.shipment_id] = 1 if cached["verdict"] == "REJECTED" else 0
        else:
            pending[s.shipment_id] = s

    attempt = 0
    while pending and attempt <= max_retries:
        prompts = {sid: build_prompt(doc_by_id[sid]) for sid in pending}
        outcomes = _call_claude_batch(prompts, client=client)
        still_pending: dict[str, SynthShipment] = {}
        for sid, s in pending.items():
            outcome = outcomes.get(sid)
            if outcome is not None and "parsed" in outcome:
                parsed = outcome["parsed"]
                record = {
                    "hash": hash_by_id[sid],
                    "shipment_id": sid,
                    "verdict": parsed["verdict"],
                    "reasons": parsed.get("reasons", []),
                    "confidence": parsed.get("confidence"),
                    "model": config.CLAUDE_REVIEW_MODEL,
                }
                cache.put(record)
                y_by_id[sid] = 1 if parsed["verdict"] == "REJECTED" else 0
            else:
                still_pending[sid] = s
        pending = still_pending
        attempt += 1

    fallback_count = len(pending)
    for sid, s in pending.items():
        y_by_id[sid] = _judge_constant_table(
            defects_by_id[sid],
            bank_strictness_by_id[sid],
            rng_by_id[sid],
            base_false_defect_rate=config.BASE_FALSE_DEFECT_RATE,
            lenient_rate=config.LENIENT_RATE,
            counterparty_propensity=s.counterparty_propensity,
            cargo_type_propensity=s.cargo_type_propensity,
        )

    return y_by_id, fallback_count


def compute_labels(
    items: list[tuple[SynthShipment, list[Defect], random.Random]],
    *,
    backend: str | None = None,
    client: Any | None = None,
    cache: "ReviewCache | None" = None,
) -> tuple[list[int], int]:
    """`(mutated_shipment, defects, review_rng)` 목록 → (y 목록, 폴백 건수).

    dataset.py 의 유일한 진입점. `config.REVIEWER_BACKEND` (또는 인자로 넘긴
    backend)로 constant_table/claude 를 고른다. constant_table 경로는 각 행을
    독립적으로 파생된 review_rng 로 판정한다는 점에서 이전 구현과 동일한
    RNG 소비 시퀀스를 보장한다(재현성 유지).
    """
    backend = backend or config.REVIEWER_BACKEND
    if backend == "claude":
        shipments = [it[0] for it in items]
        defects_by_id = {it[0].shipment_id: it[1] for it in items}
        bank_by_id = {it[0].shipment_id: it[0].bank_strictness for it in items}
        rng_by_id = {it[0].shipment_id: it[2] for it in items}
        y_by_id, fallback_count = judge_batch_claude(
            shipments, defects_by_id, bank_by_id, rng_by_id, client=client, cache=cache
        )
        return [y_by_id[it[0].shipment_id] for it in items], fallback_count

    ys = [
        _judge_constant_table(
            defects,
            mutated.bank_strictness,
            rng,
            base_false_defect_rate=config.BASE_FALSE_DEFECT_RATE,
            lenient_rate=config.LENIENT_RATE,
            counterparty_propensity=mutated.counterparty_propensity,
            cargo_type_propensity=mutated.cargo_type_propensity,
        )
        for mutated, defects, rng in items
    ]
    return ys, 0

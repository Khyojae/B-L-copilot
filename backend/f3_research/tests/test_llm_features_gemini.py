"""gemini 백엔드(계획서 10단계) 단위 테스트 — mocked client. 실제 API 는 호출하지 않는다.

`conftest.py` 의 autouse 픽스처가 GEMINI_API_KEY 를 지우므로, 이 스위트가 네트워크로
나가려면 테스트가 **명시적으로** 키를 다시 넣어야 한다 — 어떤 테스트도 그러지 않는다.

이 파일이 지키는 핵심 계약(계획서 10단계 Task 1~4):
  - 프롬프트가 정량 지표만 요청하고 하자/수리·거절 판정을 절대 묻지 않는다
    (HANDOFF.md 불변식 2 — 채널 결합 방지, 이 저장소에서 가장 중요한 규칙).
  - 503 → 백오프 재시도 → 성공.
  - 재시도 소진 시 offline 로 폴백하고 fallback_count 가 증가하며, 예외가 새지 않는다.
  - 0~1 비율은 클램프하고 NaN/inf 는 거부한다.
  - 캐시 히트는 클라이언트를 전혀 건드리지 않는다.
  - 캐시 키가 모델 ID·프롬프트 버전에 민감하다.
  - GEMINI_API_KEY 없이 gemini 를 선택하면 명확한 에러로 실패한다.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from f3_research import config, llm_features
from f3_research.cache import JsonlCache
from f3_research.schema import LLMFeatures


def _real_items(n: int = 1) -> list[tuple[str, str]]:
    """실제 생성기 + 실제 렌더러로 만든 (shipment_id, 문서 텍스트) 목록.

    tests/test_llm_features.py 의 `_real_items` 와 같은 이유로 손으로 쓴 문서
    문자열을 쓰지 않는다 — 렌더 형식이 조금만 달라도 파서가 조용히 공허해진다.
    """
    import random

    from f3_research import dataset
    from f3_research.render import render_document_set
    from f3_research.synth import generator, pools

    rng = random.Random(7)
    value_pools = pools.load_pools()
    params = generator.GeneratorParams(seed=7, base_count=n)
    entities = generator.build_entity_pools(value_pools, params, rng)
    shipments = generator.generate_base_shipments(value_pools, entities, params, dataset.load_field_accuracy())
    return [(s.shipment_id, render_document_set(s)) for s in shipments]


# ---------------------------------------------------------------------------
# 프롬프트 위생 — 라벨 누수 차단 불변식(HANDOFF.md 불변식 2, 계획서 10단계 Task 2)
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    "injected_defects",
    "covered_by_rule",
    "UCP600_",
    "DOC_MATCH_",
    "LC_COND_",
    "rule_firing",
    "rv_any_critical",
    "ACCEPTED",
    "REJECTED",
)

# 룰 코드(D001, D007B, ...) 모양의 토큰 — 바로 위 리터럴 목록과 달리 접두사
# "D0" 만 검사하면 풀(회사명·참조코드 등)의 우연한 부분 문자열에 걸릴 수 있어
# 정규식으로 룰 코드 형태(D + 숫자 2개 + 선택적 알파벳 1개)만 좁혀서 잡는다.
_RULE_CODE_RE = __import__("re").compile(r"\bD0\d{2}[A-Z]?\b")


def test_prompt_excludes_forbidden_substrings() -> None:
    """빌드된 프롬프트 전체(고정 지시문 + 서류 텍스트)에 금지 문자열이 없다."""
    items = _real_items(3)
    for _shipment_id, document_text in items:
        prompt = llm_features.build_gemini_prompt(document_text)
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in prompt, f"금지된 문자열이 프롬프트에 포함됨: {forbidden}"
        assert not _RULE_CODE_RE.search(prompt), "프롬프트에 룰 코드 형태의 토큰이 포함됨"


def test_prompt_never_asks_for_defect_or_compliance_judgement() -> None:
    """정량 지표 7개 이름만 요구하고 하자/수리·거절 판정 요청 문구는 없다."""
    prompt = llm_features.build_gemini_prompt("(서류 없음)")
    assert "하자" in prompt and "절대" in prompt  # "하자 판정을 하지 말라"는 지시는 있어야 함
    for field_name in LLMFeatures.__dataclass_fields__:
        assert field_name in prompt
    for forbidden_ask in ("수리 여부", "거절 여부", "판정하세요", "심사하세요"):
        assert forbidden_ask not in prompt


# ---------------------------------------------------------------------------
# 파싱/검증 — review.parse_verdict_response 대응(계획서 10단계 Task 3)
# ---------------------------------------------------------------------------


def _valid_payload(**overrides: float) -> str:
    payload = {
        "verifiable_47a_ratio": 0.5,
        "unverifiable_47a_count": 2,
        "goods_semantic_equiv": 0.8,
        "goods_invoice_semantic_equiv": 0.7,
        "party_semantic_equiv_min": 0.6,
        "doc_conflict_count": 1,
        "lc_complexity_score": 0.4,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_gemini_response_accepts_valid_schema() -> None:
    feats = llm_features.parse_gemini_response(_valid_payload())
    assert feats.verifiable_47a_ratio == 0.5
    assert feats.unverifiable_47a_count == 2
    assert feats.doc_conflict_count == 1


def test_parse_gemini_response_clamps_out_of_range_ratios() -> None:
    feats = llm_features.parse_gemini_response(
        _valid_payload(verifiable_47a_ratio=47.0, goods_semantic_equiv=-3.0)
    )
    assert feats.verifiable_47a_ratio == 1.0
    assert feats.goods_semantic_equiv == 0.0


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_parse_gemini_response_rejects_nan_inf(bad_value: float) -> None:
    text = _valid_payload(lc_complexity_score=bad_value)
    with pytest.raises(llm_features.GeminiSchemaViolation):
        llm_features.parse_gemini_response(text)


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        json.dumps({"verifiable_47a_ratio": 0.5}),  # 필드 누락
        json.dumps(
            {
                "verifiable_47a_ratio": "high",  # 숫자가 아님
                "unverifiable_47a_count": 2,
                "goods_semantic_equiv": 0.8,
                "goods_invoice_semantic_equiv": 0.7,
                "party_semantic_equiv_min": 0.6,
                "doc_conflict_count": 1,
                "lc_complexity_score": 0.4,
            }
        ),
    ],
)
def test_parse_gemini_response_rejects_invalid_schema(text: str) -> None:
    with pytest.raises(llm_features.GeminiSchemaViolation):
        llm_features.parse_gemini_response(text)


# ---------------------------------------------------------------------------
# 캐시 키 — 모델 ID·프롬프트 버전 민감성(계획서 10단계 Task 1, review.content_hash 대응)
# ---------------------------------------------------------------------------


def test_gemini_cache_key_changes_with_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _real_items(1)[0][1]
    h1 = llm_features._gemini_content_hash(doc)
    monkeypatch.setattr(config, "GEMINI_FEATURE_MODEL", "gemini-9.9-fake")
    h2 = llm_features._gemini_content_hash(doc)
    assert h1 != h2


def test_gemini_cache_key_changes_with_prompt_version(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = _real_items(1)[0][1]
    h1 = llm_features._gemini_content_hash(doc)
    monkeypatch.setattr(llm_features, "GEMINI_PROMPT_VERSION", "v2-test")
    h2 = llm_features._gemini_content_hash(doc)
    assert h1 != h2


def test_gemini_cache_key_differs_from_offline_for_same_document() -> None:
    """같은 문서라도 백엔드가 다르면 다른 캐시 항목이다(같은 파일을 공유해도 충돌 없음)."""
    doc = _real_items(1)[0][1]
    assert llm_features._gemini_content_hash(doc) != llm_features._content_hash("offline", doc)


# ---------------------------------------------------------------------------
# 전송 계층 — fake client (실제 API 호출 없음)
# ---------------------------------------------------------------------------


class _FakeGeminiResponse:
    def __init__(
        self,
        text: str,
        *,
        model_version: str = "gemini-3.7-flash-001-test",
        input_tokens: int = 628,
        output_tokens: int = 109,
    ) -> None:
        self.text = text
        self.model_version = model_version
        self.usage_metadata = SimpleNamespace(
            prompt_token_count=input_tokens, candidates_token_count=output_tokens
        )


class _FakeModels:
    """`client.models.generate_content()` 를 흉내낸다.

    `responder(document_text, call_index)` 콜백이 응답 또는 예외를 결정한다 —
    스레드풀에서 여러 워커가 동시에 호출할 수 있으므로 호출 카운터를 락으로 보호한다.
    """

    def __init__(self, responder) -> None:
        self._responder = responder
        self._lock = threading.Lock()
        self.call_count = 0
        self.calls: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: dict):
        with self._lock:
            idx = self.call_count
            self.call_count += 1
            self.calls.append(contents)
        return self._responder(contents, idx)


class _FakeClient:
    def __init__(self, responder) -> None:
        self.models = _FakeModels(responder)


def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """백오프·RPM 리미터가 테스트를 느리게 만들지 않도록 상수를 낮춘다."""
    monkeypatch.setattr(config, "GEMINI_BACKOFF_BASE_SECONDS", 0.001)
    monkeypatch.setattr(config, "GEMINI_BACKOFF_MAX_SECONDS", 0.002)
    monkeypatch.setattr(config, "GEMINI_BACKOFF_JITTER_SECONDS", 0.001)
    monkeypatch.setattr(config, "GEMINI_RPM_LIMIT", 6000)


def test_fake_client_valid_json_parses_correctly(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_backoff(monkeypatch)
    items = _real_items(1)
    client = _FakeClient(lambda doc, idx: _FakeGeminiResponse(_valid_payload()))
    cache = JsonlCache(tmp_path / "cache.jsonl")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=client, cache=cache
    )
    assert fallback_count == 0
    feats = by_id[items[0][0]]
    assert feats is not None
    assert feats.verifiable_47a_ratio == 0.5
    assert feats.doc_conflict_count == 1
    assert client.models.call_count == 1


def test_503_then_success_retries(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_backoff(monkeypatch)
    from google.genai import errors

    items = _real_items(1)

    def responder(doc, idx):
        if idx == 0:
            raise errors.ServerError(503, {"message": "UNAVAILABLE", "status": "UNAVAILABLE"}, None)
        return _FakeGeminiResponse(_valid_payload())

    client = _FakeClient(responder)
    cache = JsonlCache(tmp_path / "cache.jsonl")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=client, cache=cache
    )
    assert fallback_count == 0
    assert by_id[items[0][0]] is not None
    assert client.models.call_count == 2  # 1회 실패 + 1회 성공


def test_persistent_failure_falls_back_to_offline_without_raising(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fast_backoff(monkeypatch)
    monkeypatch.setattr(config, "GEMINI_MAX_RETRIES", 2)
    from google.genai import errors

    items = _real_items(1)
    shipment_id, document_text = items[0]

    def responder(doc, idx):
        raise errors.ServerError(503, {"message": "UNAVAILABLE"}, None)

    client = _FakeClient(responder)
    cache = JsonlCache(tmp_path / "cache.jsonl")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=client, cache=cache
    )
    assert fallback_count == 1
    assert client.models.call_count == 3  # max_retries=2 → 총 3회 시도

    offline_by_id, _ = llm_features.compute_features_batch(items, backend="offline")
    assert by_id[shipment_id] == offline_by_id[shipment_id]


def test_non_retryable_error_falls_back_immediately_without_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4xx(429 제외) 는 재시도해도 같은 결과이므로 즉시 폴백한다(재시도 낭비 방지)."""
    _fast_backoff(monkeypatch)
    from google.genai import errors

    items = _real_items(1)

    def responder(doc, idx):
        raise errors.ClientError(403, {"message": "PERMISSION_DENIED"}, None)

    client = _FakeClient(responder)
    cache = JsonlCache(tmp_path / "cache.jsonl")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=client, cache=cache
    )
    assert fallback_count == 1
    assert by_id[items[0][0]] is not None
    assert client.models.call_count == 1  # 재시도하지 않음


def test_schema_violation_response_retries_then_falls_back(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """구조적 출력 계약 위반(NaN 등)도 재시도 대상이다(계획서 10단계 Task 3)."""
    _fast_backoff(monkeypatch)
    monkeypatch.setattr(config, "GEMINI_MAX_RETRIES", 1)
    items = _real_items(1)

    def responder(doc, idx):
        return _FakeGeminiResponse(_valid_payload(lc_complexity_score=float("nan")))

    client = _FakeClient(responder)
    cache = JsonlCache(tmp_path / "cache.jsonl")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=client, cache=cache
    )
    assert fallback_count == 1
    assert client.models.call_count == 2  # max_retries=1 → 총 2회 시도
    assert by_id[items[0][0]] is not None


# ---------------------------------------------------------------------------
# 캐시 — 히트 시 API 호출 없음(계획서 10단계 Task 1)
# ---------------------------------------------------------------------------


def test_gemini_cache_hit_makes_zero_client_calls(tmp_path) -> None:
    items = _real_items(1)
    shipment_id, document_text = items[0]
    cache = JsonlCache(tmp_path / "cache.jsonl")
    h = llm_features._gemini_content_hash(document_text)
    prefilled = LLMFeatures(
        verifiable_47a_ratio=0.5,
        unverifiable_47a_count=1,
        goods_semantic_equiv=0.5,
        goods_invoice_semantic_equiv=0.5,
        party_semantic_equiv_min=0.5,
        doc_conflict_count=0,
        lc_complexity_score=0.5,
    )
    cache.put(llm_features._record_from_features(h, shipment_id, prefilled))

    class _ExplodingClient:
        def __getattr__(self, item):
            raise AssertionError("캐시 히트인데 클라이언트를 건드렸습니다")

    by_id, fallback_count = llm_features.compute_features_batch(
        items, backend="gemini", client=_ExplodingClient(), cache=cache
    )
    assert fallback_count == 0
    assert by_id[shipment_id].verifiable_47a_ratio == 0.5


def test_gemini_cache_round_trip_across_instances(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_backoff(monkeypatch)
    items = _real_items(1)
    shipment_id, _ = items[0]
    client = _FakeClient(lambda doc, idx: _FakeGeminiResponse(_valid_payload()))
    path = tmp_path / "cache.jsonl"

    first_cache = JsonlCache(path)
    first, _ = llm_features.compute_features_batch(items, backend="gemini", client=client, cache=first_cache)
    assert client.models.call_count == 1

    second_cache = JsonlCache(path)  # 새 인스턴스 — 디스크에서 다시 읽는다

    class _ExplodingClient:
        def __getattr__(self, item):
            raise AssertionError("캐시가 영속되지 않았습니다")

    second, _ = llm_features.compute_features_batch(
        items, backend="gemini", client=_ExplodingClient(), cache=second_cache
    )
    assert first[shipment_id] == second[shipment_id]


# ---------------------------------------------------------------------------
# API 키 없는 환경 (계획서 10단계 Task 4)
# ---------------------------------------------------------------------------


def test_gemini_backend_without_api_key_raises_clear_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    items = _real_items(1)
    cache = JsonlCache(tmp_path / "cache.jsonl")  # 캐시가 비어 있어야 실제로 클라이언트를 필요로 함
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm_features.compute_features_batch(items, backend="gemini", cache=cache)


def test_get_gemini_client_raises_without_key_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm_features._get_gemini_client(client=None)


# ---------------------------------------------------------------------------
# 채널 독립 가드 — gemini 백엔드도 예외 없이 적용된다
# ---------------------------------------------------------------------------


def test_channel_independence_rejected_before_any_cache_or_client_use(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "REVIEWER_BACKEND", "claude")

    class _ExplodingClient:
        def __getattr__(self, item):
            raise AssertionError("채널 독립 위반 검사보다 먼저 클라이언트를 건드렸습니다")

    with pytest.raises(RuntimeError, match="채널 독립"):
        llm_features.compute_features_batch(
            [("S1", "dummy")], backend="gemini", client=_ExplodingClient()
        )

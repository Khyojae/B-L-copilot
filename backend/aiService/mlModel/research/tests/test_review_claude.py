"""claude 백엔드(설계서 5.5) 단위 테스트 — mocked client. 실제 API 는 호출하지 않는다.

이 파일이 지키는 핵심 계약(설계서 5.5 "반드시 지킬 것"):
  - 프롬프트에 injected_defects/covered_by_rule/룰 코드/룰 발화 벡터가 없다.
  - structured output 계약(verdict/reasons/confidence) 위반 시 재시도 후 폴백한다.
  - 판정 캐시가 있으면 API 를 호출하지 않는다.
  - ANTHROPIC_API_KEY 없이 claude 백엔드를 쓰면 명확한 에러로 실패한다.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest

from f3_research.synth import review
from f3_research.synth.generator import (
    GeneratorParams,
    build_entity_pools,
    generate_base_shipments,
)
from f3_research.synth.injector import Defect
from f3_research.synth.pools import ValuePools


def _make_shipment(seed: int = 1, shipment_id: str = "S00000-v0"):
    pools = ValuePools(
        company_names=["ACME TRADING CO., LTD.", "GLOBAL IMPORT CO., LTD."],
        ports=["BUSAN, KOREA", "LOS ANGELES, USA"],
        vessels=["OCEAN STAR"],
        goods=["ELECTRONICS PARTS"],
        weights_kg=[500.0],
        measurements_cbm=[10.0],
        amounts_usd=[5000.0],
        reference_codes=[],
        source_file_count=1,
    )
    params = GeneratorParams(seed=seed, base_count=1)
    rng = random.Random(seed)
    entities = build_entity_pools(pools, params, rng)
    shipments = generate_base_shipments(pools, entities, params, field_accuracy={})
    s = shipments[0]
    s.shipment_id = shipment_id
    return s


# ---------------------------------------------------------------------------
# 프롬프트/렌더링 — 라벨 누수 차단 불변식
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    "injected_defects",
    "covered_by_rule",
    "UCP600_",
    "DOC_MATCH_",
    "LC_COND_",
    "rule_firing",
    "rv_any_critical",
)


def test_render_document_set_excludes_injected_defect_data() -> None:
    shipment = _make_shipment()
    document_text = review.render_document_set(shipment)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in document_text, f"금지된 문자열이 프롬프트 서류에 포함됨: {forbidden}"
    # 서류 자체의 내용(품명·항구 등)은 포함되어야 한다.
    assert shipment.goods_description in document_text or shipment.invoice_goods_description in document_text


def test_build_prompt_excludes_injected_defect_data() -> None:
    shipment = _make_shipment()
    document_text = review.render_document_set(shipment)
    prompt = review.build_prompt(document_text)
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in prompt
    assert "ACCEPTED" in prompt and "REJECTED" in prompt


def test_content_hash_deterministic_and_sensitive_to_content() -> None:
    s1 = _make_shipment(seed=1, shipment_id="A")
    s2 = _make_shipment(seed=1, shipment_id="A")
    assert review.content_hash(s1) == review.content_hash(s2)

    s3 = _make_shipment(seed=1, shipment_id="A")
    s3.invoice_amount_usd += 999.0
    assert review.content_hash(s1) != review.content_hash(s3)


# ---------------------------------------------------------------------------
# ReviewCache
# ---------------------------------------------------------------------------


def test_review_cache_round_trip(tmp_path) -> None:
    path = tmp_path / "reviews" / "claude_reviews.jsonl"
    cache = review.ReviewCache(path)
    assert cache.get("abc") is None

    record = {"hash": "abc", "shipment_id": "S1", "verdict": "REJECTED", "reasons": [], "confidence": 0.9}
    cache.put(record)
    assert cache.get("abc") == record

    # 새 인스턴스로 다시 읽어도 유지된다(파일 영속성).
    cache2 = review.ReviewCache(path)
    assert cache2.get("abc") == record


# ---------------------------------------------------------------------------
# 구조적 출력 파싱
# ---------------------------------------------------------------------------


def test_parse_verdict_response_accepts_valid_schema() -> None:
    text = json.dumps(
        {
            "verdict": "REJECTED",
            "reasons": [{"code": "UCP600-14C", "field": "presentation_date", "rationale": "..."}],
            "confidence": 0.87,
        }
    )
    parsed = review.parse_verdict_response(text)
    assert parsed["verdict"] == "REJECTED"


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        json.dumps({"verdict": "MAYBE", "reasons": [], "confidence": 0.5}),
        json.dumps({"verdict": "ACCEPTED", "reasons": "not-a-list", "confidence": 0.5}),
        json.dumps({"verdict": "ACCEPTED", "reasons": [{"code": "x"}], "confidence": 0.5}),
        json.dumps({"verdict": "ACCEPTED", "reasons": []}),  # confidence 누락
    ],
)
def test_parse_verdict_response_rejects_invalid_schema(text: str) -> None:
    with pytest.raises(review.SchemaViolation):
        review.parse_verdict_response(text)


# ---------------------------------------------------------------------------
# API 키 없는 환경에서의 명확한 실패
# ---------------------------------------------------------------------------


def test_claude_backend_without_api_key_raises_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        review._get_client(client=None)


# ---------------------------------------------------------------------------
# Batches API 호출 — mocked client (실제 API 호출 없음)
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, text: str | None, stop_reason: str = "end_turn"):
        self.stop_reason = stop_reason
        self.content = [SimpleNamespace(type="text", text=text)] if text is not None else []


class _FakeResult:
    def __init__(self, custom_id: str, result_type: str, message: _FakeMessage | None = None):
        self.custom_id = custom_id
        self.result = SimpleNamespace(type=result_type, message=message)


class _FakeBatch:
    def __init__(self, batch_id: str):
        self.id = batch_id
        self.processing_status = "ended"


class _FakeBatchesAPI:
    """anthropic client.messages.batches 를 흉내낸다. 호출마다 다른 결과를 낼 수 있다."""

    def __init__(self, results_by_call: list[dict[str, _FakeResult]]):
        self._results_by_call = results_by_call
        self._call_index = 0
        self.created_requests: list[list[str]] = []

    def create(self, requests):
        self.created_requests.append([r["custom_id"] for r in requests])
        return _FakeBatch(f"batch_{self._call_index}")

    def retrieve(self, batch_id):
        return _FakeBatch(batch_id)

    def results(self, batch_id):
        idx = self._call_index
        self._call_index += 1
        return list(self._results_by_call[idx].values())


class _FakeClient:
    def __init__(self, results_by_call: list[dict[str, _FakeResult]]):
        self.messages = SimpleNamespace(batches=_FakeBatchesAPI(results_by_call))


def _success_result(cid: str, verdict: str) -> _FakeResult:
    text = json.dumps({"verdict": verdict, "reasons": [], "confidence": 0.9})
    return _FakeResult(cid, "succeeded", _FakeMessage(text))


def test_call_claude_batch_parses_successful_verdict() -> None:
    client = _FakeClient([{"s1": _success_result("s1", "REJECTED")}])
    outcomes = review._call_claude_batch({"s1": "prompt text"}, client=client)
    assert outcomes["s1"]["parsed"]["verdict"] == "REJECTED"


def test_call_claude_batch_flags_refusal() -> None:
    client = _FakeClient([{"s1": _FakeResult("s1", "succeeded", _FakeMessage("{}", stop_reason="refusal"))}])
    outcomes = review._call_claude_batch({"s1": "prompt"}, client=client)
    assert outcomes["s1"]["error"] == "refusal"


def test_call_claude_batch_flags_schema_violation() -> None:
    bad_text = json.dumps({"verdict": "NOT_A_VERDICT"})
    client = _FakeClient([{"s1": _FakeResult("s1", "succeeded", _FakeMessage(bad_text))}])
    outcomes = review._call_claude_batch({"s1": "prompt"}, client=client)
    assert "schema_violation" in outcomes["s1"]["error"]


def test_judge_batch_claude_uses_cache_and_skips_api(tmp_path) -> None:
    shipment = _make_shipment(shipment_id="cached")
    h = review.content_hash(shipment)
    cache = review.ReviewCache(tmp_path / "reviews.jsonl")
    cache.put({"hash": h, "shipment_id": "cached", "verdict": "ACCEPTED", "reasons": [], "confidence": 0.5})

    class _ExplodingClient:
        def __getattr__(self, item):
            raise AssertionError("캐시가 있으면 API 를 호출하면 안 됩니다")

    defects_by_id = {shipment.shipment_id: []}
    bank_by_id = {shipment.shipment_id: 1.0}
    rng_by_id = {shipment.shipment_id: random.Random(0)}

    y_by_id, fallback_count = review.judge_batch_claude(
        [shipment], defects_by_id, bank_by_id, rng_by_id, client=_ExplodingClient(), cache=cache
    )
    assert y_by_id[shipment.shipment_id] == 0  # ACCEPTED -> 0
    assert fallback_count == 0


def test_judge_batch_claude_falls_back_after_max_retries(tmp_path) -> None:
    shipment = _make_shipment(shipment_id="always_fails")
    cache = review.ReviewCache(tmp_path / "reviews.jsonl")

    # 매 시도마다 스키마 위반으로 실패 — max_retries=2 이므로 총 3번 시도 후 폴백한다.
    failing_result = {shipment.shipment_id: _FakeResult(shipment.shipment_id, "errored")}
    client = _FakeClient([failing_result, failing_result, failing_result])

    defects = [Defect("expiry_exceeded", "tm_days_to_expiry", "CRITICAL", True)]
    defects_by_id = {shipment.shipment_id: defects}
    bank_by_id = {shipment.shipment_id: 1.0}
    rng_by_id = {shipment.shipment_id: random.Random(0)}

    y_by_id, fallback_count = review.judge_batch_claude(
        [shipment], defects_by_id, bank_by_id, rng_by_id, client=client, cache=cache, max_retries=2
    )
    assert fallback_count == 1
    assert y_by_id[shipment.shipment_id] in (0, 1)


def test_judge_batch_claude_recovers_on_retry(tmp_path) -> None:
    shipment = _make_shipment(shipment_id="recovers")
    cache = review.ReviewCache(tmp_path / "reviews.jsonl")

    fail_once = {shipment.shipment_id: _FakeResult(shipment.shipment_id, "errored")}
    succeed = {shipment.shipment_id: _success_result(shipment.shipment_id, "REJECTED")}
    client = _FakeClient([fail_once, succeed])

    defects_by_id = {shipment.shipment_id: []}
    bank_by_id = {shipment.shipment_id: 1.0}
    rng_by_id = {shipment.shipment_id: random.Random(0)}

    y_by_id, fallback_count = review.judge_batch_claude(
        [shipment], defects_by_id, bank_by_id, rng_by_id, client=client, cache=cache, max_retries=2
    )
    assert fallback_count == 0
    assert y_by_id[shipment.shipment_id] == 1  # REJECTED -> 1
    assert cache.get(review.content_hash(shipment)) is not None


# ---------------------------------------------------------------------------
# compute_labels 디스패치
# ---------------------------------------------------------------------------


def test_compute_labels_dispatches_to_constant_table_by_default() -> None:
    shipment = _make_shipment(shipment_id="ct")
    defects: list[Defect] = []
    items = [(shipment, defects, random.Random(0))]
    ys, fallback_count = review.compute_labels(items, backend="constant_table")
    assert fallback_count == 0
    assert ys[0] in (0, 1)


def test_compute_labels_dispatches_to_claude_backend(tmp_path) -> None:
    shipment = _make_shipment(shipment_id="cl")
    cache = review.ReviewCache(tmp_path / "reviews.jsonl")
    client = _FakeClient([{shipment.shipment_id: _success_result(shipment.shipment_id, "ACCEPTED")}])
    items = [(shipment, [], random.Random(0))]
    ys, fallback_count = review.compute_labels(items, backend="claude", client=client, cache=cache)
    assert ys == [0]
    assert fallback_count == 0

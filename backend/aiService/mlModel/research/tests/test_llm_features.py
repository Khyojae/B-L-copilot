"""Group 7(LLM_SEMANTIC) 피처 백엔드 검사 (계획서 8단계, 설계서 5.5).

이 스위트는 **네트워크를 절대 타지 않는다**. `conftest.py` 의 autouse 픽스처가
API 키를 지우고, 여기서 쓰는 백엔드는 `null`/`offline` 뿐이다.
"""

from __future__ import annotations

import math

import pytest

from f3_research import llm_features
from f3_research.cache import JsonlCache
from f3_research.schema import LLMFeatures

def _real_items(n: int = 4) -> list[tuple[str, str]]:
    """실제 생성기 + 실제 렌더러로 만든 (shipment_id, 문서 텍스트) 목록.

    손으로 쓴 문서 문자열을 쓰지 않는다 — 렌더 형식(섹션 헤더·필드 라벨)이
    조금만 달라도 파서가 아무것도 못 뽑아 **테스트가 조용히 공허해진다**
    (초판에서 실제로 그랬다: 전 필드 None 인데 통과할 뻔했다).
    """
    import random

    from f3_research import dataset
    from f3_research.render import render_document_set
    from f3_research.synth import generator, pools

    rng = random.Random(5)
    value_pools = pools.load_pools()
    params = generator.GeneratorParams(seed=5, base_count=n)
    entities = generator.build_entity_pools(value_pools, params, rng)
    shipments = generator.generate_base_shipments(
        value_pools, entities, params, dataset.load_field_accuracy()
    )
    return [(s.shipment_id, render_document_set(s)) for s in shipments]


_ITEMS = _real_items()


def _values(f: LLMFeatures) -> list:
    return [getattr(f, name) for name in LLMFeatures.__dataclass_fields__]


# ── null 백엔드 ────────────────────────────────────────────────────────


def test_null_backend_yields_no_features() -> None:
    """null 백엔드는 피처를 만들지 않는다 — snapshot.llm 이 None 이 되어
    Group 7 전체가 NaN, `llm_available` 만 0.0 이 된다(설계서 4절 Group 7)."""
    by_id, fallback = llm_features.compute_features_batch(_ITEMS, backend="null")
    assert set(by_id) == {sid for sid, _ in _ITEMS}
    assert all(v is None for v in by_id.values())
    assert fallback == 0


def test_offline_backend_actually_extracts_something() -> None:
    """오프라인 백엔드가 문서에서 실제로 값을 뽑는지 확인한다.

    ★ 이 검사가 필요한 이유: 초판 테스트는 손으로 쓴 문서 문자열을 썼는데
    렌더 형식과 달라 파서가 **전 필드 None** 을 냈고, 그래도 다른 검사들은
    전부 통과했다(전부 None 이면 결정론·순서무관도 자명하게 성립한다).
    "무언가를 실제로 뽑았다"를 명시 검사하지 않으면 스위트가 통째로 공허해진다.
    """
    by_id, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    populated = [
        name
        for f in by_id.values()
        if f is not None
        for name, value in ((n, getattr(f, n)) for n in LLMFeatures.__dataclass_fields__)
        if value is not None and not (isinstance(value, float) and math.isnan(value))
    ]
    assert populated, "오프라인 백엔드가 어떤 피처도 뽑지 못했습니다 — 파서와 렌더 형식 불일치"


# ── offline 백엔드: 결정론 ──────────────────────────────────────────────


def test_offline_backend_is_deterministic() -> None:
    """같은 입력은 항상 같은 출력을 낸다(설계서 5.5 재현성)."""
    first, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    second, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    for key in first:
        assert _values(first[key]) == _values(second[key]), f"{key} 결과가 재현되지 않습니다"


def test_offline_backend_is_order_independent() -> None:
    """배치 순서가 결과를 바꾸지 않는다.

    지터가 호출 순서나 공유 RNG 가 아니라 **내용 해시**에서 파생돼야 한다는
    요건(계획서 8단계)의 검사다. 순서 의존이 있으면 행을 어떻게 묶어 생성하느냐에
    따라 데이터셋이 달라져 재현성이 깨진다.
    """
    forward, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    reverse, _ = llm_features.compute_features_batch(list(reversed(_ITEMS)), backend="offline")
    for key in forward:
        assert _values(forward[key]) == _values(reverse[key]), (
            f"{key}: 배치 순서에 따라 결과가 달라집니다 — 지터가 내용 해시가 아닌 "
            "호출 순서에서 파생되고 있습니다"
        )


def test_offline_backend_distinguishes_different_documents() -> None:
    """서로 다른 서류는 서로 다른 피처를 낸다(전 행 상수면 정보량 0)."""
    by_id, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    distinct = {tuple(str(v) for v in _values(f)) for f in by_id.values()}
    assert len(distinct) > 1, "모든 선적이 동일한 피처를 냅니다 — 정보량 0"


def test_offline_47a_features_are_populated_when_lc_present() -> None:
    """47A 검증가능 비율/검증불가 개수는 9단계(§5.3.2 풀 분할)부터 값을 낸다.

    L/C 가 있고 :47A: 조건이 하나 이상이면 언어적 단서 분류기(아래 정확도
    검사 참고)가 반드시 값을 채운다 — 더 이상 NaN 이 아니다.
    """
    by_id, _ = llm_features.compute_features_batch(_ITEMS, backend="offline")
    populated = [
        f
        for f in by_id.values()
        if f is not None and f.verifiable_47a_ratio is not None and not math.isnan(f.verifiable_47a_ratio)
    ]
    assert populated, "L/C 가 있는 선적인데도 llm_47a_verifiable_ratio 가 전부 NaN 입니다"
    for f in populated:
        assert 0.0 <= f.verifiable_47a_ratio <= 1.0
        assert f.unverifiable_47a_count is not None and f.unverifiable_47a_count >= 0


def test_offline_47a_features_are_nan_when_lc_absent() -> None:
    """L/C 자체가 없으면(:47A: 조건도 없으면) 여전히 근거가 없어 NaN 이다."""
    from f3_research.render import render_document_set

    document_text = render_document_set(_no_lc_shipment())
    fields = llm_features._extract_fields(document_text)
    assert fields["lc_present"] is False

    by_id, _ = llm_features.compute_features_batch([("NO-LC", document_text)], backend="offline")
    f = by_id["NO-LC"]
    assert f is not None
    assert f.verifiable_47a_ratio is None
    assert f.unverifiable_47a_count is None


def _no_lc_shipment():
    """L/C 가 없는 선적 1건(실제 생성기로 만들되 lc_present=False 를 강제)."""
    import dataclasses
    import random

    from f3_research import dataset
    from f3_research.synth import generator, pools

    rng = random.Random(11)
    value_pools = pools.load_pools()
    params = generator.GeneratorParams(seed=11, base_count=1)
    entities = generator.build_entity_pools(value_pools, params, rng)
    shipment = generator.generate_base_shipments(
        value_pools, entities, params, dataset.load_field_accuracy()
    )[0]
    return dataclasses.replace(
        shipment,
        lc_present=False,
        lc_47a_text="",
        lc_consignee=None,
        lc_port_of_loading=None,
        lc_goods_description=None,
    )


def test_47a_classifier_uses_text_only_not_pool_membership() -> None:
    """분류기가 풀 소속을 몰라도 문장 텍스트만으로 판정한다는 걸 직접 확인한다.

    같은 문장을 두 번 넣었을 때 같은 결과가 나오는지(순수 함수인지)와, 문장을
    조금 바꾸면(예: BILL OF LADING 언급 제거) 판정이 바뀔 수 있는지를 봐서
    "고정 테이블 조회"가 아니라 "텍스트를 실제로 읽는다"는 걸 보인다.
    """
    verifiable_like = "BILL OF LADING MUST BE MARKED CLEAN ON BOARD"
    unverifiable_like = "BENEFICIARY MUST NOTIFY APPLICANT BY EMAIL"
    assert llm_features._is_unverifiable_47a_condition(verifiable_like) is False
    assert llm_features._is_unverifiable_47a_condition(unverifiable_like) is True
    # 결정론: 같은 입력 → 같은 출력.
    assert llm_features._is_unverifiable_47a_condition(verifiable_like) is False


def test_47a_classifier_accuracy_is_meaningfully_below_oracle() -> None:
    """분류기 정확도가 참 라벨(풀 소속) 대비 0.95 미만이어야 한다(설계서 §5.3.2).

    ★ 이 검사가 지키는 것: 분류가 풀 소속으로 판정되면(오라클) 주입량을
    완벽히 측정하게 되어, 무하자/하자 혼합비 범위를 아무리 겹쳐도
    llm_47a_verifiable_ratio 하나가 완전분리를 만든다. 정확도가 100%에
    근접하도록 "개선"되면 이 테스트가 실패해서 그 회귀를 잡는다. 동시에
    완전히 무작위(0.5)가 아니어야 피처가 무정보가 아니라는 것도 같이 본다.
    """
    from f3_research.synth.generator import LC_47A_UNVERIFIABLE_POOL, LC_47A_VERIFIABLE_POOL

    correct = 0
    total = 0
    for condition in LC_47A_VERIFIABLE_POOL:
        total += 1
        if not llm_features._is_unverifiable_47a_condition(condition):
            correct += 1
    for condition in LC_47A_UNVERIFIABLE_POOL:
        total += 1
        if llm_features._is_unverifiable_47a_condition(condition):
            correct += 1
    accuracy = correct / total
    assert accuracy < 0.95, (
        f"47A 분류기 정확도가 {accuracy:.3f} 로 오라클에 근접합니다 — "
        "언어적 단서가 아니라 풀 소속을 보고 있지는 않은지 확인하세요(설계서 §5.3.2)."
    )
    assert accuracy > 0.5, (
        f"47A 분류기 정확도가 {accuracy:.3f} 로 무작위 수준입니다 — "
        "피처가 무정보입니다(마커 목록을 다시 확인하세요)."
    )


# ── 캐시 ───────────────────────────────────────────────────────────────


def test_cache_round_trip(tmp_path) -> None:
    """캐시에 쓰고 다시 읽으면 같은 값이 나온다."""
    cache = JsonlCache(tmp_path / "llm.jsonl")
    first, _ = llm_features.compute_features_batch(_ITEMS, backend="offline", cache=cache)
    reloaded = JsonlCache(tmp_path / "llm.jsonl")
    second, _ = llm_features.compute_features_batch(_ITEMS, backend="offline", cache=reloaded)
    for key in first:
        assert _values(first[key]) == _values(second[key])


# ── 채널 독립 상호배타 (불변식 2) ────────────────────────────────────────


def test_channel_independence_guard_rejects_llm_on_both_channels() -> None:
    """LLM 이 피처와 라벨을 동시에 만드는 조합은 거부된다(HANDOFF 불변식 2).

    두 채널이 같은 모델 계열을 쓰면 상위 잠재변수(토크나이저·주목 편향·실패
    모드)를 공유해 **통계적으로 탐지 불가능한 누수**가 된다. 이 저장소의 어떤
    검사도 그걸 못 잡으므로, 조합 자체를 거부하는 것이 유일한 방어선이다.
    """
    with pytest.raises(Exception) as exc:
        llm_features.check_channel_independence(
            llm_feature_backend="gemini", reviewer_backend="claude"
        )
    assert "gemini" in str(exc.value) or "채널" in str(exc.value)


@pytest.mark.parametrize(
    ("feature_backend", "reviewer_backend"),
    [
        ("offline", "constant_table"),
        ("null", "constant_table"),
        ("gemini", "constant_table"),  # 피처만 LLM — 허용
        ("offline", "claude"),  # 라벨만 LLM — 허용
    ],
)
def test_channel_independence_guard_allows_safe_combinations(
    feature_backend: str, reviewer_backend: str
) -> None:
    """한쪽만 LLM 인 조합은 허용된다 — 막으려는 건 '양쪽 다 LLM' 뿐이다."""
    llm_features.check_channel_independence(
        llm_feature_backend=feature_backend, reviewer_backend=reviewer_backend
    )


# ── gemini 백엔드는 tests/test_llm_features_gemini.py 에서 검사한다 ─────
# (계획서 10단계 — 이 파일은 null/offline 만 다루고, mocked Gemini client 를 쓰는
# 검사는 별도 파일로 분리한다. API 키 없이 gemini 를 선택했을 때의 에러 메시지
# 검사도 그쪽에 있다.)

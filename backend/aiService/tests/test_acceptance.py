"""수용 기준 실측 테스트 (19번).

여기서 검사하는 것은 **측정 도구가 정직한가**이지 성능 자체가 아니다.
성능 수치는 환경에 따라 달라지므로 임계값을 테스트에 박으면 다른 기계에서
깨진다. 대신 도구가 잴 수 없는 것을 잰 척하지 않는지, 판정을 최댓값으로
하는지를 고정한다.
"""

from __future__ import annotations

import pytest

from acceptance import (
    FAILED,
    PASSED,
    UNMEASURED,
    Result,
    Timing,
    _fmt_ms,
    _seconds_result,
    measure,
    measure_f1,
    measure_f3_f4,
    render,
)


class TestTiming:
    def test_냉시작은_표본에_들어가지_않는다(self):
        calls = []
        timing = measure(lambda i: calls.append(i), count=5)

        # 5회 돌았지만 표본은 4개다. 첫 회는 따로 잡힌다.
        assert len(calls) == 5
        assert len(timing.warm_ms) == 4
        assert timing.cold_ms > 0

    def test_한_번만_돌면_표본이_없다(self):
        timing = measure(lambda i: None, count=1)

        assert timing.warm_ms == []
        # 0 으로 나누지 않는다.
        assert timing.p50_ms == 0.0
        assert timing.max_ms == 0.0

    def test_p95_는_표본이_적어도_범위를_넘지_않는다(self):
        timing = Timing(cold_ms=1.0, warm_ms=[1.0, 2.0])

        assert timing.p95_ms == 2.0


class TestVerdictOfTiming:
    """판정은 평균이 아니라 최댓값으로 한다."""

    def test_최댓값이_넘으면_평균이_통과여도_미달이다(self):
        # 평균 2.2초, 최대 12초. 명세는 "1건 10초"이므로 미달이어야 한다.
        timing = Timing(cold_ms=1.0, warm_ms=[100.0, 100.0, 100.0, 12_000.0])
        result = _seconds_result("F3", "검증", "v2 5.3", 10.0, timing)

        assert result.status == FAILED

    def test_전건이_기준_안이면_통과다(self):
        timing = Timing(cold_ms=1.0, warm_ms=[100.0, 200.0])

        assert _seconds_result("F3", "검증", "v2 5.3", 10.0, timing).status == PASSED


class TestFormat:
    """`0.000초` 는 빠른 것과 측정 실패를 구분하지 못한다."""

    @pytest.mark.parametrize(
        "value_ms,expected",
        [(2500.0, "2.50초"), (7.7, "7.7ms"), (0.4, "400µs")],
    )
    def test_단위를_읽는_사람_기준으로_고른다(self, value_ms, expected):
        assert _fmt_ms(value_ms) == expected


class TestMeasurement:
    def test_F3_F4_기준이_모두_보고된다(self):
        results = measure_f3_f4(count=5, seed=42, use_llm=False)
        names = {r.name for r in results}

        assert "선적 1건 검증" in names
        assert "리포트 생성" in names
        assert "리포트 + PDF" in names
        assert "리포트 수치와 판정 데이터 일치율" in names

    def test_리포트_시간은_검증을_포함한다(self):
        # 이미 계산한 verdict 를 재사용하면 0 이 나오는데, 그 숫자는 통과
        # 판정을 주면서 아무것도 말하지 않는다. `/report` 가 실제로 하는
        # 일(verify → build)을 재야 한다.
        results = {r.name: r for r in measure_f3_f4(count=6, seed=42, use_llm=False)}

        assert results["리포트 생성"].timing.max_ms > 0

    def test_LLM_경로_여부가_결과에_남는다(self):
        results = {r.name: r for r in measure_f3_f4(count=3, seed=42, use_llm=False)}

        assert "LLM 미포함" in results["리포트 생성"].note

    def test_수치_일치율은_100퍼센트다(self):
        # 리포트가 판정 데이터를 다시 세는 곳이 생기면 여기서 깨진다.
        results = {r.name: r for r in measure_f3_f4(count=10, seed=42, use_llm=False)}

        assert results["리포트 수치와 판정 데이터 일치율"].status == PASSED


class TestUnmeasurable:
    """잴 수 없는 것을 결과에서 빼지 않는다."""

    def test_실물이_필요한_기준은_미측정으로_남는다(self):
        results = {r.name: r for r in measure_f1(pages=2)}

        for name in ("추출 정확도 (스캔)", "근거 좌표 보유율", "오추출 라우팅 재현율"):
            assert results[name].status == UNMEASURED
            # 왜 못 쟀는지가 결과의 일부다.
            assert results[name].note

    def test_교정_서식_정확도는_수용_기준의_답이_아니다(self):
        # REGIONS 가 교정된 레이아웃에서 잰 값이라 상한이다. 통과로 세면
        # 실물에서 무너질 값을 달성으로 보고하게 된다.
        result = {r.name: r for r in measure_f1(pages=2)}["추출 정확도 (텍스트 PDF)"]

        assert result.status == UNMEASURED
        assert "상한" in result.note

    def test_미측정은_통과로_집계되지_않는다(self):
        results = [
            Result("F1", "잰 것", "v2 5.1", "100%", PASSED),
            Result("F1", "못 잰 것", "v2 5.1", "100%", UNMEASURED),
        ]
        report = render(results)

        assert "통과 1 · 미달 0 · 미측정 1" in report

    def test_미달_항목은_따로_모아_보여준다(self):
        results = [Result("F3", "검증", "v2 5.3", "10초 이하", FAILED, "최대 12초")]
        report = render(results)

        assert "미달 항목" in report
        assert "임의 완화 대상이 아니다" in report

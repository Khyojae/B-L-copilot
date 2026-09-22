"""F7 판정 설명 — LLM 경로 인용 무결성 실측.

`tests/test_explain.py` 의 30건 회귀는 **일부러 템플릿 설명기를 고정**한다 —
키가 없는 CI 에서도 항상 돌아야 하고, 템플릿은 구조상 100% 통과라 그 사실을
assert 하는 테스트다. 그래서 그 테스트로는 "LLM 이 인용을 지어내는 비율"을
알 수 없다. 이 스크립트가 같은 30건을 **환경 설정의 설명기**(LLM_PROVIDER)로
돌려 그 숫자를 잰다.

실행:
    python -m explain_eval
    python -m explain_eval --count 30 --seed 11 --json ../docs/ai-service/explain_eval_2026-09-22.json

## 세 갈래로 센다

설명 1건은 반드시 다음 중 하나로 끝난다(report/explain.py LLMExplainer):
  · llm_first   — LLM 1차 생성이 인용 무결성 검사를 통과
  · llm_retry   — 1차 실패 → 재생성 1회로 통과
  · template    — 2회 모두 실패했거나(인용 불일치) 호출 자체가 실패해 템플릿 폴백
보고서가 말하는 "인용 무결성 통과율"은 (llm_first + llm_retry) / 전체 다.
폴백은 실패가 아니라 설계된 안전망이지만, 폴백 비율이 높으면 LLM 경로가
사실상 안 쓰이는 것이므로 따로 싣는다.

## 호출 횟수는 완성 설명기 밖에서 센다

LLMExplainer 는 시도 횟수를 결과에 남기지 않는다(화면이 알 필요가 없는
값). 여기서는 completion 함수를 감싸 설명 1건당 호출 수를 세어 갈래를
정한다 — 설명기 코드를 측정 때문에 바꾸지 않는다.

## 한도(429)는 측정 대상이 아니라 측정 조건이다

Gemini 무료 등급은 분당 5회다. 47건을 그냥 쏘면 5건 뒤부터 전부 429 로
폴백돼 "LLM 통과율 8%" 같은 숫자가 나오는데, 그건 인용 무결성이 아니라
요금제를 잰 것이다. 그래서 같은 감싸기에서 호출 간격을 `--rpm` 으로 맞추고
429 는 서버가 알려준 대기 뒤 재시도한다 — 이 재시도는 설명기의 "재생성
2회"와 별개라 attempts 에 세지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from time import perf_counter, sleep
from typing import Callable, Dict, List, Optional

from dotenv import load_dotenv

from mlModel.synth import SyntheticGenerator
from report import apply_narrative, build_report, check_narrative
from report.explain import LLMExplainer, TemplateExplainer
from report.narrative import TemplateNarrator
from ruleEngine import RuleEngine

# api/main.py 와 같은 규칙: 이미 설정된 환경변수는 덮지 않는다.
load_dotenv()


@dataclass
class ExplanationOutcome:
    rule_id: str
    outcome: str  # llm_first | llm_retry | template
    attempts: int
    integrity_ok: bool
    seconds: float
    # 폴백일 때만: 마지막 검사 실패 사유 또는 예외 메시지
    failure: Optional[str] = None


@dataclass
class EvalResult:
    provider: str
    model: Optional[str]
    samples: int
    seed: int
    verdicts_with_violations: int
    explanations: int
    llm_first: int
    llm_retry: int
    template: int
    integrity_pass_rate: float
    llm_pass_rate: float
    p50_seconds: float
    max_seconds: float
    measured_at: str
    rpm: float = 0.0
    rate_limit_waits: int = 0
    outcomes: List[ExplanationOutcome] = field(default_factory=list)
    failures: Dict[str, int] = field(default_factory=dict)


_RETRY_HINT = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)
_MAX_429_RETRIES = 3


class _CountingCompletion:
    """completion 을 감싸 호출 수·마지막 예외를 기록하고, 분당 호출 수를 맞춘다."""

    def __init__(self, inner: Callable[[str, str], str], rpm: float) -> None:
        self._inner = inner
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._last_call_at = 0.0
        self.calls = 0
        self.rate_limit_waits = 0
        self.last_error: Optional[str] = None

    def reset(self) -> None:
        self.calls = 0
        self.last_error = None

    def _throttle(self) -> None:
        wait = self._min_interval - (perf_counter() - self._last_call_at)
        if wait > 0:
            sleep(wait)

    def __call__(self, system: str, user: str) -> str:
        self.calls += 1
        for attempt in range(_MAX_429_RETRIES + 1):
            self._throttle()
            self._last_call_at = perf_counter()
            try:
                return self._inner(system, user)
            except Exception as exc:  # noqa: BLE001 - 사유를 남기고 그대로 올린다
                message = str(exc)
                if "HTTP 429" in message and attempt < _MAX_429_RETRIES:
                    hint = _RETRY_HINT.search(message)
                    wait = float(hint.group(1)) + 1.0 if hint else self._min_interval * 2
                    self.rate_limit_waits += 1
                    print(f"[explain_eval] 429 — {wait:.0f}s 대기 후 재시도 ({attempt + 1}/{_MAX_429_RETRIES})")
                    sleep(wait)
                    continue
                self.last_error = f"{type(exc).__name__}: {message.splitlines()[0][:120]}"
                raise
        raise AssertionError("unreachable")


def _build_llm(rpm: float) -> tuple[Optional[_CountingCompletion], str, Optional[str]]:
    """환경에서 LLM completion 을 만든다. 없으면 (None, provider, None)."""
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower() or "template"
    if provider == "template":
        return None, provider, None
    from report.llm_providers import build_completion

    complete = build_completion(provider)
    if complete is None:
        return None, provider, None
    model = getattr(complete, "model", None) or os.getenv("LLM_MODEL")
    return _CountingCompletion(complete, rpm), provider, model


def run(count: int, seed: int, rpm: float) -> EvalResult:
    counting, provider, model = _build_llm(rpm)
    if counting is None:
        raise SystemExit(
            f"LLM 경로가 꺼져 있다 (LLM_PROVIDER={provider!r}, 키 없음 또는 'changeme'). "
            "이 스크립트는 LLM 통과율을 재는 것이라 템플릿 경로로는 의미가 없다 — "
            "템플릿 100% 는 tests/test_explain.py 가 이미 assert 한다."
        )

    engine = RuleEngine()
    samples = SyntheticGenerator(seed=seed).generate(count, defect_ratio=1.0)
    explainer = LLMExplainer(counting, fallback=TemplateExplainer())

    outcomes: List[ExplanationOutcome] = []
    verdicts_with_violations = 0

    for sample in samples:
        verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
        if not verdict.violations:
            continue
        verdicts_with_violations += 1

        report = build_report(verdict, sample.bl.to_dict(), sample.lc, as_of=sample.as_of)
        # 서사는 템플릿으로 고정한다 — 여기서 재는 것은 설명(F7)이지 요약(F4)이
        # 아니고, LLM 서사까지 켜면 호출 수가 두 배가 된다.
        report = apply_narrative(report, TemplateNarrator())

        # 설명 1건씩 돌려야 호출 수를 그 설명에 귀속시킬 수 있다.
        for risk in report.risks:
            counting.reset()
            started = perf_counter()
            explanation = explainer.explain(risk, report)
            seconds = perf_counter() - started

            integrity = check_narrative(report, explanation.body_ko, explanation.body_en)
            if explanation.origin == "llm":
                outcome = "llm_first" if counting.calls == 1 else "llm_retry"
                failure = None
            else:
                outcome = "template"
                failure = counting.last_error or (
                    "인용 무결성 2회 실패" if counting.calls >= 2 else "응답 형식 오류(2줄 미만)"
                )
            outcomes.append(
                ExplanationOutcome(
                    rule_id=risk.rule_id,
                    outcome=outcome,
                    attempts=counting.calls,
                    integrity_ok=integrity.ok,
                    seconds=round(seconds, 3),
                    failure=failure,
                )
            )
            print(
                f"[explain_eval] {risk.rule_id:<8} {outcome:<9} "
                f"attempts={counting.calls} {seconds:5.2f}s"
                + (f"  ← {failure}" if failure else "")
            )

    total = len(outcomes)
    llm_first = sum(o.outcome == "llm_first" for o in outcomes)
    llm_retry = sum(o.outcome == "llm_retry" for o in outcomes)
    template = sum(o.outcome == "template" for o in outcomes)
    integrity_pass = sum(o.integrity_ok for o in outcomes)
    durations = sorted(o.seconds for o in outcomes) or [0.0]

    failures: Dict[str, int] = {}
    for o in outcomes:
        if o.failure:
            failures[o.failure] = failures.get(o.failure, 0) + 1

    return EvalResult(
        provider=provider,
        model=model,
        samples=count,
        seed=seed,
        verdicts_with_violations=verdicts_with_violations,
        explanations=total,
        llm_first=llm_first,
        llm_retry=llm_retry,
        template=template,
        integrity_pass_rate=integrity_pass / total if total else 0.0,
        llm_pass_rate=(llm_first + llm_retry) / total if total else 0.0,
        p50_seconds=durations[len(durations) // 2],
        max_seconds=durations[-1],
        measured_at=datetime.now().isoformat(timespec="seconds"),
        rpm=rpm,
        rate_limit_waits=counting.rate_limit_waits,
        outcomes=outcomes,
        failures=failures,
    )


def _print_summary(result: EvalResult) -> None:
    print()
    print(f"F7 판정 설명 — LLM 경로 인용 무결성 실측 ({result.measured_at})")
    print(f"  provider={result.provider} model={result.model} rpm={result.rpm:g} (429 대기 {result.rate_limit_waits}회)")
    print(f"  합성 판정 {result.samples}건(seed={result.seed}) 중 위반 있음 {result.verdicts_with_violations}건 → 설명 {result.explanations}건")
    print()
    print(f"  LLM 1차 통과      {result.llm_first:4d}")
    print(f"  LLM 재생성 후 통과 {result.llm_retry:4d}")
    print(f"  템플릿 폴백        {result.template:4d}")
    print()
    print(f"  인용 무결성 통과율(최종 설명 기준) {result.integrity_pass_rate:.1%}")
    print(f"  LLM 통과율(폴백 제외)             {result.llm_pass_rate:.1%}")
    print(f"  설명 1건 소요  p50 {result.p50_seconds:.2f}s · max {result.max_seconds:.2f}s")
    if result.failures:
        print()
        print("  폴백 사유:")
        for reason, n in sorted(result.failures.items(), key=lambda kv: -kv[1]):
            print(f"    {n:3d}× {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--count", type=int, default=30, help="합성 판정 수 (기본 30)")
    parser.add_argument("--seed", type=int, default=11, help="test_explain 회귀와 같은 11 이 기본")
    parser.add_argument("--json", type=str, default=None, help="결과를 이 파일에 JSON 으로 저장")
    parser.add_argument(
        "--rpm", type=float, default=5.0,
        help="분당 최대 호출 수. Gemini 무료 등급이 5 (기본). 유료면 올려도 된다",
    )
    args = parser.parse_args()

    result = run(args.count, args.seed, args.rpm)
    _print_summary(result)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(asdict(result), fh, ensure_ascii=False, indent=2)
        print(f"\n  → {args.json}")


if __name__ == "__main__":
    main()

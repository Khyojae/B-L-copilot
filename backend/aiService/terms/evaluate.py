"""
F2 표준 용어 교정 정밀도 평가.

기획안 5.2 완료 기준: "교정 제안 정밀도 0.90 이상. 오제안은 실무 신뢰를 직접
훼손하므로 재현율보다 정밀도를 우선 최적화한다"(`docs/ai-service/f2-standard-terms.md`
§정밀도를 재현율보다 우선한다). 측정 수단이 없으면 이 목표의 달성 여부를 말할 수
없으므로 `mlModel/evaluate.py`(F3 하자 검출 평가)와 같은 규율로 이 파일을 만든다.

## `requires_choice` 는 제안이 아니다

`acceptance.py`·`test_acceptance.py` 가 "여기서 검사하는 것은 측정 도구가 정직한가"를
규약으로 두는 것과 같은 이유로, 이 평가기는 스스로 정밀도를 부풀릴 수 있는 구멍부터
막는다. `requires_choice=True` 는 판정한 것이 아니라 사용자에게 넘긴 것이라 정밀도
분자·분모 어디에도 넣지 않는다 — 이 구분이 없으면 애매한 입력을 전부
`requires_choice` 로 미는 것만으로 정밀도가 1.0 이 된다(`f2-standard-terms.md` §정밀도,
`HANDOFF.md` §9). 그래서 케이스마다 결과를 세 값 중 하나로 접는다.

    "value:<X>"  — 확정 제안(비-choice)이 X 로 나왔다
    "none"        — 어떤 확정 제안도 requires_choice 도 없었다
    "choice"      — requires_choice=True 로 사용자에게 넘겼다

**정밀도**는 "확정 제안을 냈을 때 그중 몇 건이 맞았는가"이므로 분모가
`value:*` 케이스 전체(코퍼스의 `expect_none`·`expect_choice` 케이스에서 잘못
확정 제안이 나온 경우까지 포함)이고, **재현율**은 "정답이 있는 케이스 중 몇 건을
맞혔는가"이므로 분모가 코퍼스의 `expect` 케이스 전체다. 이 두 분모가 다르다는
것 자체가 핵심이다 — 같은 분모를 쓰면 `expect_none`/`expect_choice` 케이스가
정밀도 계산에 전혀 기여하지 못해 오탐이 조용히 묻힌다.

**`choice_rate`(클래스별·전체)를 재현율 옆에 항상 함께 찍는다** — 재현율이
낮아도 그만큼 `choice` 로 미뤘다면 사용자 관점에서는 "안내는 받았다"이지만,
그 사실이 재현율 숫자에는 보이지 않는다. 두 숫자를 나란히 놓아야 "판정을
포기하고 선택으로 미룬 비율"이 숨지 않는다(`f2-standard-terms.md` §정밀도
"재현율과 requires_choice 비율을 별도 열로 함께 찍는다").

## 코퍼스 스키마

`terms/eval/corpus.yaml`(210건, `f2-corpus-1`). 케이스마다 `expect`/`expect_none`/
`expect_choice` 중 **정확히 하나**를 쓴다. `lc`(구조화된 L/C 조건, `LCTerms.from_dict`
로 변환)와 `lc_raw_tags`(MT700 태그 dict, `Normalizer.normalize` 가 직접 파싱)는
서로 다른 두 경로를 겨냥하므로 **둘 다 그대로 넘긴다** — 오케스트레이터가 하네스를
짜다 `lc_raw_tags` 를 빠뜨려 멀쩡한 케이스(LC008)를 구현 결함으로 오인할 뻔한 사고가
있었다(작업 지시 참고). 이 파일은 그 실수를 반복하지 않는다.

## LLM 은 기본 꺼짐

`--llm` 없이 돌리면 판정이 전부 결정론이라 어느 기계에서도 같은 정밀도가 나온다
(`tests/test_terms_evaluate.py` 의 임계값 테스트가 이 성질에 기댄다). `--llm` 을
주면 `default_selector()` 를 실어 ⑤단계까지 태우되, `TERMS_LLM_SELECT`/
`GEMINI_API_KEY` 가 없으면 `default_selector()` 자체가 `None` 을 돌려주므로
자동으로 "설정 없음 → 결정론 경로만" 으로 떨어진다(`llm_select.default_selector`
docstring과 같은 규약).

실행:
    python -m terms.evaluate                    # LLM 끔 (기본)
    python -m terms.evaluate --llm               # ⑤단계 포함(설정돼 있으면)
    python -m terms.evaluate --json out.json
    python -m terms.evaluate --corpus <path>     # 다른 코퍼스
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .cascade import DocumentInput, Normalizer
from .glossary import GlossaryStack, load_glossary
from .llm_select import default_selector
from .similarity import NGramRanker
from .types import NormalizeResult

# 기획안 5.2 완료 기준.
TARGET_PRECISION = 0.90

DEFAULT_CORPUS_PATH = Path(__file__).with_name("eval") / "corpus.yaml"

_OUTCOME_NONE = "none"
_OUTCOME_CHOICE = "choice"
_VALUE_PREFIX = "value:"


# ════════════════════════════════════════════════════════════════
# 케이스 1건의 결과
# ════════════════════════════════════════════════════════════════


@dataclass
class CaseEval:
    """코퍼스 케이스 1건을 실제로 돌린 결과.

    `expected`/`actual` 은 모듈 docstring의 세 값(`value:X`/`none`/`choice`)
    중 하나다. 같은 형태이므로 비교(`ok`)가 문자열 등가 하나로 끝난다 —
    "값은 맞는데 choice 로 나왔다" 같은 애매한 절반 성공을 만들지 않는다.
    """

    case_id: str
    doc: str
    field: str
    term_class: str
    value: str
    expected: str
    actual: str
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


# ════════════════════════════════════════════════════════════════
# 집계
# ════════════════════════════════════════════════════════════════


@dataclass
class Metrics:
    """한 그룹(전체 또는 클래스 1개)의 정밀도·재현율·choice 비율.

    분모가 서로 다른 이유는 모듈 docstring 참고. `case_total` 은 accuracy 류
    지표가 아니라 `choice_rate` 의 분모로만 쓴다 — "이 그룹에서 얼마나
    자주 판정을 포기했는가"는 케이스 전체를 모수로 삼아야 뜻이 선다.
    """

    case_total: int = 0
    confirmed_total: int = 0   # actual 이 "value:*" 인 케이스 수 (정밀도 분모)
    confirmed_correct: int = 0  # 그중 expected 와 정확히 일치한 수 (정밀도 분자)
    expect_total: int = 0      # expected 가 "value:*" 인 케이스 수 (재현율 분모)
    choice_expected: int = 0   # expected == "choice" 인 케이스 수
    choice_hit: int = 0        # 그중 actual == "choice" 로 정확히 맞힌 수
    choice_actual: int = 0     # actual == "choice" 인 케이스 수 (choice_rate 분자)

    @property
    def precision(self) -> float:
        return self.confirmed_correct / self.confirmed_total if self.confirmed_total else 0.0

    @property
    def recall(self) -> float:
        return self.confirmed_correct / self.expect_total if self.expect_total else 0.0

    @property
    def choice_rate(self) -> float:
        """이 그룹 전체 케이스 중 `requires_choice` 로 넘어간 비율.

        기대값과 무관하게 "실제로 얼마나 선택으로 미뤘는가"를 잰다 —
        재현율 옆에 나란히 찍어야 "정밀도는 높은데 사실 절반이 choice 였다"
        가 감춰지지 않는다.
        """
        return self.choice_actual / self.case_total if self.case_total else 0.0

    @property
    def choice_precision(self) -> float:
        """`expect_choice` 케이스 중 실제로 choice 로 정확히 넘어간 비율."""
        return self.choice_hit / self.choice_expected if self.choice_expected else 0.0

    def to_dict(self) -> dict:
        return {
            "case_total": self.case_total,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "choice_rate": round(self.choice_rate, 4),
            "choice_precision": round(self.choice_precision, 4),
            "confirmed_total": self.confirmed_total,
            "confirmed_correct": self.confirmed_correct,
            "expect_total": self.expect_total,
            "choice_expected": self.choice_expected,
            "choice_hit": self.choice_hit,
            "choice_actual": self.choice_actual,
        }


def _aggregate(cases: List[CaseEval]) -> Metrics:
    m = Metrics(case_total=len(cases))
    for c in cases:
        if c.actual.startswith(_VALUE_PREFIX):
            m.confirmed_total += 1
            if c.ok:
                m.confirmed_correct += 1
        if c.expected.startswith(_VALUE_PREFIX):
            m.expect_total += 1
        if c.expected == _OUTCOME_CHOICE:
            m.choice_expected += 1
            if c.actual == _OUTCOME_CHOICE:
                m.choice_hit += 1
        if c.actual == _OUTCOME_CHOICE:
            m.choice_actual += 1
    return m


# ════════════════════════════════════════════════════════════════
# 보고서
# ════════════════════════════════════════════════════════════════


@dataclass
class EvalReport:
    corpus_version: str
    corpus_path: str
    case_count: int
    llm: bool
    overall: Metrics
    by_class: Dict[str, Metrics] = field(default_factory=dict)
    mismatches: List[CaseEval] = field(default_factory=list)
    target_precision: float = TARGET_PRECISION

    # `m.precision` 처럼 최상위에서 바로 읽을 수 있게 위임한다
    # (`tests/test_terms_evaluate.py` 의 임계값 테스트가 이 형태를 요구한다).
    @property
    def precision(self) -> float:
        return self.overall.precision

    @property
    def recall(self) -> float:
        return self.overall.recall

    @property
    def choice_rate(self) -> float:
        return self.overall.choice_rate

    @property
    def meets_target(self) -> bool:
        return self.precision >= self.target_precision

    def to_dict(self) -> dict:
        return {
            "corpus_version": self.corpus_version,
            "corpus_path": self.corpus_path,
            "case_count": self.case_count,
            "llm": self.llm,
            "target_precision": self.target_precision,
            "meets_target": self.meets_target,
            "overall": self.overall.to_dict(),
            "by_class": {k: v.to_dict() for k, v in sorted(self.by_class.items())},
            "mismatches": [
                {
                    "id": c.case_id,
                    "doc": c.doc,
                    "field": c.field,
                    "class": c.term_class,
                    "value": c.value,
                    "expected": c.expected,
                    "actual": c.actual,
                }
                for c in self.mismatches
            ],
        }

    def to_text(self) -> str:
        lines = [
            "=" * 70,
            "  F2 표준 용어 교정 정밀도 평가",
            f"  목표: 정밀도 >= {self.target_precision} (기획안 5.2) · "
            "requires_choice 는 제안으로 세지 않는다",
            "=" * 70,
            "",
            f"코퍼스: {self.corpus_version} ({self.corpus_path}) · "
            f"{self.case_count}건 · ⑤LLM: {'켬' if self.llm else '끔(기본)'}",
            "",
            "전체",
            f"  정밀도 {self.overall.precision:.4f}  재현율 {self.overall.recall:.4f}  "
            f"choice비율 {self.overall.choice_rate:.4f}",
            f"  확정 제안 {self.overall.confirmed_total}건 중 "
            f"{self.overall.confirmed_correct}건 정답"
            f" · 정답 필요 {self.overall.expect_total}건 중 "
            f"{self.overall.confirmed_correct}건 재현"
            f" · choice {self.overall.choice_actual}/{self.overall.case_total}"
            f"(정답 필요한 choice 중 적중 {self.overall.choice_hit}/{self.overall.choice_expected})",
            "",
            "클래스별",
            f"  {'클래스':<16} {'건수':>5} {'정밀도':>8} {'재현율':>8} "
            f"{'choice비율':>10} {'확정/정답':>10} {'필요/재현':>10}",
            "  " + "-" * 68,
        ]
        for cls, m in sorted(self.by_class.items()):
            lines.append(
                f"  {cls:<16} {m.case_total:>5} {m.precision:>8.4f} {m.recall:>8.4f} "
                f"{m.choice_rate:>10.4f} "
                f"{f'{m.confirmed_correct}/{m.confirmed_total}':>10} "
                f"{f'{m.confirmed_correct}/{m.expect_total}':>10}"
            )
        lines.append("")

        if self.mismatches:
            lines.append(f"불일치 ({len(self.mismatches)}건) — id · 필드 · 값 · 기대 · 실제")
            for c in self.mismatches:
                lines.append(
                    f"  {c.case_id:<8} {c.doc}/{c.field} ({c.term_class})  "
                    f"값={c.value!r}  기대={c.expected}  실제={c.actual}"
                )
            lines.append("")
        else:
            lines.append("불일치 없음")
            lines.append("")

        mark = "PASS" if self.meets_target else "FAIL"
        lines.append(
            f"[{mark}] 정밀도 목표({self.target_precision}) — 실측 {self.precision:.4f}"
        )
        lines.append("=" * 70)
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# 코퍼스 → 케이스 실행
# ════════════════════════════════════════════════════════════════


def _read_yaml(path: Path) -> dict:
    """`glossary._read_yaml` 과 같은 지연 임포트 + 친절한 오류.

    이 파일도 `terms` 패키지 소속이라 `import terms` 만으로 PyYAML 을
    끌어오면 안 된다는 불변식(`terms/__init__.py` 모듈 docstring)을 그대로
    진다 — 임포트를 함수 안으로 미룬다.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 의존성 누락은 환경 문제
        raise ImportError("PyYAML 이 필요합니다: pip install PyYAML") from exc

    if not path.is_file():
        raise FileNotFoundError(f"코퍼스 파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"코퍼스 파일 형식이 잘못되었습니다(딕셔너리가 아님): {path}")
    return data


def _document_input(case: dict) -> DocumentInput:
    """코퍼스 케이스 1건 → `Normalizer.normalize` 입력.

    케이스마다 필드를 **하나만** 싣는다 — 코퍼스가 "이 필드에 이 값이
    들어왔을 때"만 검증하도록 설계돼 있고(스키마 주석), 다른 필드를
    지어내 넣으면 동음이의 판별의 인접 필드 신호가 오염돼 케이스가
    의도하지 않은 결과를 낼 수 있다.
    """
    return DocumentInput(doc=case["doc"], fields={case["field"]: case["value"]})


def _lc_args(case: dict):
    """케이스의 `lc`/`lc_raw_tags` 를 `Normalizer.normalize` 인자로 바꾼다.

    **둘 다 넘긴다.** `lc` 는 `LCTerms.from_dict` 로 구조화된 L/C 조건
    (44E/44F 등 매핑된 필드)을 겨냥하고, `lc_raw_tags` 는 매핑 밖 필드라도
    47A 같은 자유서식 원문에 값이 그대로 들어 있는 경로(LC008)를 겨냥한다
    — 서로 다른 케이스가 서로 다른 경로를 검증하므로 하나를 빠뜨리면 그
    경로를 겨냥한 케이스가 전부 구현 결함처럼 보인다(작업 지시의 경고와
    같은 사고).

    `ruleEngine.types.LCTerms` 는 여기서만 지연 임포트한다 — `terms/`
    다른 모듈들이 `ruleEngine` 을 몰라도 되는 규약(`cascade.py` 모듈
    docstring "의존성 제약")을 이 평가 스크립트도 따른다.
    """
    lc = None
    if case.get("lc"):
        from ruleEngine.types import LCTerms

        lc = LCTerms.from_dict(case["lc"])
    lc_raw_tags = case.get("lc_raw_tags") or {}
    return lc, lc_raw_tags


def _expected_label(case: dict) -> str:
    """코퍼스 라벨(`expect`/`expect_none`/`expect_choice`) → 비교용 문자열.

    코퍼스 스키마 주석이 "하나만 쓴다"고 못박은 제약을 여기서도 강제한다 —
    셋 다 없는 케이스는 코퍼스 자체의 결함이고, 조용히 넘기면 그 케이스가
    항상 "실제가 무엇이든 불일치"로 잘못 세어진다.
    """
    markers = [k for k in ("expect", "expect_none", "expect_choice") if k in case]
    if not markers:
        raise ValueError(f"{case.get('id')}: expect/expect_none/expect_choice 가 없습니다")
    if len(markers) > 1:
        raise ValueError(
            f"{case.get('id')}: expect/expect_none/expect_choice 중 하나만 써야 합니다"
            f" (있음: {markers})"
        )
    if "expect_choice" in case:
        return _OUTCOME_CHOICE
    if "expect_none" in case:
        return _OUTCOME_NONE
    return f"{_VALUE_PREFIX}{case['expect']}"


def _actual_label(result: NormalizeResult, field_name: str, term_class: str) -> str:
    """`NormalizeResult` 에서 이 필드·클래스가 실제로 낸 결과를 읽는다.

    `requires_choice` 를 최우선으로 본다 — ④유사도가 후보 2건 이상을 냈다가
    ⑤가 확정하면 `to_be` 가 채워지고 `requires_choice=False` 로 바뀌므로
    (`cascade._resolve_llm`), 확정된 그 상태를 그대로 "확정 제안"으로 읽으면
    된다. 둘 다 없으면(같은 필드·클래스에 아무 제안도 안 실렸으면) 침묵이다.
    """
    matches = [
        s for s in result.suggestions if s.field.field == field_name and s.term_class == term_class
    ]
    if any(s.requires_choice for s in matches):
        return _OUTCOME_CHOICE
    confirmed = sorted({s.to_be for s in matches if s.to_be is not None})
    if confirmed:
        # 코퍼스는 필드당 클래스 하나에서 값이 하나로 정해지도록 설계됐다.
        # 그래도 span 스캔이 같은 클래스로 두 곳을 잡는 경우를 대비해
        # 값을 이어붙인다 — 조용히 첫 값만 취하면 두 번째 오제안이
        # 불일치 목록에서 사라진다.
        return _VALUE_PREFIX + "|".join(confirmed)
    return _OUTCOME_NONE


def evaluate_corpus(
    corpus_path: Optional[str] = None,
    *,
    llm: bool = False,
    target_precision: float = TARGET_PRECISION,
) -> EvalReport:
    """코퍼스를 읽어 케이스마다 캐스케이드를 돌리고 정밀도·재현율을 낸다.

    `Normalizer` 를 케이스마다 새로 만들지 않는다 — 사전 로드·n-gram 인덱스
    빌드는 기동 비용이지 케이스당 비용이 아니다(`acceptance.py` "냉시작을
    분리한다"와 같은 논거를 여기서는 "애초에 한 번만 만든다"로 지킨다).
    """
    path = Path(corpus_path) if corpus_path else DEFAULT_CORPUS_PATH
    doc = _read_yaml(path)
    cases = list(doc.get("cases") or [])
    corpus_version = str(doc.get("corpus_version") or "")

    stack = GlossaryStack([load_glossary()])
    normalizer = Normalizer(
        stack=stack,
        ranker=NGramRanker(),
        selector=default_selector() if llm else None,
    )

    evals: List[CaseEval] = []
    for case in cases:
        lc, lc_raw_tags = _lc_args(case)
        document = _document_input(case)
        result = normalizer.normalize([document], lc=lc, lc_raw_tags=lc_raw_tags, llm=llm)
        expected = _expected_label(case)
        actual = _actual_label(result, case["field"], case["class"])
        evals.append(
            CaseEval(
                case_id=str(case.get("id", "")),
                doc=case["doc"],
                field=case["field"],
                term_class=case["class"],
                value=case["value"],
                expected=expected,
                actual=actual,
                note=str(case.get("note", "")),
            )
        )

    overall = _aggregate(evals)
    by_class = {
        cls: _aggregate([c for c in evals if c.term_class == cls])
        for cls in sorted({c.term_class for c in evals})
    }
    mismatches = [c for c in evals if not c.ok]

    return EvalReport(
        corpus_version=corpus_version,
        corpus_path=str(path),
        case_count=len(evals),
        llm=llm,
        overall=overall,
        by_class=by_class,
        mismatches=mismatches,
        target_precision=target_precision,
    )


# ── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="F2 표준 용어 교정 정밀도 평가")
    parser.add_argument("--llm", action="store_true", help="⑤단계(LLM 후보 선정) 포함")
    parser.add_argument("--corpus", help="다른 코퍼스 YAML 경로")
    parser.add_argument("--target-precision", type=float, default=TARGET_PRECISION)
    parser.add_argument("--json", type=Path, help="결과를 JSON 으로 저장")
    args = parser.parse_args()

    report = evaluate_corpus(
        corpus_path=args.corpus, llm=args.llm, target_precision=args.target_precision
    )
    print(report.to_text())

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n결과 저장: {args.json}")


if __name__ == "__main__":
    # `.env` 는 **CLI 실행에서만** 읽는다. 모듈 임포트 시점에 읽으면
    # 테스트가 실제 GEMINI_API_KEY 를 집어 네트워크를 타기 시작한다 —
    # 실제로 그렇게 깨뜨렸다(전체 스위트 5초 → 18.6초, 실패 1건 추가).
    # `remaining-work.md` 가 "외부 API 기능은 기본 꺼짐"을 규약으로 둔 이유가
    # 이것이다: 테스트가 조용히 네트워크·비용·지연에 묶이면 안 된다.
    from dotenv import load_dotenv

    load_dotenv()

    main()


__all__ = [
    "CaseEval",
    "DEFAULT_CORPUS_PATH",
    "EvalReport",
    "Metrics",
    "TARGET_PRECISION",
    "evaluate_corpus",
    "main",
]

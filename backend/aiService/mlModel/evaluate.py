"""
하자 검출 성능 평가.

기획안 8.1 정량 목표: "합성 검증셋 기준 주입 하자 검출 F1-score 0.85 이상".
측정 수단이 없으면 목표 달성 여부를 말할 수 없으므로 함께 만든다.

**룰 단독과 룰+모델을 나눠 보고한다.** 합쳐서 하나의 숫자만 내면 모델이
실제로 기여했는지, 아니면 룰이 다 한 건지 구분할 수 없다.

실행:
    python -m mlModel.evaluate --count 2000
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ruleEngine.engine import RuleEngine

from .features import FEATURE_NAMES, RAW_FEATURE_NAMES, extract_features
from .predictor import DefectPredictor
from .synth import Sample, SyntheticGenerator


@dataclass
class Metrics:
    """이진 분류 지표."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        total = (self.true_positive + self.false_positive
                 + self.true_negative + self.false_negative)
        correct = self.true_positive + self.true_negative
        return correct / total if total else 0.0

    @property
    def total(self) -> int:
        return (self.true_positive + self.false_positive
                + self.true_negative + self.false_negative)

    def add(self, predicted: bool, actual: bool) -> None:
        if predicted and actual:
            self.true_positive += 1
        elif predicted and not actual:
            self.false_positive += 1
        elif not predicted and actual:
            self.false_negative += 1
        else:
            self.true_negative += 1

    def to_dict(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "accuracy": round(self.accuracy, 4),
            "confusion": {
                "tp": self.true_positive,
                "fp": self.false_positive,
                "tn": self.true_negative,
                "fn": self.false_negative,
            },
            "sample_count": self.total,
        }


@dataclass
class EvaluationReport:
    """평가 결과 전체."""

    rules_only: Metrics
    rules_plus_model: Optional[Metrics] = None
    raw_features_only: Optional[Metrics] = None
    target_f1: float = 0.85
    per_defect_recall: Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    raw_feature_importance: Dict[str, float] = field(default_factory=dict)
    train_count: int = 0
    eval_count: int = 0

    @property
    def best_f1(self) -> float:
        # `raw_features_only` 는 제외한다. 그건 배포 후보가 아니라 "모델이
        # 룰과 독립적으로 무엇을 아는가"를 재는 비교군이다. 여기에 넣으면
        # 진단용 수치가 기획안 목표 달성 판정을 밀어 올릴 수 있다.
        scores = [self.rules_only.f1]
        if self.rules_plus_model:
            scores.append(self.rules_plus_model.f1)
        return max(scores)

    @property
    def model_contribution(self) -> Optional[float]:
        """결합 모델이 룰 단독 대비 더한 F1."""
        if not self.rules_plus_model:
            return None
        return self.rules_plus_model.f1 - self.rules_only.f1

    @property
    def meets_target(self) -> bool:
        return self.best_f1 >= self.target_f1

    def to_dict(self) -> dict:
        return {
            "target_f1": self.target_f1,
            "best_f1": round(self.best_f1, 4),
            "meets_target": self.meets_target,
            "train_count": self.train_count,
            "eval_count": self.eval_count,
            "rules_only": self.rules_only.to_dict(),
            "rules_plus_model": (
                self.rules_plus_model.to_dict() if self.rules_plus_model else None
            ),
            "raw_features_only": (
                self.raw_features_only.to_dict() if self.raw_features_only else None
            ),
            "model_contribution": (
                round(self.model_contribution, 4)
                if self.model_contribution is not None else None
            ),
            "per_defect_recall": self.per_defect_recall,
            "feature_importance": self.feature_importance,
            "raw_feature_importance": self.raw_feature_importance,
        }

    def to_text(self) -> str:
        lines = [
            "=" * 62,
            "  F3 하자 검출 성능 평가",
            f"  목표: F1 >= {self.target_f1}  (기획안 8.1)",
            "=" * 62,
            "",
            f"학습 {self.train_count}건 / 검증 {self.eval_count}건",
            "",
            _metrics_block("룰엔진 단독", self.rules_only),
        ]
        if self.raw_features_only:
            lines.append(_metrics_block("원시 특징만 (룰 출력 제외)", self.raw_features_only))
        if self.rules_plus_model:
            lines.append(_metrics_block("룰 + XGBoost", self.rules_plus_model))
            lines.append(f"  모델 기여도: F1 {self.model_contribution:+.4f}")
            lines.append("")
        if self.raw_features_only and self.rules_plus_model:
            lines.append(self._independence_block())

        if self.per_defect_recall:
            lines.append("하자 유형별 재현율")
            for kind, recall in sorted(
                self.per_defect_recall.items(), key=lambda x: x[1]
            ):
                bar = "█" * int(recall * 20)
                lines.append(f"  {kind:<20} {recall:.3f}  {bar}")
            lines.append("")

        if self.feature_importance:
            lines.append("피처 기여도 상위 5")
            top = sorted(
                self.feature_importance.items(), key=lambda x: -x[1]
            )[:5]
            for name, gain in top:
                lines.append(f"  {name:<32} {gain:.1f}")
            lines.append("")

        verdict = "✅ 목표 달성" if self.meets_target else "❌ 목표 미달"
        lines.append(f"{verdict}  (최고 F1 {self.best_f1:.4f})")
        lines.append("=" * 62)
        return "\n".join(lines)

    def _independence_block(self) -> str:
        """룰과 모델이 얼마나 겹치는지 3열로 보인다.

        기획안 8.2 가 요구하는 학술적 정당화의 핵심 질문은 "모델이 룰의
        복제본 아닌가"이다. 결합 F1 하나만 내면 그 질문에 답할 수 없다.
        룰 없이 원시 특징만으로 어디까지 가는지를 나란히 놓아야,
        모델이 독립적으로 아는 것이 무엇인지 수치로 말할 수 있다.
        """
        rows = [
            ("룰엔진만", self.rules_only),
            ("원시 특징만 (룰 출력 제외)", self.raw_features_only),
            ("룰 + XGBoost", self.rules_plus_model),
        ]
        lines = [
            "룰·모델 독립성 (기획안 8.2 — 순환논리 대응)",
            f"  {_pad('구성', 28)} {_rjust('정밀도', 8)} {_rjust('재현율', 8)}"
            f" {_rjust('F1', 8)}",
            "  " + "-" * 54,
        ]
        for title, m in rows:
            lines.append(
                f"  {_pad(title, 28)} {m.precision:8.4f} {m.recall:8.4f} {m.f1:8.4f}"
            )

        raw, combined = self.raw_features_only.f1, self.rules_plus_model.f1
        lines += [
            "",
            f"  룰 없이 도달한 F1   {raw:.4f}  (룰 단독 대비 {raw - self.rules_only.f1:+.4f})",
            f"  모델이 더한 F1      {self.model_contribution:+.4f}  (룰 → 결합)",
            "",
        ]
        lines += _wrap(self._independence_verdict(), width=58,
                       first="  → ", rest="    ")
        lines.append("")
        return "\n".join(lines)

    def _independence_verdict(self) -> str:
        """3열 수치를 한 문장으로 읽는다.

        발표에서 이 줄이 그대로 인용될 수 있으므로, 유리하게 읽지 않는다.
        """
        raw = self.raw_features_only.f1
        gain = self.model_contribution or 0.0
        share = raw / self.rules_only.f1 if self.rules_only.f1 else 0.0

        if gain < 0.01 and share < 0.9:
            return (
                f"모델은 룰과 독립적으로는 룰 성능의 {share:.0%} 밖에 못 내고, "
                f"결합해도 F1 을 {gain:+.4f} 만 더한다. 현 설계에서 모델의 "
                "기여는 룰 결과의 재가중에 가깝다."
            )
        if gain < 0.01:
            return (
                f"원시 특징만으로 룰 성능의 {share:.0%} 에 도달하지만 결합 이득은 "
                f"{gain:+.4f} 에 그친다. 두 축이 같은 하자를 본다는 뜻이다."
            )
        return (
            f"원시 특징만으로 룰 성능의 {share:.0%} 를 내고, 결합 시 "
            f"{gain:+.4f} 를 더한다. 모델이 룰과 다른 신호를 쓰고 있다."
        )


def _display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글·전각 문자는 두 칸이다.

    len() 으로 열을 맞추면 한글이 섞인 표가 어긋난다.
    """
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _rjust(text: str, width: int) -> str:
    return " " * max(0, width - _display_width(text)) + text


def _wrap(text: str, width: int, first: str = "", rest: str = "") -> List[str]:
    """표시 폭 기준으로 줄바꿈한다. textwrap 은 한글 폭을 모른다."""
    lines: List[str] = []
    prefix, current = first, ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and _display_width(prefix + candidate) > width:
            lines.append(prefix + current)
            prefix, current = rest, word
        else:
            current = candidate
    if current:
        lines.append(prefix + current)
    return lines


def _metrics_block(title: str, m: Metrics) -> str:
    return (
        f"{title}\n"
        f"  precision {m.precision:.4f}  recall {m.recall:.4f}  "
        f"F1 {m.f1:.4f}  accuracy {m.accuracy:.4f}\n"
        f"  TP {m.true_positive}  FP {m.false_positive}  "
        f"TN {m.true_negative}  FN {m.false_negative}\n"
    )


# ── 평가 실행 ────────────────────────────────────────────────────

def evaluate(
    count: int = 2000,
    defect_ratio: float = 0.5,
    seed: int = 42,
    train_model: bool = True,
    target_f1: float = 0.85,
    corpus_path: Optional[str] = None,
) -> EvaluationReport:
    """합성 데이터로 룰 단독과 룰+모델 성능을 잰다.

    `corpus_path` 를 주면 B/L 을 지어내지 않고 실물 말뭉치에서 뽑는다.
    하자 라벨은 그래도 합성이다 — 바뀌는 것은 서류이지 정답이 아니다.
    """
    generator = SyntheticGenerator(seed=seed, corpus=_load_corpus(corpus_path))
    train_samples, eval_samples = generator.split(count, defect_ratio)
    engine = RuleEngine()

    train_rows, train_labels = _build_matrix(engine, train_samples)
    eval_rows, eval_labels = _build_matrix(engine, eval_samples)

    # 룰 단독: CRITICAL 위반이 하나라도 있으면 하자로 본다.
    rules_only = Metrics()
    for sample in eval_samples:
        verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
        rules_only.add(verdict.has_critical, bool(sample.label))

    report = EvaluationReport(
        rules_only=rules_only,
        target_f1=target_f1,
        train_count=len(train_samples),
        eval_count=len(eval_samples),
        per_defect_recall=_per_defect_recall(engine, eval_samples),
    )

    if not train_model:
        return report

    try:
        predictor = _fit(DefectPredictor(), train_rows, train_labels,
                         eval_rows, eval_labels)
        # 비교군: 룰엔진 출력을 뺀 원시 특징만으로 학습한다. 이 축이 없으면
        # "모델이 룰을 되학습한 것 아닌가"에 수치로 답할 수 없다.
        raw_predictor = _fit(
            DefectPredictor(feature_names=RAW_FEATURE_NAMES),
            train_rows, train_labels, eval_rows, eval_labels,
        )
    except ImportError as exc:
        print(f"[알림] 모델 평가 건너뜀 — {exc}")
        return report

    report.rules_plus_model = _score(predictor, eval_rows, eval_labels)
    report.feature_importance = predictor.feature_importance()
    report.raw_features_only = _score(raw_predictor, eval_rows, eval_labels)
    report.raw_feature_importance = raw_predictor.feature_importance()

    return report


def _fit(predictor, train_rows, train_labels, eval_rows, eval_labels):
    predictor.train(
        train_rows, train_labels,
        eval_rows=eval_rows, eval_labels=eval_labels,
    )
    return predictor


def _score(predictor, eval_rows, eval_labels) -> Metrics:
    metrics = Metrics()
    for probability, actual in zip(predictor.predict_batch(eval_rows), eval_labels):
        metrics.add(probability >= 0.5, bool(actual))
    return metrics


def _build_matrix(
    engine: RuleEngine, samples: Sequence[Sample]
) -> tuple[List[List[float]], List[int]]:
    rows: List[List[float]] = []
    labels: List[int] = []
    for sample in samples:
        verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
        rows.append(extract_features(sample.bl, sample.lc, verdict, sample.as_of).values)
        labels.append(sample.label)
    return rows, labels


def _per_defect_recall(
    engine: RuleEngine, samples: Sequence[Sample]
) -> Dict[str, float]:
    """주입한 하자 유형별로 룰이 잡아내는 비율.

    전체 F1 만 보면 어떤 유형을 놓치는지 모른다. 유형별로 봐야
    룰을 어디에 보강할지 알 수 있다.

    판정 기준은 본 지표와 같은 `has_critical` 이다. '위반이 하나라도
    있으면 검출'로 느슨하게 잡으면 전 유형이 1.000 으로 나와 진단 도구
    구실을 못 한다. CRITICAL 로 승격되지 않는 유형(제시기간 경과 등)이
    드러나야 룰 보강 지점을 알 수 있다.
    """
    hit: Dict[str, int] = {}
    total: Dict[str, int] = {}

    for sample in samples:
        if not sample.injected:
            continue
        verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
        caught = verdict.has_critical
        for kind in sample.injected:
            total[kind] = total.get(kind, 0) + 1
            if caught:
                hit[kind] = hit.get(kind, 0) + 1

    return {
        kind: round(hit.get(kind, 0) / n, 4)
        for kind, n in sorted(total.items())
    }


# ── CLI ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="F3 하자 검출 성능 평가")
    parser.add_argument("--count", type=int, default=2000, help="합성 샘플 수")
    parser.add_argument("--defect-ratio", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-f1", type=float, default=0.85)
    parser.add_argument("--no-model", action="store_true", help="룰만 평가")
    parser.add_argument("--save-model", action="store_true", help="학습 모델 저장")
    parser.add_argument("--json", type=Path, help="결과를 JSON 으로 저장")
    parser.add_argument(
        "--corpus",
        help="실물 B/L 말뭉치. 라벨 디렉토리 또는 캐시 JSON. "
             "주면 B/L 을 지어내지 않고 실물에서 뽑는다 (하자 라벨은 그래도 합성)",
    )
    args = parser.parse_args()

    report = evaluate(
        count=args.count,
        defect_ratio=args.defect_ratio,
        seed=args.seed,
        train_model=not args.no_model,
        target_f1=args.target_f1,
        corpus_path=args.corpus,
    )
    print(report.to_text())

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {**report.to_dict(), "generated_at": datetime.now().isoformat()}
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n결과 저장: {args.json}")

    if args.save_model:
        _train_and_save(args)


def _load_corpus(path: Optional[str]):
    """말뭉치를 적재한다. 경로가 없으면 빈 목록 — 생성기가 기존 경로로 돈다.

    캐시(.json) 와 라벨 디렉토리를 모두 받는다. 디렉토리를 주면 파싱해서
    옆에 캐시를 남긴다 — 4,000건 파싱에 40초가 들고, 학습·평가를 반복하는
    동안 매번 물면 실험 주기가 그만큼 느려진다.
    """
    if not path:
        return []
    from . import corpus as corpus_module

    target = Path(path)
    if target.is_dir():
        records = corpus_module.load(
            label_dir=str(target), cache_path=str(target.parent / "bl_corpus.json")
        )
    else:
        records = corpus_module.load_cache(str(target))
    print(f"실물 말뭉치 {len(records)}건 적재: {path}")
    return records


def _train_and_save(args) -> None:
    generator = SyntheticGenerator(
        seed=args.seed, corpus=_load_corpus(getattr(args, "corpus", None))
    )
    train_samples, _ = generator.split(args.count, args.defect_ratio)
    engine = RuleEngine()
    rows, labels = _build_matrix(engine, train_samples)

    predictor = DefectPredictor()
    predictor.train(rows, labels)
    path = predictor.save()
    print(f"모델 저장: {path}")


if __name__ == "__main__":
    main()

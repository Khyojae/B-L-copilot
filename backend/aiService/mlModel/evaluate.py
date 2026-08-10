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

from .features import FEATURE_NAMES, extract_features
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
    target_f1: float = 0.85
    per_defect_recall: Dict[str, float] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    train_count: int = 0
    eval_count: int = 0

    @property
    def best_f1(self) -> float:
        scores = [self.rules_only.f1]
        if self.rules_plus_model:
            scores.append(self.rules_plus_model.f1)
        return max(scores)

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
            "per_defect_recall": self.per_defect_recall,
            "feature_importance": self.feature_importance,
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
        if self.rules_plus_model:
            lines.append(_metrics_block("룰 + XGBoost", self.rules_plus_model))
            delta = self.rules_plus_model.f1 - self.rules_only.f1
            lines.append(f"  모델 기여도: F1 {delta:+.4f}")
            lines.append("")

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
) -> EvaluationReport:
    """합성 데이터로 룰 단독과 룰+모델 성능을 잰다."""
    generator = SyntheticGenerator(seed=seed)
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
        predictor = DefectPredictor()
        predictor.train(
            train_rows, train_labels,
            eval_rows=eval_rows, eval_labels=eval_labels,
        )
    except ImportError as exc:
        print(f"[알림] 모델 평가 건너뜀 — {exc}")
        return report

    combined = Metrics()
    for probability, actual in zip(predictor.predict_batch(eval_rows), eval_labels):
        combined.add(probability >= 0.5, bool(actual))
    report.rules_plus_model = combined
    report.feature_importance = predictor.feature_importance()

    return report


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
    args = parser.parse_args()

    report = evaluate(
        count=args.count,
        defect_ratio=args.defect_ratio,
        seed=args.seed,
        train_model=not args.no_model,
        target_f1=args.target_f1,
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


def _train_and_save(args) -> None:
    generator = SyntheticGenerator(seed=args.seed)
    train_samples, _ = generator.split(args.count, args.defect_ratio)
    engine = RuleEngine()
    rows, labels = _build_matrix(engine, train_samples)

    predictor = DefectPredictor()
    predictor.train(rows, labels)
    path = predictor.save()
    print(f"모델 저장: {path}")


if __name__ == "__main__":
    main()

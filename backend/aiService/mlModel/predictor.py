"""
하자 확률 예측 (XGBoost 3.3.0).

룰엔진 위에 얹는 확률 축이다. 룰이 "이 조문에 걸린다"를 말한다면 이쪽은
"은행이 하자로 잡을 것 같다"를 말한다. 둘은 다르다 — 룰을 통과해도 하자가
되는 건이 있고(추출 품질 문제), 룰에 걸려도 수리되는 건이 있다
(컨테이너 환적, UCP 600 Art.20(c)).

모델 파일이 없으면 **룰 가중치 합산으로 대체(fallback)한다.** 학습 전에도
파이프라인 전체가 돌아야 하고, 어느 쪽으로 산출했는지는 `Verdict.model` 에
남아 화면·리포트가 정직하게 표기할 수 있다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from f3_rules.types import LCTerms, Verdict

from .features import FEATURE_NAMES, extract_features, select

DEFAULT_MODEL_PATH = Path(__file__).parent / "artifacts" / "defect_model.json"

# 학습 파라미터. 데이터가 수천 건 규모라 깊이를 얕게 잡는다.
# 깊게 가면 합성 데이터의 생성 규칙을 그대로 외운다.
DEFAULT_PARAMS = {
    "max_depth": 4,
    "eta": 0.1,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "seed": 42,
}
DEFAULT_ROUNDS = 200


@dataclass
class Prediction:
    """하자 확률 1건."""

    probability: float
    model: str          # "xgboost-v1" | "rules-v1"
    is_defect: bool
    threshold: float

    def to_dict(self) -> dict:
        return {
            "probability": round(self.probability, 4),
            "model": self.model,
            "is_defect": self.is_defect,
            "threshold": self.threshold,
        }


class DefectPredictor:
    """XGBoost 하자 확률 예측기."""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        threshold: float = 0.5,
        feature_names: Optional[Sequence[str]] = None,
    ) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.threshold = threshold
        # 기본은 전체 피처다. 부분집합을 주면 그 열만 쓰는 비교군 모델이 된다
        # (`features.RAW_FEATURE_NAMES`). 순서는 저장·로드에서 대조하므로
        # 여기서 정한 순서가 그대로 규약이 된다.
        self.feature_names: List[str] = list(feature_names or FEATURE_NAMES)
        self._booster = None
        self._loaded = False

    # ── 예측 ──────────────────────────────────────────────────────

    def predict(
        self,
        bl,
        lc: Optional[LCTerms],
        verdict: Verdict,
        as_of: Optional[datetime] = None,
    ) -> Prediction:
        """서류 1건의 하자 확률."""
        booster = self._get_booster()
        if booster is None:
            # 학습 전이거나 XGBoost 미설치. 룰 가중치로 대체한다.
            probability = verdict.defect_probability
            return Prediction(
                probability=probability,
                model="rules-v1",
                is_defect=probability >= self.threshold,
                threshold=self.threshold,
            )

        features = extract_features(bl, lc, verdict, as_of)
        probability = float(self._raw_predict(booster, [features.values])[0])
        return Prediction(
            probability=probability,
            model="xgboost-v1",
            is_defect=probability >= self.threshold,
            threshold=self.threshold,
        )

    def predict_batch(self, rows: Sequence[Sequence[float]]) -> List[float]:
        """피처 행렬 → 확률 목록. 평가 하네스가 쓴다."""
        booster = self._get_booster()
        if booster is None:
            raise RuntimeError("학습된 모델이 없습니다. train() 을 먼저 실행하세요.")
        return [float(p) for p in self._raw_predict(booster, rows)]

    # ── 학습 ──────────────────────────────────────────────────────

    def train(
        self,
        rows: Sequence[Sequence[float]],
        labels: Sequence[int],
        rounds: int = DEFAULT_ROUNDS,
        params: Optional[dict] = None,
        eval_rows: Optional[Sequence[Sequence[float]]] = None,
        eval_labels: Optional[Sequence[int]] = None,
    ) -> None:
        """모델을 학습한다.

        `rows` 는 언제나 `FEATURE_NAMES` 전체 순서로 받는다. 부분집합 모델도
        마찬가지다 — 열을 고르는 일은 예측기가 한다. 호출부가 자르게 두면
        학습과 추론에서 서로 다르게 자를 수 있고, 그 오류는 조용하다.
        """
        xgb = _import_xgboost()

        train_set = xgb.DMatrix(_to_matrix(self._project(rows)), label=list(labels),
                                feature_names=self.feature_names)
        watchlist = [(train_set, "train")]
        if eval_rows is not None and eval_labels is not None:
            valid = xgb.DMatrix(_to_matrix(self._project(eval_rows)),
                                label=list(eval_labels),
                                feature_names=self.feature_names)
            watchlist.append((valid, "valid"))

        self._booster = xgb.train(
            {**DEFAULT_PARAMS, **(params or {})},
            train_set,
            num_boost_round=rounds,
            evals=watchlist,
            verbose_eval=False,
        )
        self._loaded = True

    def save(self, path: Optional[Path] = None) -> Path:
        """모델과 피처 순서를 함께 저장한다.

        피처 순서가 어긋나면 모델은 조용히 틀린 답을 낸다. 같이 저장해서
        로드 시 대조할 수 있게 한다.
        """
        if self._booster is None:
            raise RuntimeError("저장할 모델이 없습니다.")

        target = Path(path) if path else self.model_path
        target.parent.mkdir(parents=True, exist_ok=True)
        self._booster.save_model(str(target))

        target.with_suffix(".meta.json").write_text(
            json.dumps(
                {"feature_names": self.feature_names, "params": DEFAULT_PARAMS},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return target

    def feature_importance(self) -> dict:
        """피처 기여도. 모델이 무엇을 보고 판단하는지 확인용."""
        if self._booster is None:
            return {}
        return self._booster.get_score(importance_type="gain")

    # ── 내부 ─────────────────────────────────────────────────────

    def _get_booster(self):
        if self._loaded:
            return self._booster
        self._loaded = True

        if not self.model_path.exists():
            return None
        try:
            xgb = _import_xgboost()
        except ImportError:
            return None

        self._verify_feature_order()
        booster = xgb.Booster()
        booster.load_model(str(self.model_path))
        self._booster = booster
        return booster

    def _verify_feature_order(self) -> None:
        """저장 당시의 피처 순서와 현재가 같은지 확인한다."""
        meta_path = self.model_path.with_suffix(".meta.json")
        if not meta_path.exists():
            return
        saved = json.loads(meta_path.read_text(encoding="utf-8")).get("feature_names")
        if saved and saved != self.feature_names:
            raise RuntimeError(
                "모델의 피처 순서가 현재 코드와 다릅니다. 모델을 다시 학습하세요.\n"
                f"  저장됨: {saved}\n  현재:   {self.feature_names}"
            )

    def _project(self, rows: Sequence[Sequence[float]]) -> Sequence[Sequence[float]]:
        """전체 피처 행렬에서 이 모델이 쓰는 열만 남긴다."""
        if self.feature_names == FEATURE_NAMES:
            return rows
        for row in rows:
            if len(row) != len(FEATURE_NAMES):
                raise ValueError(
                    f"행의 열 수가 FEATURE_NAMES 와 다릅니다 "
                    f"({len(row)} != {len(FEATURE_NAMES)}). "
                    "부분집합 모델도 전체 피처 행을 받습니다."
                )
            break
        return [select(list(row), self.feature_names) for row in rows]

    def _raw_predict(self, booster, rows: Sequence[Sequence[float]]) -> List[float]:
        xgb = _import_xgboost()
        matrix = xgb.DMatrix(_to_matrix(self._project(rows)),
                             feature_names=self.feature_names)
        return list(booster.predict(matrix))


def _import_xgboost():
    try:
        import xgboost as xgb
    except ImportError as exc:
        raise ImportError(
            "XGBoost 가 설치되어 있지 않습니다: pip install 'xgboost>=3.3.0'\n"
            "모델 없이도 룰 가중치 합산으로 하자 확률이 산출됩니다."
        ) from exc
    return xgb


def _to_matrix(rows: Sequence[Sequence[float]]):
    try:
        import numpy as np

        return np.asarray(rows, dtype=float)
    except ImportError:
        return [list(map(float, row)) for row in rows]

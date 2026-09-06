"""확률 보정 (설계서 6.3).

표본이 작으므로 isotonic 금지, sigmoid(Platt) 만 사용한다. isotonic 은
수백~수천 표본에서 계단형으로 과적합한다. 반드시 calibration 분할에만 적합하고
(train 분할 재사용 금지), 부스터가 본 적 없는 데이터를 쓴다.

설계 결정: 설계서 6.3 은 `CalibratedClassifierCV(estimator, method="sigmoid",
cv="prefit")` 를 예시로 들지만, scikit-learn 신버전에서 이를 그대로 구현하면
`FrozenEstimator` 가 적합된 XGBClassifier 전체를 감싸 `calibrator.joblib` 안에
그대로 직렬화(pickle)한다 — 이는 설계서 6.5 가 명시적으로 금지하는 "모델을
pickle 로 저장"과 정확히 같은 문제(xgboost 버전 취약성)를 calibrator.joblib
경로로 재도입한다. 따라서 여기서는 raw_score(스칼라, booster.predict 출력) 만
입력으로 받는 1차원 로지스틱 회귀로 Platt scaling 을 직접 구현한다 — 수학적으로
Platt(1999)의 sigmoid 보정과 동일한 형태(y ~ sigmoid(A·raw_score + B))이며,
calibrator.joblib 에는 xgboost 객체가 전혀 들어가지 않는다.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression


def fit_calibrator(raw_scores_cal: np.ndarray, y_cal: np.ndarray) -> LogisticRegression:
    """calibration 분할의 (raw_score, y) 로 Platt scaling 을 적합한다."""
    model = LogisticRegression(solver="lbfgs")
    model.fit(np.asarray(raw_scores_cal).reshape(-1, 1), np.asarray(y_cal))
    return model


def predict_proba(calibrator: LogisticRegression, raw_scores: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(np.asarray(raw_scores).reshape(-1, 1))[:, 1]


def reliability_curve(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> dict[str, list[float]]:
    """10구간 신뢰도 다이어그램(설계서 6.4)에 쓸 (예측확률평균, 실제하자율) 쌍."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(y_prob, bins[1:-1], right=True)
    mean_predicted: list[float] = []
    fraction_positive: list[float] = []
    counts: list[int] = []
    for b in range(n_bins):
        mask = bin_idx == b
        if mask.sum() == 0:
            continue
        mean_predicted.append(float(np.mean(y_prob[mask])))
        fraction_positive.append(float(np.mean(y_true[mask])))
        counts.append(int(mask.sum()))
    return {
        "mean_predicted_probability": mean_predicted,
        "fraction_of_positives": fraction_positive,
        "bin_count": counts,
    }

"""분할 → 학습 → 보정 → 평가 → 아티팩트 (설계서 6절).

3분할 + 그룹(GroupShuffleSplit, groups=base_shipment_id) · 얕은 XGBoost ·
calibration 분할에 별도 적합하는 sigmoid 보정 · 기획안 10.4 의 3조건×2비율
평가표 산출까지 이 모듈 하나가 오케스트레이션한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, f1_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from xgboost import XGBClassifier

from f3_research import calibration, config, dataset
from f3_research.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    MODEL_ONLY_GROUPS,
    feature_group,
)
from f3_research.registry import build_version_string

MODEL_ONLY_COLUMNS = tuple(n for n in FEATURE_NAMES if feature_group(n) in MODEL_ONLY_GROUPS)
COMBINED_COLUMNS = tuple(FEATURE_NAMES)

assert len(MODEL_ONLY_COLUMNS) == 44, len(MODEL_ONLY_COLUMNS)
assert len(COMBINED_COLUMNS) == 74, len(COMBINED_COLUMNS)


@dataclass
class SplitIndices:
    train: np.ndarray
    calibration: np.ndarray
    validation: np.ndarray


def _load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"데이터셋이 없습니다: {path}\n먼저 `python -m f3_research.cli gen-data` 를 실행하세요."
        )
    return pd.read_parquet(path)


def _load_llm_backend(manifest_path: Path) -> str:
    """gen-data 가 남긴 매니페스트에서 실제 생성에 쓰인 llm_backend 를 읽는다.

    계획서 8단계 Task 5: "오프라인 휴리스틱으로 만든 데이터셋"과 "Gemini 로
    만든 데이터셋"을 절대 헷갈리면 안 된다 — `config.LLM_FEATURE_BACKEND`
    현재값이 아니라, **그 데이터셋이 실제로 생성될 때 쓰인 값**(매니페스트에
    박제된 값)을 신뢰한다. 둘이 다를 수 있다(예: gen-data 이후 환경변수가
    바뀐 채로 train 을 실행). 매니페스트가 없으면(구버전 데이터셋 등)
    config 현재값으로 대체한다.
    """
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest.get("llm_backend")
        if backend is not None:
            return backend
    return config.LLM_FEATURE_BACKEND


def _group_split(df: pd.DataFrame, seed: int) -> SplitIndices:
    """설계서 6.1: train 60% / calibration 20% / validation 20%, groups=base_shipment_id."""
    groups = df["base_shipment_id"].to_numpy()
    idx_all = np.arange(len(df))

    gss1 = GroupShuffleSplit(n_splits=1, test_size=config.SPLIT_VALIDATION_RATIO, random_state=seed)
    trainval_idx, val_idx = next(gss1.split(idx_all, groups=groups))

    cal_fraction = config.SPLIT_CALIBRATION_RATIO / (
        config.SPLIT_TRAIN_RATIO + config.SPLIT_CALIBRATION_RATIO
    )
    gss2 = GroupShuffleSplit(n_splits=1, test_size=cal_fraction, random_state=seed + 1)
    trainval_groups = groups[trainval_idx]
    train_rel, cal_rel = next(gss2.split(trainval_idx, groups=trainval_groups))

    train_idx = trainval_idx[train_rel]
    cal_idx = trainval_idx[cal_rel]

    # 그룹 분리 검증 — 같은 base_shipment_id 가 두 분할에 걸치면 누수(설계서 6.1).
    assert not (set(groups[train_idx]) & set(groups[cal_idx]))
    assert not (set(groups[train_idx]) & set(groups[val_idx]))
    assert not (set(groups[cal_idx]) & set(groups[val_idx]))

    return SplitIndices(train=train_idx, calibration=cal_idx, validation=val_idx)


def _train_booster(
    x_train: pd.DataFrame, y_train: pd.Series, x_val: pd.DataFrame, y_val: pd.Series
) -> XGBClassifier:
    """설계서 6.2 하이퍼파라미터. scale_pos_weight=neg/pos — 하자가 다수 클래스라 <1."""
    pos = int(y_train.sum())
    neg = int(len(y_train) - pos)
    scale_pos_weight = neg / pos if pos > 0 else 1.0

    clf = XGBClassifier(
        **config.XGB_PARAMS,
        n_estimators=config.XGB_MAX_ESTIMATORS,
        early_stopping_rounds=config.XGB_EARLY_STOPPING_PATIENCE,
        scale_pos_weight=scale_pos_weight,
    )
    clf.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    return clf


def _best_f1_threshold(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[float, float]:
    """검증 분할에서 F1 을 최대화하는 임계값을 찾는다(평가셋으로 튜닝하지 않는다)."""
    best_t, best_f1 = 0.5, f1_score(y_true, (y_prob >= 0.5).astype(int), zero_division=0)
    for t in np.linspace(0.01, 0.99, 99):
        f1 = f1_score(y_true, (y_prob >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t, best_f1


def _bootstrap_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    metric_fn,
    *,
    n_boot: int = config.BOOTSTRAP_N,
    seed: int = 42,
    ci: float = config.BOOTSTRAP_CI,
) -> tuple[float, float, float]:
    """부트스트랩 신뢰구간(설계서 5.6) — (점추정, 하한, 상한).

    "결합 F1 0.856" 이 아니라 "0.856 [0.84, 0.87]" 로 보고하기 위한 근거.
    성공 판정은 하한으로 한다(점추정이 임계를 넘어도 하한이 못 넘으면 미달성).
    """
    n = len(y_true)
    point = float(metric_fn(y_true, y_score))
    if n == 0:
        return point, float("nan"), float("nan")

    rng = np.random.RandomState(seed)
    alpha = (1.0 - ci) / 2.0
    stats: list[float] = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, n)
        yt, ys = y_true[idx], y_score[idx]
        try:
            stats.append(float(metric_fn(yt, ys)))
        except ValueError:
            continue  # 재표본에 한 클래스만 남는 등 지표 계산 불가 케이스는 건너뛴다
    if not stats:
        return point, float("nan"), float("nan")
    lower = float(np.percentile(stats, 100 * alpha))
    upper = float(np.percentile(stats, 100 * (1 - alpha)))
    return point, lower, upper


def _metric_with_ci(y_true: np.ndarray, y_score: np.ndarray, metric_fn, *, seed: int) -> dict[str, float]:
    point, lo, hi = _bootstrap_ci(y_true, y_score, metric_fn, seed=seed)
    return {"point": point, "ci_lower": lo, "ci_upper": hi}


def _condition_metrics(
    y_true: np.ndarray, y_prob: np.ndarray, threshold_0_5: float, best_threshold: float, *, seed: int = 42
) -> dict[str, object]:
    """설계서 6.4 지표 + 설계서 5.6 부트스트랩 95% 신뢰구간을 함께 산출한다."""
    has_both_classes = len(np.unique(y_true)) > 1

    def _f1_at(t: float):
        return lambda yt, yp: f1_score(yt, (yp >= t).astype(int), zero_division=0)

    f1_05 = _metric_with_ci(y_true, y_prob, _f1_at(threshold_0_5), seed=seed)
    f1_best = _metric_with_ci(y_true, y_prob, _f1_at(best_threshold), seed=seed + 1)
    brier = _metric_with_ci(y_true, y_prob, brier_score_loss, seed=seed + 3)
    if has_both_classes:
        roc_auc = _metric_with_ci(y_true, y_prob, roc_auc_score, seed=seed + 2)
    else:
        roc_auc = {"point": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan")}

    return {
        "f1_at_0.5": f1_05,
        "f1_at_best_threshold": f1_best,
        "best_threshold": float(best_threshold),
        "roc_auc": roc_auc,
        "brier": brier,
        "n": int(len(y_true)),
        "positive_rate": float(np.mean(y_true)),
    }


def _rule_only_metrics(df: pd.DataFrame) -> dict[str, object]:
    """룰 단독 조건: rv_any_critical==1 → 하자 예측. 확률이 아니라 0/1 이므로
    임계값 튜닝은 의미가 없다(둘 다 0.5 로 동일) — ROC-AUC·Brier 는 이진 점수를
    "확률"처럼 취급해 계산한다(참고용, 확률적 모델과 직접 비교 목적의 하한선)."""
    y_true = df["y"].to_numpy()
    y_score = df["rv_any_critical"].to_numpy().astype(float)
    return _condition_metrics(y_true, y_score, 0.5, 0.5)


def _mcw_sensitivity_sweep(
    train_rows: pd.DataFrame,
    cal_rows: pd.DataFrame,
    val_rows: pd.DataFrame,
    columns: tuple[str, ...],
) -> list[dict[str, object]]:
    """min_child_weight 민감도 표(설계서 4절 하이퍼파라미터 탐색 요건).

    학습셋 내 validation 분할(=봉인 평가셋과 무관한 holdout)에서만 탐색한다 —
    `eval_sealed_*.parquet` 은 이 함수에 전달되지 않는다. 검증자가 지적한
    "min_child_weight=5 에서 결합 F1 0.613(룰 단독보다 낮음)" 취약성이 metrics.json
    에 그대로 드러나야 한다(숨기지 않는다).
    """
    x_train = train_rows[list(columns)]
    y_train = train_rows["y"]
    x_val = val_rows[list(columns)]
    y_val = val_rows["y"]
    x_cal = cal_rows[list(columns)]
    y_cal = cal_rows["y"]

    pos = int(y_train.sum())
    neg = int(len(y_train) - pos)
    scale_pos_weight = neg / pos if pos > 0 else 1.0

    rows: list[dict[str, object]] = []
    for mcw in config.MCW_SWEEP_VALUES:
        params = dict(config.XGB_PARAMS)
        params["min_child_weight"] = mcw
        clf = XGBClassifier(
            **params,
            n_estimators=config.XGB_MAX_ESTIMATORS,
            early_stopping_rounds=config.XGB_EARLY_STOPPING_PATIENCE,
            scale_pos_weight=scale_pos_weight,
        )
        clf.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)

        raw_val = clf.predict_proba(x_val)[:, 1]
        raw_cal = clf.predict_proba(x_cal)[:, 1]
        calibrator = calibration.fit_calibrator(raw_cal, y_cal.to_numpy())
        cal_val_prob = calibration.predict_proba(calibrator, raw_val)

        y_val_arr = y_val.to_numpy()
        best_t, best_f1 = _best_f1_threshold(y_val_arr, cal_val_prob)
        f1_05 = f1_score(y_val_arr, (cal_val_prob >= 0.5).astype(int), zero_division=0)
        roc_auc = (
            float(roc_auc_score(y_val_arr, cal_val_prob)) if len(np.unique(y_val_arr)) > 1 else float("nan")
        )
        rows.append(
            {
                "min_child_weight": mcw,
                "combined_f1_at_0.5": float(f1_05),
                "combined_f1_best_threshold": float(best_f1),
                "best_threshold": float(best_t),
                "roc_auc": roc_auc,
                "n_estimators_used": int(getattr(clf, "best_iteration", -1)) + 1
                if getattr(clf, "best_iteration", None) is not None
                else None,
            }
        )
    return rows


def run_training(*, register: bool = False, note: str | None = None) -> dict[str, Any]:
    train_df = _load_dataset(config.TRAIN_DATASET_FILE)
    eval_df = _load_dataset(config.EVAL_DATASET_FILE)

    leak_diag = dataset.leakage_diagnostics(train_df)
    print("=== 누수 진단 (설계서 1절) ===")
    for k, v in leak_diag.items():
        print(f"  {k}: {v}")
    assert leak_diag["phi_y_vs_rv_any_critical"] < 0.98, "라벨 누수 의심: phi >= 0.98"

    separability_diag = dataset.separability_diagnostics(train_df)
    print("=== 룰 밖 하자 유형별 단일 피처 분리력 진단 (설계서 1절 신규) ===")
    for defect_type, info in separability_diag.items():
        print(f"  {defect_type}: {info}")
        auc = info.get("max_single_feature_auc")
        if auc is not None and not (isinstance(auc, float) and auc != auc):  # NaN 이 아닌 경우만
            assert auc < 0.95, f"{defect_type}: 단일 피처 AUC={auc} — 완전분리(워터마크) 의심"

    splits = _group_split(train_df, config.TRAIN_SEED)
    train_rows = train_df.iloc[splits.train]
    cal_rows = train_df.iloc[splits.calibration]
    val_rows = train_df.iloc[splits.validation]
    print(f"분할 크기 — train={len(train_rows)} calibration={len(cal_rows)} validation={len(val_rows)}")

    eval_balanced_df = dataset.make_balanced(eval_df, seed=config.EVAL_SEED)

    results: dict[str, Any] = {"conditions": {"natural": {}, "balanced": {}}}
    fitted_models: dict[str, dict[str, Any]] = {}

    for cond_name, columns in (("model_only", MODEL_ONLY_COLUMNS), ("combined", COMBINED_COLUMNS)):
        x_train = train_rows[list(columns)]
        y_train = train_rows["y"]
        x_val = val_rows[list(columns)]
        y_val = val_rows["y"]
        x_cal = cal_rows[list(columns)]
        y_cal = cal_rows["y"]

        clf = _train_booster(x_train, y_train, x_val, y_val)

        raw_val = clf.predict_proba(x_val)[:, 1]
        raw_cal = clf.predict_proba(x_cal)[:, 1]
        calibrator = calibration.fit_calibrator(raw_cal, y_cal.to_numpy())

        cal_val_prob = calibration.predict_proba(calibrator, raw_val)
        best_threshold, _ = _best_f1_threshold(y_val.to_numpy(), cal_val_prob)

        fitted_models[cond_name] = {
            "clf": clf,
            "calibrator": calibrator,
            "columns": list(columns),
            "best_threshold": best_threshold,
        }

        for ratio_name, ratio_df in (("natural", eval_df), ("balanced", eval_balanced_df)):
            x_eval = ratio_df[list(columns)]
            y_eval = ratio_df["y"].to_numpy()
            raw_eval = clf.predict_proba(x_eval)[:, 1]
            cal_eval_prob = calibration.predict_proba(calibrator, raw_eval)
            results["conditions"][ratio_name][cond_name] = _condition_metrics(
                y_eval, cal_eval_prob, 0.5, best_threshold
            )

    for ratio_name, ratio_df in (("natural", eval_df), ("balanced", eval_balanced_df)):
        results["conditions"][ratio_name]["rule_only"] = _rule_only_metrics(ratio_df)

    combined_natural = results["conditions"]["natural"]["combined"]
    rule_natural = results["conditions"]["natural"]["rule_only"]
    # 설계서 6.4 는 "결합 F1 >= 0.85 그리고 결합 F1 > 룰 단독 F1" 이라고만 쓰고
    # threshold=0.5 인지 최적 임계인지 명시하지 않는다. scale_pos_weight=neg/pos(<1,
    # 하자가 다수 클래스이므로 설계서 6.2 지시대로 뒤집힘)를 쓰면 0.5 는 더 이상
    # 자연스러운 결정 경계가 아니라서 두 해석이 갈릴 수 있다 — 어느 한 쪽으로
    # 미리 정하지 않고 두 임계 기준을 모두 계산해 그대로 보고한다(임의로 유리한
    # 쪽만 골라 "성공"이라 부르지 않기 위함). "결합 > 룰 단독"은 임계·비율·지표
    # (F1·ROC-AUC·Brier) 전 조합에서 예외 없이 성립하는지도 함께 표시한다.
    #
    # 설계서 5.6: 성공 판정은 부트스트랩 95% 신뢰구간의 "하한"으로 한다 — 점추정이
    # 0.85 를 넘겨도 하한이 0.85 미만이면 "달성"이라 기록하지 않는다.
    def _passes(threshold_key: str) -> bool:
        c = combined_natural[threshold_key]
        r = rule_natural[threshold_key]
        return c["ci_lower"] >= config.SUCCESS_F1_THRESHOLD and c["point"] > r["point"]

    combined_beats_rule_everywhere = all(
        results["conditions"][ratio][cond]["f1_at_0.5"]["point"]
        > results["conditions"][ratio]["rule_only"]["f1_at_0.5"]["point"]
        and (
            results["conditions"][ratio][cond]["roc_auc"]["point"]
            > results["conditions"][ratio]["rule_only"]["roc_auc"]["point"]
        )
        for ratio in ("natural", "balanced")
        for cond in ("combined",)
    )

    results["success"] = {
        "criterion": (
            "결합 F1 신뢰구간 하한 >= 0.85 AND 결합 F1 점추정 > 룰 단독 F1 점추정 (자연 비율) "
            "— 설계서 5.6: 성공 판정은 신뢰구간 하한 기준"
        ),
        "passed_at_threshold_0.5": bool(_passes("f1_at_0.5")),
        "passed_at_best_threshold": bool(_passes("f1_at_best_threshold")),
        "combined_beats_rule_on_every_metric_and_ratio": bool(combined_beats_rule_everywhere),
        "combined_f1_at_0.5": combined_natural["f1_at_0.5"],
        "rule_only_f1_at_0.5": rule_natural["f1_at_0.5"],
        "combined_f1_best_threshold": combined_natural["f1_at_best_threshold"],
        "rule_only_f1_best_threshold": rule_natural["f1_at_best_threshold"],
        "combined_roc_auc": combined_natural["roc_auc"],
        "rule_only_roc_auc": rule_natural["roc_auc"],
    }
    # 하위 호환: 둘 중 하나라도 두 조건(하한>=0.85, 점추정>룰단독)을 만족하면 전체 통과로 본다.
    results["success"]["passed"] = bool(
        results["success"]["passed_at_threshold_0.5"] or results["success"]["passed_at_best_threshold"]
    )
    results["leakage_diagnostics"] = leak_diag
    results["separability_diagnostics"] = separability_diag

    print("=== min_child_weight 민감도 스윕 (학습셋 내 validation holdout만 사용) ===")
    mcw_sweep = _mcw_sensitivity_sweep(train_rows, cal_rows, val_rows, COMBINED_COLUMNS)
    for row in mcw_sweep:
        print(f"  {row}")
    results["mcw_sensitivity"] = mcw_sweep

    dataset_fingerprint = {
        "train_seed": config.TRAIN_SEED,
        "train_base_count": config.TRAIN_BASE_COUNT,
        "train_variants_per_base": config.TRAIN_VARIANTS_PER_BASE,
        "train_rows": int(len(train_df)),
        "eval_seed": config.EVAL_SEED,
        "eval_base_count": config.EVAL_BASE_COUNT,
        "eval_variants_per_base": config.EVAL_VARIANTS_PER_BASE,
        "eval_rows": int(len(eval_df)),
        "hyperparams": {
            **config.XGB_PARAMS,
            "n_estimators": config.XGB_MAX_ESTIMATORS,
            "early_stopping_rounds": config.XGB_EARLY_STOPPING_PATIENCE,
        },
    }
    version = build_version_string(FEATURE_SCHEMA_VERSION, dataset_fingerprint)
    results["model_version"] = version
    results["feature_schema_version"] = FEATURE_SCHEMA_VERSION
    results["trained_at"] = date.today().isoformat()
    results["training_label_count"] = int(len(train_rows))
    # 계획서 8단계 Task 5: metrics.json 에도 llm_backend 를 남긴다(HANDOFF.md 8단계
    # 요건 — "오프라인 휴리스틱 실행"과 "Gemini 실행"을 metrics.json 만 보고도
    # 구분할 수 있어야 한다).
    results["llm_backend"] = _load_llm_backend(config.TRAIN_MANIFEST_FILE)
    results["reviewer_backend"] = config.REVIEWER_BACKEND

    _save_artifacts(version, fitted_models["combined"], results, train_df, eval_df)

    if register:
        _register_and_maybe_activate(version, results, note)

    return results


def _save_artifacts(
    version: str,
    combined: dict[str, Any],
    results: dict[str, Any],
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
) -> None:
    """설계서 6.5 아티팩트 산출. 결합(82피처) 모델만 등록 대상으로 저장한다 —
    모델 단독 조건은 비교표 산출용 임시 모델이며 레지스트리 대상이 아니다."""
    out_dir = config.ARTIFACTS_DIR / version
    out_dir.mkdir(parents=True, exist_ok=True)

    booster = combined["clf"].get_booster()
    booster.save_model(str(out_dir / "model.ubj"))  # pickle 금지(설계서 6.5)

    joblib.dump(combined["calibrator"], out_dir / "calibrator.joblib")

    (out_dir / "feature_names.json").write_text(
        json.dumps(
            {
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "feature_names": list(COMBINED_COLUMNS),
                "best_threshold": combined["best_threshold"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (out_dir / "metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    (out_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "train_seed": config.TRAIN_SEED,
                "train_base_count": config.TRAIN_BASE_COUNT,
                "train_variants_per_base": config.TRAIN_VARIANTS_PER_BASE,
                "train_rows": int(len(train_df)),
                "eval_seed": config.EVAL_SEED,
                "eval_base_count": config.EVAL_BASE_COUNT,
                "eval_variants_per_base": config.EVAL_VARIANTS_PER_BASE,
                "eval_rows": int(len(eval_df)),
                # 계획서 8단계 Task 5: 오프라인 휴리스틱 데이터셋과 Gemini 데이터셋을
                # 절대 혼동하지 않기 위한 기록(HANDOFF.md 8단계 요건).
                "reviewer_backend": config.REVIEWER_BACKEND,
                "llm_backend": _load_llm_backend(config.TRAIN_MANIFEST_FILE),
                "eval_llm_backend": _load_llm_backend(config.EVAL_MANIFEST_FILE),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _save_calibration_curve(out_dir, combined, eval_df)


def _save_calibration_curve(out_dir: Path, combined: dict[str, Any], eval_df: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x_eval = eval_df[combined["columns"]]
    y_eval = eval_df["y"].to_numpy()
    raw = combined["clf"].predict_proba(x_eval)[:, 1]
    prob = calibration.predict_proba(combined["calibrator"], raw)
    curve = calibration.reliability_curve(y_eval, prob)

    # 기본 폰트(DejaVu Sans)는 한글 글리프가 없어 라벨을 영어로 둔다(설계서 6.4
    # 신뢰도 다이어그램 요구사항의 내용 자체는 한글 주석/문서에 그대로 설명해 둔다).
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
    ax.plot(curve["mean_predicted_probability"], curve["fraction_of_positives"], marker="o", label="Combined model")
    ax.set_xlabel("Predicted probability (calibrated)")
    ax.set_ylabel("Observed defect rate")
    ax.set_title("Reliability diagram (eval set, natural ratio, 10 bins)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "calibration_curve.png", dpi=120)
    plt.close(fig)


def _register_and_maybe_activate(version: str, results: dict[str, Any], note: str | None) -> None:
    """설계서 8절: 재학습 후 검증셋 성능이 하락하면 activate 를 호출하지 않는다."""
    from smart_e_bl.db import sync_session

    from f3_research import registry

    combined_natural = results["conditions"]["natural"]["combined"]
    metrics = {
        "f1": combined_natural["f1_at_0.5"]["point"],
        "roc_auc": combined_natural["roc_auc"]["point"],
        "brier": combined_natural["brier"]["point"],
    }
    with sync_session() as session:
        active = registry.get_active_version(session)
        active_f1 = float(active.metric_f1) if active and active.metric_f1 is not None else None
        registry.register(session, version, metrics, results["training_label_count"], note=note)
        session.commit()
        if registry.should_activate(metrics["f1"], active_f1):
            registry.activate(session, version)
            print(f"[registry] {version} 활성화됨 (이전 활성 F1={active_f1})")
        else:
            print(
                f"[registry] 경고: 새 모델 F1({metrics['f1']}) < 활성 모델 F1({active_f1}). "
                "활성화하지 않음 — 이전 모델 유지(자동 롤백 원칙)."
            )

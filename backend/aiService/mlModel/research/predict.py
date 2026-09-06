"""추론 진입점 (설계서 9절).

snapshot ─ extract_features ─ to_vector ─ booster ─ raw_score
                                             └─ calibrator ─ probability

shap·matplotlib 는 설명 생성 시에만 필요하므로 모듈 최상단에서 import 하지
않는다(설계서 10절) — `explain.py::top_factors` 가 지연 import 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import xgboost as xgb

from f3_research import calibration
from f3_research.features import FEATURE_SCHEMA_VERSION, extract_features, to_vector
from f3_research.schema import ShipmentSnapshot

DEFERRED_FIELD_RATIO_THRESHOLD = 0.20  # 설계서 9절: 판정 보류 필드 20% 초과 시 범위만 제시


class FeatureSchemaMismatchError(Exception):
    """모델 아티팩트의 FEATURE_SCHEMA_VERSION 이 현재 코드와 다를 때 추론을 거부한다."""


@dataclass
class ModelArtifact:
    version: str
    booster: xgb.Booster
    calibrator: Any
    feature_names: list[str]
    feature_schema_version: str
    best_threshold: float


@dataclass
class PredictionResult:
    probability: float
    raw_score: float
    is_calibrated: bool
    model_version: str
    rule_catalog_version: str | None
    feature_snapshot: dict[str, float]
    deferred_field_count: int
    is_range_only: bool
    is_lc_absent: bool
    top_factors: list[Any] = field(default_factory=list)


def load_artifact(version_dir: Path) -> ModelArtifact:
    version_dir = Path(version_dir)
    meta = json.loads((version_dir / "feature_names.json").read_text(encoding="utf-8"))

    if meta["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
        raise FeatureSchemaMismatchError(
            f"모델 아티팩트의 피처 스키마({meta['feature_schema_version']})가 "
            f"현재 코드({FEATURE_SCHEMA_VERSION})와 다릅니다. 추론을 거부합니다 "
            "(설계서 9절: 스키마 불일치 시 명시적 예외)."
        )

    booster = xgb.Booster()
    booster.load_model(str(version_dir / "model.ubj"))
    calibrator = joblib.load(version_dir / "calibrator.joblib")

    return ModelArtifact(
        version=version_dir.name,
        booster=booster,
        calibrator=calibrator,
        feature_names=meta["feature_names"],
        feature_schema_version=meta["feature_schema_version"],
        best_threshold=meta.get("best_threshold", 0.5),
    )


def predict(
    snapshot: ShipmentSnapshot,
    artifact: ModelArtifact,
    *,
    rule_catalog_version: str | None = None,
) -> PredictionResult:
    features = extract_features(snapshot)
    vector = to_vector(features)

    # to_vector() 는 FEATURE_SPECS(=artifact.feature_names) 순서를 그대로 따른다.
    # 학습 시 pandas DataFrame(컬럼명 포함)으로 적합했기 때문에 저장된 booster 는
    # feature_names 메타데이터를 요구한다 — DMatrix 에도 동일하게 넘겨야 한다.
    dmatrix = xgb.DMatrix(np.array([vector], dtype=float), feature_names=list(artifact.feature_names))
    raw_score = float(artifact.booster.predict(dmatrix)[0])
    probability = float(calibration.predict_proba(artifact.calibrator, np.array([raw_score]))[0])

    checked = snapshot.extraction_quality.checked_field_count or 1
    deferred = len(snapshot.extraction_quality.missing_fields) + len(
        snapshot.extraction_quality.no_evidence_fields
    )
    is_range_only = (deferred / checked) > DEFERRED_FIELD_RATIO_THRESHOLD

    return PredictionResult(
        probability=probability,
        raw_score=raw_score,  # 기획안 5.3: API 응답·화면에 절대 노출하지 않는다(분석용)
        is_calibrated=True,
        model_version=artifact.version,
        rule_catalog_version=rule_catalog_version,
        feature_snapshot=features,
        deferred_field_count=deferred,
        is_range_only=is_range_only,
        is_lc_absent=snapshot.lc is None,
    )

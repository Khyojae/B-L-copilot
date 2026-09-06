"""설명 (설계서 7절) — SHAP 상위 5요인.

`predict.py` 는 런타임 추론 경로이므로 shap 를 모듈 최상단에서 import 하지
않는다(설계서 10절) — 이 파일 자체가 이미 지연 import 경계다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from f3_research.features import feature_group


@dataclass(frozen=True)
class PredictionFactor:
    rank: int
    feature_name: str
    feature_group: str | None
    shap_value: float


def top_factors(booster: Any, x_row: Any, feature_names: list[str], top_k: int = 5) -> list[PredictionFactor]:
    """`shap.TreeExplainer` 를 보정 전 부스터에 적용한다.

    보정기는 단조 변환이므로 SHAP 값의 순위는 보정 후에도 보존된다(설계서 7절).
    반환되는 shap_value 는 log-odds 마진 단위다 — 절대 확률의 %p 로 서술하지 말 것
    (기획안 5.4 "LLM 은 수치를 생성하지 않는다" 규약, 리포트 수치 대조 검사 대상).
    """
    import shap  # 지연 import(설계서 10절)

    explainer = shap.TreeExplainer(booster)
    shap_values = explainer.shap_values(x_row)
    if shap_values.ndim > 1:
        row_values = shap_values[0]
    else:
        row_values = shap_values

    ranked = sorted(
        zip(feature_names, row_values), key=lambda pair: abs(pair[1]), reverse=True
    )[:top_k]

    return [
        PredictionFactor(
            rank=i + 1,
            feature_name=name,
            feature_group=feature_group(name),
            shap_value=float(value),
        )
        for i, (name, value) in enumerate(ranked)
    ]

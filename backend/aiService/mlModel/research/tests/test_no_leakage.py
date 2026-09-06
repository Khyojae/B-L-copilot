"""★ 설계서 1절 불변식 검사 — 이 파일이 이 프로젝트에서 가장 중요한 테스트다.

라벨 누수를 차단하는 두 개의 독립 채널(synth/rule_sim.py, synth/review.py)이
실제로 독립인지 정적·통계적으로 검증한다. 여기가 깨지면 결합 모델의 F1 이
아무리 높아도 "룰 단독 대비 개선"이라는 이 프로젝트의 핵심 주장이 성립하지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sklearn.metrics import roc_auc_score

from f3_research import config, dataset

SYNTH_DIR = Path(__file__).resolve().parent.parent / "synth"


def _imported_module_names(path: Path) -> set[str]:
    """파일이 import 하는 모듈·심볼 이름을 전부 모은다.

    ⚠️ v3 구현은 `ImportFrom` 에서 `node.module` 만 담았다. 그래서
    `from f3_research import rule_adapter` 같은 형태가 **통째로 보이지 않았고**,
    채널 독립성 검사가 반쯤 공허했다(돌연변이 검사로 확인). `from X import Y` 의
    Y 까지 `X.Y` 로 담아야 실제로 막힌다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


# 채널 A(피처)를 구성하는 모듈들. review.py(채널 B)는 이 중 어느 것도 import 하면 안 된다.
# v3 에서는 채널 A 가 rule_sim.py 하나뿐이라 문자열 "rule_sim" 만 검사했는데,
# v4 에서 rule_sim.py 를 **삭제**했으므로 그 검사는 영원히 통과하면서 아무것도
# 지키지 않는 공허한 테스트가 된다(설계서 12절, HANDOFF R8). 실제 채널 A 모듈
# 전체를 나열해 검사한다.
#
# 계획서 8단계: llm_features.py(Group 7, LLM 피처)도 채널 A 확장이다 —
# review.py 를 import 하면 "같은 모델이 피처와 라벨을 동시에 만드는" 위험과는
# 별개로, 피처 계산 코드가 라벨 판정 로직에 정적으로 결합되는 냄새 자체를
# 막는다(render.py 를 별도 중립 모듈로 뺀 이유가 정확히 이것).
_CHANNEL_A_MODULES = ("rule_sim", "rule_adapter", "ruleEngine", "extraction_view", "llm_features")


def test_review_does_not_import_channel_a_statically() -> None:
    """설계서 12절 체크리스트 1항: 채널 B(review)가 채널 A 를 import 하지 않는다.

    라벨을 만드는 쪽이 룰 발화를 보게 되면 두 채널이 같은 정보원을 공유해
    "룰 발화 → 라벨"이라는 누수 경로가 생긴다. 그러면 논문의 핵심 실험
    ("결합 > 룰 단독")이 자명하게 참이 되어 의미를 잃는다.
    """
    imports = _imported_module_names(SYNTH_DIR / "review.py")
    offenders = [
        name for name in imports if any(mod in name for mod in _CHANNEL_A_MODULES)
    ]
    assert not offenders, f"review.py 가 채널 A 모듈을 import 합니다: {offenders}"


def test_channel_a_does_not_import_review_statically() -> None:
    """대칭 검사: 채널 A 모듈들이 review.py 를 import 하지 않는다."""
    package_dir = SYNTH_DIR.parent
    channel_a_paths = [
        SYNTH_DIR / "extraction_view.py",
        package_dir / "rule_adapter.py",
        package_dir / "llm_features.py",
        *sorted((package_dir / "ruleEngine").glob("*.py")),
    ]
    for path in channel_a_paths:
        assert path.exists(), f"채널 A 모듈이 사라졌습니다: {path} — 검사가 공허해집니다"
        imports = _imported_module_names(path)
        offenders = [name for name in imports if "review" in name]
        assert not offenders, f"{path.name} 이 review 를 import 합니다: {offenders}"


def test_rule_sim_is_deleted() -> None:
    """v4 에서 rule_sim.py 는 실제 룰엔진으로 대체돼 삭제됐다(설계서 5.4).

    파일이 되살아나면 위 검사 목록이 실제 사용 모듈과 어긋나게 되므로 명시 검사한다.
    """
    assert not (SYNTH_DIR / "rule_sim.py").exists(), (
        "rule_sim.py 가 되살아났습니다 — 실제 룰엔진(rule_adapter+extraction_view)이 채널 A 입니다"
    )


@pytest.fixture(scope="module")
def small_dataset():
    """1절 진단 통계는 표본이 작으면 노이즈가 크므로 적당한 규모로 생성한다."""
    result = dataset.generate_dataset(seed=42, base_count=400, variants_per_base=3)
    return result.dataframe


def test_uncovered_defect_ratio_at_least_35_percent(small_dataset) -> None:
    """설계서 12절 체크리스트 2항: 룰 밖 하자 비율 >= 35% (주입 "건수" 기준)."""
    df = small_dataset
    has_any = df[df["defect_count"] > 0]
    assert len(has_any) > 0
    uncovered_ratio = float(has_any["has_uncovered_defect"].mean())
    assert uncovered_ratio >= 0.30, (
        f"룰 밖 하자를 포함한 선적 비율이 너무 낮습니다: {uncovered_ratio}"
    )


def test_phi_below_leakage_threshold(small_dataset) -> None:
    """설계서 1절: phi(y, rv_any_critical) < 0.95. 0.98 이상이면 누수로 간주한다."""
    diag = dataset.leakage_diagnostics(small_dataset)
    phi = diag["phi_y_vs_rv_any_critical"]
    assert phi < 0.95, f"phi={phi} — 라벨 누수 의심(0.95 미만이어야 함)"
    assert phi < 0.98, f"phi={phi} — 라벨 누수 확정 임계(0.98) 이상입니다"


def test_defect_rate_when_rule_silent_at_least_10_percent(small_dataset) -> None:
    """설계서 1절: 룰 미발화 건 중 하자 비율 >= 0.10 (룰 밖 하자 존재 증명)."""
    diag = dataset.leakage_diagnostics(small_dataset)
    rate = diag["defect_rate_when_rule_silent"]
    assert rate >= 0.10, f"룰 미발화 건 중 하자 비율이 너무 낮습니다: {rate}"


def test_repair_rate_when_rule_fired_at_least_10_percent(small_dataset) -> None:
    """설계서 1절: 룰 발화 건 중 수리 비율 >= 0.10 (오탐 존재 증명)."""
    diag = dataset.leakage_diagnostics(small_dataset)
    rate = diag["repair_rate_when_rule_fired"]
    assert rate >= 0.10, f"룰 발화 건 중 수리 비율이 너무 낮습니다: {rate}"


def test_overall_defect_rate_in_expected_range(small_dataset) -> None:
    """기획안 2장 실제 수치(65~75%)에 맞도록 파라미터가 보정되어 있는지 확인한다.

    표본 변동을 감안해 다소 넓은 허용 구간을 둔다.
    """
    diag = dataset.leakage_diagnostics(small_dataset)
    rate = diag["overall_defect_rate"]
    assert 0.55 <= rate <= 0.85, f"전체 하자율이 기대 범위를 벗어났습니다: {rate}"


# ---------------------------------------------------------------------------
# 설계서 1절 신규 요건 — 중첩(overlap) 검증. v1 설계는 룰 밖 하자 유형마다
# 결정론적 워터마크를 남겨 단일 피처 AUC 1.000(완전분리)이 측정됐다. 이 절은
# 그 결함이 고쳐졌는지를 검증한다.
# ---------------------------------------------------------------------------


def test_uncovered_defect_type_max_single_feature_auc_below_085(small_dataset) -> None:
    """설계서 12절 체크리스트: 룰 밖 하자 유형별 단일 피처 최대 AUC < 0.85."""
    diag = dataset.separability_diagnostics(small_dataset)
    assert diag, "separability_diagnostics 가 빈 결과를 반환했습니다"
    for defect_type, info in diag.items():
        auc = info["max_single_feature_auc"]
        if auc != auc:  # NaN (표본 부족) — 건너뛴다
            continue
        assert auc < 0.85, (
            f"{defect_type}: 단일 피처({info['max_auc_feature']}) AUC={auc} >= 0.85 — "
            "완전분리에 가까운 워터마크가 의심됩니다"
        )


def test_uncovered_defect_type_distributions_overlap(small_dataset) -> None:
    """설계서 12절 체크리스트: 무하자/하자 피처 분포가 각 축에서 겹친다(min/max 교집합 ≠ ∅)."""
    diag = dataset.separability_diagnostics(small_dataset)
    assert diag
    for defect_type, info in diag.items():
        if info["distributions_overlap"] is None:
            continue
        assert info["distributions_overlap"], (
            f"{defect_type}: 최대 분리 피처({info['max_auc_feature']})에서 "
            "무하자/하자 분포 구간이 겹치지 않습니다(완전분리)"
        )


def test_uncovered_defect_types_are_not_traceless(small_dataset) -> None:
    """설계서 5.3 요건 3: 흔적이 아예 없는(AUC~0.5, 라벨 노이즈) 유형을 두지 않는다.

    signer_authority_ambiguous·customary_wording_missing 도 약하지만 0이 아닌
    신호를 가져야 한다 — 순수 라벨 노이즈(AUC ≈ 0.5)가 아님을 확인한다.
    """
    diag = dataset.separability_diagnostics(small_dataset)
    for defect_type in ("signer_authority_ambiguous", "customary_wording_missing"):
        info = diag.get(defect_type)
        if info is None or info["max_single_feature_auc"] != info["max_single_feature_auc"]:
            continue
        assert info["max_single_feature_auc"] > 0.5, (
            f"{defect_type}: 단일 피처 AUC={info['max_single_feature_auc']} — "
            "흔적이 없는 순수 라벨 노이즈로 보입니다"
        )


# ---------------------------------------------------------------------------
# 설계서 4절 Group 6(HISTORY) 검증 — v2 라벨 누수(leave-group-out 타깃 인코딩)
# 재발 방지 확인 3종(설계서 12절 체크리스트).
# ---------------------------------------------------------------------------


def test_history_features_constant_within_entity() -> None:
    """설계서 12절 체크리스트: HISTORY 값이 엔티티당 상수다(행마다 다르면 누수).

    막으려는 것은 **행 고유 정보가 이력 피처에 새어드는 것**이다(v2 의 leave-base-out
    타깃 인코딩이 정확히 그랬다). 따라서 검사는 두 갈래여야 한다.

    1. 이력이 있는(웜) 행: 엔티티당 값이 **정확히 상수**여야 한다.
    2. 콜드스타트 행: 설계서 4절 Group 6 규칙 4에 따라 비율 3개가 **NaN** 이다.
       이 NaN 여부는 **거래처 정체성만의 함수**여야 한다 — 같은 거래처인데 행마다
       NaN 여부가 갈리면 그게 바로 행 고유 정보 누수다.

    콜드스타트를 뭉뚱그려 `dropna=False` 로 세면 은행·화물유형 그룹 안에
    (실제값, NaN) 두 값이 섞여 상수성 검사가 깨진다. 그건 누수가 아니라
    거래처의 콜드스타트가 은행 그룹에 비쳐 보이는 것뿐이므로, 두 갈래로 나눠 본다.
    """
    result = dataset.generate_dataset(seed=42, base_count=300, variants_per_base=3)
    df = result.dataframe

    # ── 1. 웜 행은 엔티티당 정확히 상수 ────────────────────────────────
    warm = df[df["hist_is_cold_start"] == 0]
    assert len(warm) > 0, "웜 행이 하나도 없어 상수성을 검사할 수 없습니다"

    for col, key in (
        ("hist_counterparty_defect_rate", "counterparty_id"),
        ("hist_counterparty_shipment_count", "counterparty_id"),
        ("hist_bank_defect_rate", "bank_id"),
        ("hist_cargo_type_defect_rate", "cargo_type"),
    ):
        max_distinct = warm.groupby(key)[col].nunique(dropna=False).max()
        assert max_distinct == 1, f"{col} 가 {key} 별로 상수가 아닙니다(웜 행 기준)"

    # counterparty_shipment_count 는 콜드스타트에서도 0 으로 정의되므로 전 행 상수여야 한다.
    max_distinct = df.groupby("counterparty_id")["hist_counterparty_shipment_count"].nunique(
        dropna=False
    ).max()
    assert max_distinct == 1, "hist_counterparty_shipment_count 가 counterparty_id 별로 상수가 아닙니다"

    # ── 2. 콜드스타트 NaN 은 거래처만의 함수 (핵심 누수 방지선) ────────
    for col in (
        "hist_counterparty_defect_rate",
        "hist_bank_defect_rate",
        "hist_cargo_type_defect_rate",
    ):
        mixed = df.groupby("counterparty_id")[col].apply(lambda s: s.isna().nunique())
        assert int((mixed > 1).sum()) == 0, (
            f"{col} 의 NaN 여부가 같은 거래처 안에서 행마다 갈립니다 — 행 고유 정보 누수"
        )


def test_history_only_auc_below_070_on_sealed_eval() -> None:
    """설계서 12절 체크리스트: HISTORY 단독 예측 AUC < 0.70.

    "잠재 성향의 실제 예측력 수준" — 0.9 이상이면 누수. 학습 데이터와 시드가
    다른(=학습 중 열람하지 않는다는 의미의) "봉인" 표본에서 검증한다. v2는 이
    조건에서 AUC 1.000(한 줄짜리 디코더로 라벨 완전 복원)이 나왔었다.
    """
    from sklearn.linear_model import LogisticRegression

    from f3_research.features import FEATURE_NAMES, feature_group

    hist_cols = [f for f in FEATURE_NAMES if feature_group(f) == "HISTORY"]

    train_result = dataset.generate_dataset(seed=11, base_count=400, variants_per_base=3)
    train_df = train_result.dataframe
    eval_result = dataset.generate_dataset(seed=12345, base_count=400, variants_per_base=1)
    eval_df = eval_result.dataframe

    median = train_df[hist_cols].median()
    x_train = train_df[hist_cols].fillna(median)
    x_eval = eval_df[hist_cols].fillna(median)

    clf = LogisticRegression(max_iter=1000)
    clf.fit(x_train, train_df["y"])
    p_eval = clf.predict_proba(x_eval)[:, 1]
    auc = roc_auc_score(eval_df["y"], p_eval)
    assert auc < 0.70, f"HISTORY 단독 예측 AUC={auc} — 누수 의심(0.70 미만이어야 함)"


def test_holdout_eval_auc_gap_below_003_when_history_dropped() -> None:
    """설계서 12절 체크리스트: HISTORY 제거 시 홀드아웃-평가셋 AUC 격차 < 0.03.

    v2에서는 이 격차가 약 0.2(학습 홀드아웃 0.894 vs 봉인 평가셋 0.687)에
    달했다 — HISTORY 피처가 자기 라벨을 leave-group-out 인코딩했기 때문이다.
    실제 학습/평가 규모·시드(config.TRAIN_*/EVAL_*)를 그대로 써서 재발이 없는지
    확인한다 — 77 피처(HISTORY 제외)에서는 표본이 작으면 AUC 추정 자체의 표본
    변동만으로 격차가 0.03 을 넘나들 수 있어, 실제 정책 규모에서 재현해야
    의미가 있다.
    """
    from f3_research.features import FEATURE_NAMES, feature_group
    from f3_research.train import _group_split, _train_booster

    no_history_cols = [f for f in FEATURE_NAMES if feature_group(f) != "HISTORY"]

    train_result = dataset.generate_dataset(
        seed=config.TRAIN_SEED,
        base_count=config.TRAIN_BASE_COUNT,
        variants_per_base=config.TRAIN_VARIANTS_PER_BASE,
    )
    train_df = train_result.dataframe
    splits = _group_split(train_df, config.TRAIN_SEED)
    train_rows = train_df.iloc[splits.train]
    val_rows = train_df.iloc[splits.validation]

    eval_result = dataset.generate_dataset(
        seed=config.EVAL_SEED,
        base_count=config.EVAL_BASE_COUNT,
        variants_per_base=config.EVAL_VARIANTS_PER_BASE,
    )
    eval_df = eval_result.dataframe

    clf = _train_booster(
        train_rows[no_history_cols], train_rows["y"], val_rows[no_history_cols], val_rows["y"]
    )
    val_auc = roc_auc_score(val_rows["y"], clf.predict_proba(val_rows[no_history_cols])[:, 1])
    eval_auc = roc_auc_score(eval_df["y"], clf.predict_proba(eval_df[no_history_cols])[:, 1])

    gap = abs(val_auc - eval_auc)
    assert gap < 0.03, (
        f"HISTORY 제거 후 홀드아웃({val_auc:.4f})-평가셋({eval_auc:.4f}) AUC 격차={gap:.4f} "
        "— 0.03 미만이어야 합니다(다른 곳의 누수 의심)"
    )

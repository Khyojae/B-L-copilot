"""분할 로직 테스트 (설계서 6.1) — groups=base_shipment_id 로 그룹이 섞이지 않는지."""

from __future__ import annotations

from f3_research import dataset
from f3_research.train import _group_split


def test_group_split_has_no_overlap_across_splits() -> None:
    result = dataset.generate_dataset(seed=42, base_count=100, variants_per_base=3)
    df = result.dataframe
    splits = _group_split(df, seed=42)

    groups = df["base_shipment_id"]
    train_groups = set(groups.iloc[splits.train])
    cal_groups = set(groups.iloc[splits.calibration])
    val_groups = set(groups.iloc[splits.validation])

    assert not (train_groups & cal_groups)
    assert not (train_groups & val_groups)
    assert not (cal_groups & val_groups)

    # 모든 행이 정확히 한 분할에만 속한다.
    total = len(splits.train) + len(splits.calibration) + len(splits.validation)
    assert total == len(df)


def test_group_split_roughly_matches_target_ratios() -> None:
    result = dataset.generate_dataset(seed=42, base_count=300, variants_per_base=3)
    df = result.dataframe
    splits = _group_split(df, seed=42)
    n = len(df)
    train_ratio = len(splits.train) / n
    cal_ratio = len(splits.calibration) / n
    val_ratio = len(splits.validation) / n

    assert 0.50 <= train_ratio <= 0.70
    assert 0.10 <= cal_ratio <= 0.30
    assert 0.10 <= val_ratio <= 0.30


def test_train_and_eval_datasets_use_different_seeds() -> None:
    from f3_research import config

    assert config.TRAIN_SEED != config.EVAL_SEED


def test_make_balanced_yields_50_50() -> None:
    result = dataset.generate_dataset(seed=42, base_count=200, variants_per_base=3)
    df = result.dataframe
    balanced = dataset.make_balanced(df, seed=42)
    assert len(balanced) > 0
    rate = balanced["y"].mean()
    assert abs(rate - 0.5) < 0.02

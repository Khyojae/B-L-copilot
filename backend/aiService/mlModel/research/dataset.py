"""합성 → (X, y, groups) 변환 + 누수 진단 (설계서 11절 5단계).

두 독립 채널(룰엔진+관측노이즈, review)을 오케스트레이션한다. Group 6(HISTORY) 피처는
**X의 행이 아닌 별도의 이력 기간(history period) 선적**에서 계산한다(설계서 4절
Group 6 규칙 1) — v2는 데이터셋 안의 다른 base_shipment_id 로 leave-one-group-out
집계를 했는데, 엔티티 안에서 그렇게 남는 유일한 변동이 사실상 자기 base의 라벨
합이 되어 자기 라벨의 LOO 인코딩이 됐다(누수). 이 구현은 그 경로 자체를 없앤다:
이력 기간 선적은 generator.generate_history_shipments() 가 별도로 생성하고,
채널 B로 라벨링한 뒤 관측 비율만 남기며, 원본 선적은 X에 전혀 등장하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, replace

import pandas as pd
from sklearn.metrics import roc_auc_score

from f3_research import config, llm_features
from f3_research.features import ALL_GROUPS, FEATURE_NAMES, extract_features, feature_group
from f3_research.render import render_document_set
from f3_research.schema import HistoryStats
from f3_research import rule_adapter
from f3_research.ruleEngine import RuleEngine
from f3_research.synth import generator, injector, review
from f3_research.synth.extraction_view import extraction_view
from f3_research.synth.generator import EntityPools, GeneratorParams, SynthShipment
from f3_research.synth.pools import ValuePools, load_pools

# HISTORY(Group 6)는 pass 2 로, LLM_SEMANTIC(Group 7)은 아래 "pass 1a-2"로
# 미룬다 — 둘 다 개별 행 루프 시점에는 아직 계산할 수 없는 정보(이력 집계,
# LLM 배치 호출)에 의존하기 때문이다. HISTORY 와 같은 지연 패턴이지만, LLM은
# X의 행 자체(관측값 문서 텍스트)에서 나오므로 이력 기간처럼 별도 선적
# 집합이 필요하지는 않다.
PASS1_GROUPS = tuple(g for g in ALL_GROUPS if g not in ("HISTORY", "LLM_SEMANTIC"))

META_COLUMNS = (
    "shipment_id",
    "base_shipment_id",
    "y",
    "counterparty_id",
    "bank_id",
    "cargo_type",
    "defect_count",
    "has_covered_defect",
    "has_uncovered_defect",
    # 설계서 1절 신규 진단(유형별 단일 피처 AUC)의 근거 — 모델 학습에는 쓰이지 않는다
    # (FEATURE_NAMES 에 없으므로 X 벡터화에 포함되지 않는다).
    "uncovered_defect_types",
)


def _derive_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def load_field_accuracy(path=None) -> dict[str, float]:
    """eval_report_merged.json 의 overall.field_accuracy_by_field (설계서 5.1)."""
    path = path or config.EVAL_REPORT_PATH
    if not path.exists():
        print(f"[dataset] 경고: {path} 를 찾을 수 없어 필드별 기본 정확도(0.9)를 사용합니다.")
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("overall", {}).get("field_accuracy_by_field", {}))


@dataclass
class GenerationResult:
    dataframe: pd.DataFrame
    seed: int
    base_count: int
    variants_per_base: int
    total_rows: int
    claude_fallback_count: int = 0  # 설계서 5.5: claude 백엔드 폴백 건수(데이터셋 매니페스트 기록 대상)
    # 계획서 8단계 Task 5: LLM 피처(Group 7) 백엔드 이름·폴백 건수. metrics.json·
    # dataset manifest 양쪽에 기록해 "오프라인 휴리스틱으로 만든 데이터셋"과
    # "Gemini 로 만든 데이터셋"을 절대 헷갈리지 않게 한다.
    llm_backend: str = "offline"
    llm_feature_fallback_count: int = 0


@dataclass
class _HistoryAggregate:
    """이력 기간 라벨을 엔티티별로 집계한 결과. 값이 없는 키는 콜드스타트(관측 0건)다."""

    counterparty: dict[str, tuple[float | None, int]]
    bank: dict[str, tuple[float | None, int]]
    cargo_type: dict[str, tuple[float | None, int]]


def _label_history_shipments(
    seed: int, shipments: list[SynthShipment]
) -> tuple[list[int], int]:
    """이력 기간 선적을 채널 B로 라벨링한다(설계서 4절 Group 6 규칙 1 — 동일 채널
    B, 별도 선적 집합). 반환된 라벨은 관측 비율 집계에만 쓰이고 X의 행이 되지
    않는다. 채널 A(룰엔진)는 호출하지 않는다 — 이력 선적은 Group 1 피처를
    가질 필요가 없다(X에 들어가지 않으므로).
    """
    label_inputs: list[tuple] = []
    for idx, shipment in enumerate(shipments):
        injector_rng = random.Random(_derive_seed(seed, "history", idx, "injector"))
        review_rng = random.Random(_derive_seed(seed, "history", idx, "review"))
        mutated, defects = injector.inject_defects(shipment, injector_rng)
        label_inputs.append((mutated, defects, review_rng))
    return review.compute_labels(label_inputs)


def _aggregate_history(
    shipments: list[SynthShipment], labels: list[int]
) -> _HistoryAggregate:
    """엔티티(거래처·은행·화물유형)별 (관측 비율, 관측 건수)를 집계한다.

    타깃 인코딩이 아니다 — 이 집계에 들어가는 라벨은 전부 이력 기간 선적(X의
    행이 아닌 별도 집합)의 라벨이며, X의 어떤 행의 y 도 자기 자신 또는 다른
    X 행의 피처 계산에 들어가지 않는다(설계서 4절 Group 6 규칙 2).
    """

    def _accumulate(key_fn) -> dict[str, tuple[float | None, int]]:
        sums: dict[str, int] = {}
        counts: dict[str, int] = {}
        for shipment, y in zip(shipments, labels):
            key = key_fn(shipment)
            sums[key] = sums.get(key, 0) + y
            counts[key] = counts.get(key, 0) + 1
        return {
            key: ((sums[key] / counts[key]) if counts[key] > 0 else None, counts[key])
            for key in counts
        }

    return _HistoryAggregate(
        counterparty=_accumulate(lambda s: s.counterparty_id),
        bank=_accumulate(lambda s: s.bank_id),
        cargo_type=_accumulate(lambda s: s.cargo_type),
    )


def generate_dataset(
    *,
    seed: int,
    base_count: int,
    variants_per_base: int,
    pools: ValuePools | None = None,
    field_accuracy: dict[str, float] | None = None,
) -> GenerationResult:
    """설계서 5절 전체 파이프라인 실행: generator → injector → {extraction_view+룰엔진, review} → features."""
    # 계획서 8단계 Task 4: 채널 독립 위반 조합(LLM_FEATURE_BACKEND='gemini' +
    # REVIEWER_BACKEND 가 실전 LLM)은 3,000건 생성에 들어가기 전에 즉시 거부한다
    # (HANDOFF.md 불변식 2 — "어떤 작업도 하기 전에 발화").
    llm_features.check_channel_independence()

    pools = pools or load_pools()
    field_accuracy = field_accuracy if field_accuracy is not None else load_field_accuracy()

    gen_rng = random.Random(seed)
    params = GeneratorParams(seed=seed, base_count=base_count)
    entities: EntityPools = generator.build_entity_pools(pools, params, gen_rng)
    base_shipments = generator.generate_base_shipments(pools, entities, params, field_accuracy)

    # ── 이력 기간(history period) — 설계서 4절 Group 6 규칙 1. X의 행이 되는
    # base_shipments 와 완전히 분리된 선적 집합을 생성해 채널 B로 라벨링하고,
    # 원본은 버린 채 엔티티별 관측 비율·건수만 남긴다. 시드는 (seed, "history")
    # 에서만 파생되므로 variants_per_base 나 base_count 와 무관하게 재현 가능하다.
    history_rng = random.Random(_derive_seed(seed, "history"))
    history_shipments = generator.generate_history_shipments(pools, entities, field_accuracy, history_rng)
    history_labels, history_fallback_count = _label_history_shipments(seed, history_shipments)
    history_agg = _aggregate_history(history_shipments, history_labels)

    # ── pass 1a: HISTORY 를 제외한 모든 피처를 확정한다(라벨 y 는 아직 비움) ──
    # y 산출은 아래에서 별도로 수행한다 — review_rng 는 (seed, base_idx, variant_idx)
    # 로부터 독립적으로 파생되므로(다른 rng 호출 순서에 의존하지 않음) 피처 계산과
    # 분리해도 재현성이 깨지지 않는다. 이 분리 덕분에 claude 백엔드(설계서 5.5)가
    # Batches API 로 전체 선적을 한 번에 판정할 수 있다.
    pass1_rows: list[dict] = []
    snapshots = []
    llm_items: list[tuple[str, str]] = []  # (shipment_id, 관측값 문서 텍스트) — llm_features.compute_features_batch 입력
    # 룰엔진은 생성 시 YAML 을 파싱하므로 행마다가 아니라 한 번만 만든다.
    rule_engine = RuleEngine()
    label_inputs: list[tuple] = []  # (mutated, defects, review_rng) — review.compute_labels 입력
    for base_idx, base in enumerate(base_shipments):
        for variant_idx in range(variants_per_base):
            injector_rng = random.Random(_derive_seed(seed, base_idx, variant_idx, "injector"))
            rule_rng = random.Random(_derive_seed(seed, base_idx, variant_idx, "rule"))
            review_rng = random.Random(_derive_seed(seed, base_idx, variant_idx, "review"))

            variant = base.copy()
            variant.shipment_id = f"{base.base_shipment_id}-v{variant_idx}"
            mutated, defects = injector.inject_defects(variant, injector_rng)

            # 채널 A: 실제 룰엔진이 **관측값**(OCR 추출 사본) 위에서 돈다(설계서 5.4).
            # 진실이 아니라 관측값을 보기 때문에 FN/FP 가 하나의 근거 있는
            # 메커니즘에서 파생된다. 채널 A 는 review 를 모른다.
            observed = extraction_view(mutated, rule_rng)
            rule_outcome = rule_adapter.evaluate_shipment(
                observed, rule_engine, catalog_version=rule_engine.catalog_version
            )

            placeholder_history = HistoryStats(counterparty_shipment_count=0)
            snapshot = generator.to_snapshot(mutated, rule_outcome, placeholder_history)
            feats = extract_features(snapshot, groups=PASS1_GROUPS)

            uncovered_types = ";".join(sorted({d.type for d in defects if not d.covered_by_rule}))

            pass1_rows.append(
                {
                    "shipment_id": mutated.shipment_id,
                    "base_shipment_id": mutated.base_shipment_id,
                    "counterparty_id": mutated.counterparty_id,
                    "bank_id": mutated.bank_id,
                    "cargo_type": mutated.cargo_type,
                    "y": None,
                    "defect_count": len(defects),
                    "has_covered_defect": any(d.covered_by_rule for d in defects),
                    "has_uncovered_defect": any(not d.covered_by_rule for d in defects),
                    "uncovered_defect_types": uncovered_types,
                    **feats,
                }
            )
            snapshots.append(snapshot)
            label_inputs.append((mutated, defects, review_rng))
            # LLM 피처(채널 A 확장, Group 7)도 룰엔진과 같은 **관측값**(observed)을
            # 본다 — 진실(mutated)이 아니다(계획서 8단계 Task 5). 렌더링만 미리
            # 해 두고 실제 계산은 아래에서 배치로 묶어 한 번에 호출한다(review.py
            # 의 pass 1b 와 같은 패턴 — 10단계 Gemini Batches API 호출에 대비).
            llm_items.append((mutated.shipment_id, render_document_set(observed)))

    # ── pass 1a-2: 채널 A 확장 — LLM 피처(Group 7). 룰엔진과 마찬가지로 **관측값**
    # 문서 텍스트만 본다(위 루프에서 이미 렌더링해 둔 llm_items). 이력 기간
    # 선적은 여기 들어오지 않는다 — history_shipments 는 X의 행이 아니므로
    # LLM 피처를 계산할 이유가 없다(계획서 8단계 Task 5 "히스토리 기간은 이걸
    # 호출하면 안 된다").
    llm_by_id, llm_feature_fallback_count = llm_features.compute_features_batch(llm_items)
    for idx, row in enumerate(pass1_rows):
        snapshot_with_llm = replace(snapshots[idx], llm=llm_by_id[row["shipment_id"]])
        snapshots[idx] = snapshot_with_llm
        llm_feats = extract_features(snapshot_with_llm, groups=("LLM_SEMANTIC",))
        row.update(llm_feats)

    # ── pass 1b: 채널 B — injected_defects → 은행 판정(y). review 는 채널 A 를 모른다.
    # 백엔드는 config.REVIEWER_BACKEND 로 고른다(설계서 5.5 "두 개의 백엔드").
    labels, main_fallback_count = review.compute_labels(label_inputs)
    for row, y in zip(pass1_rows, labels):
        row["y"] = y
    claude_fallback_count = main_fallback_count + history_fallback_count

    # ── pass 2: HISTORY 피처 — 이력 기간 집계값을 엔티티별로 붙인다(설계서 4절
    # Group 6). 타깃 인코딩이 아니다: 붙이는 값은 전부 위에서 미리 계산해 둔,
    # X 행의 y 와는 독립인 이력 기간 관측치다. ──
    final_rows: list[dict] = []
    for row, snapshot in zip(pass1_rows, snapshots):
        cp_rate, cp_count = history_agg.counterparty.get(row["counterparty_id"], (None, 0))
        bank_rate, _ = history_agg.bank.get(row["bank_id"], (None, 0))
        cargo_rate, _ = history_agg.cargo_type.get(row["cargo_type"], (None, 0))
        history = HistoryStats(
            counterparty_defect_rate=cp_rate,
            bank_defect_rate=bank_rate,
            cargo_type_defect_rate=cargo_rate,
            counterparty_shipment_count=cp_count,
        )
        snapshot_with_history = replace(snapshot, history=history)
        hist_feats = extract_features(snapshot_with_history, groups=("HISTORY",))
        final_rows.append({**row, **hist_feats})

    ordered_columns = list(META_COLUMNS) + list(FEATURE_NAMES)
    df = pd.DataFrame(final_rows)[ordered_columns]

    return GenerationResult(
        dataframe=df,
        seed=seed,
        base_count=base_count,
        variants_per_base=variants_per_base,
        total_rows=len(df),
        claude_fallback_count=claude_fallback_count,
        llm_backend=config.LLM_FEATURE_BACKEND,
        llm_feature_fallback_count=llm_feature_fallback_count,
    )


def stratified_sample(df: pd.DataFrame, n: int, seed: int, strata_col: str = "y") -> pd.DataFrame:
    """평가셋에서 층화 추출한 검수 표본(설계서 5.6, 기획안 10.3 ⑥ — 200/2,000 = 10%)."""
    if n >= len(df):
        return df.reset_index(drop=True)
    groups = df.groupby(strata_col, group_keys=False)
    total = len(df)
    strata = list(groups.groups.keys())
    parts: list[pd.DataFrame] = []
    allocated = 0
    for i, key in enumerate(strata):
        g = groups.get_group(key)
        if i == len(strata) - 1:
            k = n - allocated
        else:
            k = round(n * len(g) / total)
            allocated += k
        k = max(0, min(k, len(g)))
        if k:
            parts.append(g.sample(n=k, random_state=seed))
    sample = pd.concat(parts) if parts else df.iloc[0:0]
    return sample.sample(frac=1, random_state=seed).reset_index(drop=True)


def make_balanced(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    """50:50 균형 표본(설계서 5.5, 10.3). 다수 클래스를 언더샘플링한다."""
    rng_state = seed
    pos = df[df["y"] == 1]
    neg = df[df["y"] == 0]
    n = min(len(pos), len(neg))
    if n == 0:
        return df.iloc[0:0]
    pos_s = pos.sample(n=n, random_state=rng_state)
    neg_s = neg.sample(n=n, random_state=rng_state)
    return pd.concat([pos_s, neg_s]).sample(frac=1, random_state=rng_state).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 누수 진단 (설계서 1절 "검증 방법")
# ---------------------------------------------------------------------------


def leakage_diagnostics(df: pd.DataFrame) -> dict[str, float]:
    """설계서 1절의 세 가지 진단 지표를 계산한다.

    - phi(y, rv_any_critical) < 0.95 (0.98 이상이면 누수)
    - 룰 미발화(rv_any_critical=0) 건 중 하자 비율 >= 0.10 (룰 밖 하자 존재 증명)
    - 룰 발화(rv_any_critical=1) 건 중 수리 비율 >= 0.10 (오탐 존재 증명)
    """
    y = df["y"].astype(int)
    rv = df["rv_any_critical"].astype(int)

    # 두 이진 변수의 상관계수 = phi coefficient
    phi = float(y.corr(rv)) if rv.nunique() > 1 and y.nunique() > 1 else float("nan")

    no_fire = df[rv == 0]
    defect_rate_when_no_fire = float(no_fire["y"].mean()) if len(no_fire) else float("nan")

    fired = df[rv == 1]
    repair_rate_when_fired = float((1 - fired["y"]).mean()) if len(fired) else float("nan")

    return {
        "phi_y_vs_rv_any_critical": phi,
        "defect_rate_when_rule_silent": defect_rate_when_no_fire,
        "repair_rate_when_rule_fired": repair_rate_when_fired,
        "n_rule_silent": int(len(no_fire)),
        "n_rule_fired": int(len(fired)),
        "overall_defect_rate": float(y.mean()),
    }


# 완전분리 진단 후보 피처 — Group 1(RULE_VIOLATION)과 Group 6(HISTORY)는 제외한다
# (검증자 지적: 이 두 그룹은 룰 밖 하자 그 자체의 "서류상 흔적"이 아니다. 룰 피처는
# 애초에 룰 밖 하자를 못 잡아야 정상이고, 이력 피처는 엔티티 단위 집계라 특정
# 하자 유형과 무관하다 — 둘 다 넣으면 진단이 "이 하자 유형의 흔적이 얼마나
# 강한가"가 아니라 다른 것을 재게 된다).
_SEPARABILITY_EXCLUDED_GROUPS = ("RULE_VIOLATION", "HISTORY")
_SEPARABILITY_CANDIDATE_FEATURES: tuple[str, ...] = tuple(
    f for f in FEATURE_NAMES if feature_group(f) not in _SEPARABILITY_EXCLUDED_GROUPS
)


def separability_diagnostics(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """설계서 1절 신규 진단 — 룰 밖 하자 유형별 단일 피처 최대 AUC + 분포 겹침.

    검증자 지적(v2 결함): 이전 구현은 양성 집합을 "그 유형이 하나라도 섞인 행"으로
    잡았다 — 선적당 하자 1~3건이 같이 주입되므로 양성 행 대부분이 룰 커버 하자를
    동반했고, 82 피처 전체(룰 피처 포함)에서 최대 분리 피처를 찾다 보니 실제로는
    "룰 발화가 같이 있었는가"(`rv_distinct_field_count` 등, 룰 co-occurrence)를
    재고 있었다 — 룰 밖 하자 자신의 서류상 흔적이 아니었다.

    고친 정의: 양성 = 주입된 하자가 **그 유형 하나뿐인** 행(`defect_count==1`,
    `has_covered_defect==False`, `uncovered_defect_types==t`). 음성 = 하자가
    전혀 없는 행(`defect_count==0`). 후보 피처는 `_SEPARABILITY_CANDIDATE_FEATURES`
    — Group 1(RULE_VIOLATION)·Group 6(HISTORY)를 제외한 나머지(DOC_CONSISTENCY·
    EXTRACTION_QUALITY·LC_COMPLEXITY·TIME_MARGIN)뿐이다. 0.85 이상이면 완전분리에
    가깝다는 경고(체크리스트 "룰 밖 하자 유형별 단일 피처 최대 AUC < 0.85"),
    0.95 이상이면 사실상 워터마크다. 분포 겹침은 그 최대 피처의 [min, max] 구간이
    교차하는지로 판단한다.
    """
    if "uncovered_defect_types" not in df.columns:
        return {}

    no_defect_mask = df["defect_count"] == 0
    neg_df = df[no_defect_mask]

    results: dict[str, dict[str, object]] = {}
    for spec in injector.UNCOVERED_SPECS:
        t = spec.type
        only_this_type = (
            (df["defect_count"] == 1)
            & (~df["has_covered_defect"])
            & (df["uncovered_defect_types"] == t)
        )
        pos_df = df[only_this_type]
        if len(pos_df) < 5 or len(neg_df) < 5:
            results[t] = {
                "max_single_feature_auc": float("nan"),
                "max_auc_feature": None,
                "n_defect": int(len(pos_df)),
                "n_no_defect": int(len(neg_df)),
                "distributions_overlap": None,
            }
            continue

        best_auc = 0.0
        best_feature: str | None = None
        for feat in _SEPARABILITY_CANDIDATE_FEATURES:
            pos_vals = pos_df[feat].dropna()
            neg_vals = neg_df[feat].dropna()
            if len(pos_vals) < 5 or len(neg_vals) < 5:
                continue
            combined_x = pd.concat([pos_vals, neg_vals])
            if combined_x.nunique() < 2:
                continue
            combined_y = [1] * len(pos_vals) + [0] * len(neg_vals)
            auc = roc_auc_score(combined_y, combined_x)
            auc = max(auc, 1.0 - auc)  # 방향 무관 분리력
            if auc > best_auc:
                best_auc = auc
                best_feature = feat

        overlap_ok: bool | None = True
        if best_feature is not None:
            pv = pos_df[best_feature].dropna()
            nv = neg_df[best_feature].dropna()
            if len(pv) and len(nv):
                overlap_ok = not (pv.min() > nv.max() or nv.min() > pv.max())
        else:
            overlap_ok = None

        results[t] = {
            "max_single_feature_auc": float(best_auc),
            "max_auc_feature": best_feature,
            "n_defect": int(len(pos_df)),
            "n_no_defect": int(len(neg_df)),
            "distributions_overlap": overlap_ok,
        }
    return results

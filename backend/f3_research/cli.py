"""python -m f3_research.cli <subcommand> (설계서 3절).

subcommand: build-pools | gen-data | train | evaluate
"""

from __future__ import annotations

import argparse
import json
import sys

from f3_research import config


def cmd_build_pools(args: argparse.Namespace) -> None:
    from f3_research.synth import pools

    pool = pools.build_pools(limit=args.limit)
    pools.save_pools(pool)
    print(f"[build-pools] {pool.source_file_count} 개 라벨 파일 처리 완료")
    print(f"[build-pools] 저장 위치: {config.POOLS_FILE}")
    print(
        f"[build-pools] company={len(pool.company_names)} ports={len(pool.ports)} "
        f"vessels={len(pool.vessels)} goods={len(pool.goods)} "
        f"weights={len(pool.weights_kg)} cbm={len(pool.measurements_cbm)} "
        f"amounts={len(pool.amounts_usd)} ref_codes={len(pool.reference_codes)}"
    )


def cmd_gen_data(args: argparse.Namespace) -> None:
    from f3_research import dataset
    from f3_research.synth.pools import load_pools

    pools = load_pools()
    field_accuracy = dataset.load_field_accuracy()

    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"[gen-data] 학습셋 생성 중: base={config.TRAIN_BASE_COUNT} "
        f"variants={config.TRAIN_VARIANTS_PER_BASE} seed={config.TRAIN_SEED}"
    )
    train_result = dataset.generate_dataset(
        seed=config.TRAIN_SEED,
        base_count=config.TRAIN_BASE_COUNT,
        variants_per_base=config.TRAIN_VARIANTS_PER_BASE,
        pools=pools,
        field_accuracy=field_accuracy,
    )
    train_result.dataframe.to_parquet(config.TRAIN_DATASET_FILE, index=False)
    config.TRAIN_MANIFEST_FILE.write_text(
        json.dumps(
            {
                "seed": train_result.seed,
                "base_count": train_result.base_count,
                "variants_per_base": train_result.variants_per_base,
                "total_rows": train_result.total_rows,
                "defect_rate": float(train_result.dataframe["y"].mean()),
                "reviewer_backend": config.REVIEWER_BACKEND,
                "claude_fallback_count": train_result.claude_fallback_count,
                "llm_backend": train_result.llm_backend,
                "llm_feature_fallback_count": train_result.llm_feature_fallback_count,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[gen-data] 학습셋 {train_result.total_rows}건 저장: {config.TRAIN_DATASET_FILE}")

    print(
        f"[gen-data] 평가셋(봉인) 생성 중: base={config.EVAL_BASE_COUNT} "
        f"variants={config.EVAL_VARIANTS_PER_BASE} seed={config.EVAL_SEED}"
    )
    eval_result = dataset.generate_dataset(
        seed=config.EVAL_SEED,
        base_count=config.EVAL_BASE_COUNT,
        variants_per_base=config.EVAL_VARIANTS_PER_BASE,
        pools=pools,
        field_accuracy=field_accuracy,
    )
    eval_result.dataframe.to_parquet(config.EVAL_DATASET_FILE, index=False)
    config.EVAL_MANIFEST_FILE.write_text(
        json.dumps(
            {
                "seed": eval_result.seed,
                "base_count": eval_result.base_count,
                "variants_per_base": eval_result.variants_per_base,
                "total_rows": eval_result.total_rows,
                "defect_rate": float(eval_result.dataframe["y"].mean()),
                "reviewer_backend": config.REVIEWER_BACKEND,
                "claude_fallback_count": eval_result.claude_fallback_count,
                "llm_backend": eval_result.llm_backend,
                "llm_feature_fallback_count": eval_result.llm_feature_fallback_count,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[gen-data] 평가셋(봉인) {eval_result.total_rows}건 저장: {config.EVAL_DATASET_FILE}")

    print(
        f"[gen-data] 검수 표본(층화 추출, {config.REVIEW_SAMPLE_SIZE}건) 생성 중 "
        f"(설계서 5.6, 기획안 10.3 ⑥)"
    )
    review_sample = dataset.stratified_sample(
        eval_result.dataframe, n=config.REVIEW_SAMPLE_SIZE, seed=config.EVAL_SEED
    )
    review_sample.to_parquet(config.REVIEW_SAMPLE_FILE, index=False)
    config.REVIEW_SAMPLE_MANIFEST_FILE.write_text(
        json.dumps(
            {
                "source_eval_seed": config.EVAL_SEED,
                "sample_size": int(len(review_sample)),
                "eval_total_rows": eval_result.total_rows,
                "sample_fraction": round(len(review_sample) / max(eval_result.total_rows, 1), 4),
                "defect_rate": float(review_sample["y"].mean()) if len(review_sample) else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[gen-data] 검수 표본 {len(review_sample)}건 저장: {config.REVIEW_SAMPLE_FILE}")

    from f3_research import dataset as dataset_module

    diag = dataset_module.leakage_diagnostics(train_result.dataframe)
    print("[gen-data] 누수 진단(학습셋):")
    print(json.dumps(diag, indent=2))

    sep_diag = dataset_module.separability_diagnostics(train_result.dataframe)
    print("[gen-data] 룰 밖 하자 유형별 단일 피처 분리력 진단(학습셋, 설계서 1절 신규):")
    print(json.dumps(sep_diag, indent=2))

    eval_sep_diag = dataset_module.separability_diagnostics(eval_result.dataframe)
    print("[gen-data] 룰 밖 하자 유형별 단일 피처 분리력 진단(봉인 평가셋, 설계서 1절 신규):")
    print(json.dumps(eval_sep_diag, indent=2))


def cmd_train(args: argparse.Namespace) -> None:
    from f3_research.train import run_training

    results = run_training(register=args.register, note=args.note)
    print("=== 평가 결과 (설계서 6.4: 3조건 × 2비율) ===")
    print(json.dumps(results["conditions"], indent=2))
    print("=== 성공 판정 ===")
    print(json.dumps(results["success"], indent=2))
    print(f"모델 버전: {results['model_version']}")
    print(f"아티팩트: {config.ARTIFACTS_DIR / results['model_version']}")
    if not results["success"]["passed"]:
        print("경고: 성공 판정 기준(결합 F1 >= 0.85 AND 결합 > 룰 단독)을 충족하지 못했습니다.")


def _build_llm_pilot_items(n: int, seed: int) -> list[tuple[str, str]]:
    """gen-data 파이프라인(dataset.py `generate_dataset` pass 1a)과 같은 방식으로
    N건의 (shipment_id, 관측값 문서 텍스트)를 만든다 — Gemini 도 룰엔진과 같은
    **관측값**(OCR 훼손 사본)을 봐야 하기 때문이다(render.py 모듈 docstring,
    HANDOFF.md 불변식 1). HISTORY·룰엔진·라벨은 파일럿에 필요 없으므로 뺀다."""
    import random

    from f3_research import dataset
    from f3_research.render import render_document_set
    from f3_research.synth import generator, injector
    from f3_research.synth.extraction_view import extraction_view
    from f3_research.synth.pools import load_pools

    value_pools = load_pools()
    field_accuracy = dataset.load_field_accuracy()
    gen_rng = random.Random(seed)
    params = generator.GeneratorParams(seed=seed, base_count=n)
    entities = generator.build_entity_pools(value_pools, params, gen_rng)
    base_shipments = generator.generate_base_shipments(value_pools, entities, params, field_accuracy)

    items: list[tuple[str, str]] = []
    for base_idx, base in enumerate(base_shipments):
        injector_rng = random.Random(dataset._derive_seed(seed, base_idx, 0, "injector"))
        rule_rng = random.Random(dataset._derive_seed(seed, base_idx, 0, "rule"))
        variant = base.copy()
        variant.shipment_id = f"{base.base_shipment_id}-v0"
        mutated, _defects = injector.inject_defects(variant, injector_rng)
        observed = extraction_view(mutated, rule_rng)
        items.append((mutated.shipment_id, render_document_set(observed)))
    return items


def cmd_llm_pilot(args: argparse.Namespace) -> None:
    """Gemini 백엔드 파일럿(계획서 10단계 Task 5). 전체 데이터셋을 재생성하지
    않는다 — `--limit` 건만 실측하고 토큰·비용·불일치를 보고한다."""
    import math

    from f3_research import llm_features

    limit = args.limit
    print(f"[llm-pilot] Gemini 백엔드 파일럿 실행: limit={limit}, model={config.GEMINI_FEATURE_MODEL}")

    items = _build_llm_pilot_items(limit, seed=config.TRAIN_SEED)

    report = llm_features.run_gemini_pilot(items)

    print(
        f"[llm-pilot] 총 {report.total}건 — 성공 {report.successes} / "
        f"폴백(offline) {report.fallbacks} / 캐시히트 {report.cache_hits}"
    )
    print(f"[llm-pilot] 재시도 총 {report.retries_total}회")
    print(
        f"[llm-pilot] 입력 토큰 {report.total_input_tokens} / "
        f"출력 토큰 {report.total_output_tokens}"
    )
    print(
        f"[llm-pilot] 소요 {report.wall_clock_seconds:.2f}초, "
        f"관측 RPM {report.observed_rpm:.1f} (한도 {config.GEMINI_RPM_LIMIT})"
    )
    print(f"[llm-pilot] model_version 관측값: {report.model_versions}")
    print(f"[llm-pilot] 예상 비용(유료 환산): ${report.estimated_cost_usd():.4f}")
    if report.errors:
        print(f"[llm-pilot] 오류(최종 실패분, {len(report.errors)}건): {report.errors}")

    # offline vs gemini 불일치 — 이 실험의 존재 이유를 뒷받침하는 초기 신호
    # (계획서 10단계 "Gemini 가 실제로 다른 말을 하는지"). 캐시를 그대로
    # 재사용하므로 API 를 다시 부르지 않는다.
    offline_by_id, _ = llm_features.compute_features_batch(items, backend="offline")
    gemini_by_id, _ = llm_features.compute_features_batch(items, backend="gemini")
    print("[llm-pilot] offline vs gemini 불일치(피처별, 결측 제외 비교):")
    from f3_research.schema import LLMFeatures

    for name in LLMFeatures.__dataclass_fields__:
        compared = 0
        disagree = 0
        for shipment_id, _ in items:
            off = getattr(offline_by_id.get(shipment_id), name, None)
            gem = getattr(gemini_by_id.get(shipment_id), name, None)
            if off is None or gem is None:
                continue
            if isinstance(off, float) and math.isnan(off):
                continue
            if isinstance(gem, float) and math.isnan(gem):
                continue
            compared += 1
            if abs(float(off) - float(gem)) > 1e-9:
                disagree += 1
        print(f"    {name}: {disagree}/{compared} 건 불일치")


def cmd_evaluate(args: argparse.Namespace) -> None:
    version_dir = config.ARTIFACTS_DIR / args.version if args.version else None
    if version_dir is None:
        candidates = sorted(config.ARTIFACTS_DIR.glob("*"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print("아티팩트가 없습니다. 먼저 `train` 을 실행하세요.", file=sys.stderr)
            sys.exit(1)
        version_dir = candidates[-1]
    metrics_path = version_dir / "metrics.json"
    if not metrics_path.exists():
        print(f"{metrics_path} 를 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)
    print(metrics_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m f3_research.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pools = sub.add_parser("build-pools", help="AI Hub 라벨 → 값 분포 풀")
    p_pools.add_argument("--limit", type=int, default=None)
    p_pools.set_defaults(func=cmd_build_pools)

    p_gen = sub.add_parser("gen-data", help="합성 학습셋(3,000)·평가셋(2,000, 봉인)·검수표본(200) 생성")
    p_gen.set_defaults(func=cmd_gen_data)

    p_train = sub.add_parser("train", help="분할→학습→보정→평가→아티팩트")
    p_train.add_argument("--register", action="store_true", help="model_version 테이블에 등록(DB 필요)")
    p_train.add_argument("--note", type=str, default=None)
    p_train.set_defaults(func=cmd_train)

    p_eval = sub.add_parser("evaluate", help="저장된 아티팩트의 metrics.json 출력")
    p_eval.add_argument("--version", type=str, default=None)
    p_eval.set_defaults(func=cmd_evaluate)

    p_llm_pilot = sub.add_parser(
        "llm-pilot", help="Gemini 백엔드 파일럿(계획서 10단계) — 실측 호출, 전체 데이터셋 생성 아님"
    )
    p_llm_pilot.add_argument("--limit", type=int, default=20, help="실행할 선적 건수")
    p_llm_pilot.set_defaults(func=cmd_llm_pilot)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

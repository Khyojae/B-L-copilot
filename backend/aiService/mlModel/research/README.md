# F3 계층 B — 하자 확률 예측 모델 (XGBoost)

설계서: `docs/F3_예측모델_설계.md`. 이 디렉토리 하나로 자기완결적으로 동작한다
(`src/smart_e_bl/` 는 `registry.py` 만 `--register` 사용 시 지연 import 한다).

## 설치

```bash
uv sync --extra ml
```

## 실행 순서

```bash
# 1) AI Hub 선하증권 라벨(4,000건) → 값 분포 풀 (1회, 캐시됨)
python -m f3_research.cli build-pools

# 2) 합성 학습셋(3,000건, seed=42) + 봉인 평가셋(2,000건, seed=20260814)
#    + 검수 표본(평가셋에서 층화 추출 200건) 생성
python -m f3_research.cli gen-data

# 3) 분할 → 학습 → 보정 → 평가 → 아티팩트
python -m f3_research.cli train
#   DB 에 model_version 을 등록하고 조건부 활성화하려면:
python -m f3_research.cli train --register --note "설명"

# 4) 저장된 아티팩트의 metrics.json 재출력
python -m f3_research.cli evaluate [--version fs-1-YYYYMMDD-xxxxxx]

# 테스트
pytest ai/f3_research/tests/
```

`AI_HUB_BL_LABEL_DIR` 환경변수로 AI Hub 라벨 경로를(로컬 전용) 덮어쓸 수 있다.
기본값은 `/Users/ethanyang/Documents/B_L_model/Sample Data/.../TL_물류_3.선하증권_BL01`.

## 산출물 위치

```
ai/f3_research/data/
  pools/value_pools.json                        # build-pools 산출물
  datasets/train_3000.parquet                   # gen-data 산출물(학습)
  datasets/eval_sealed_2000.parquet              # gen-data 산출물(봉인 평가셋 — train.py 는 읽지 않는다*)
  datasets/eval_review_sample_200.parquet        # 평가셋에서 층화 추출한 검수 표본(설계서 5.6, 10.3 ⑥)
  datasets/*.manifest.json                       # 생성 시드·행 수·reviewer_backend·claude_fallback_count
  reviews/claude_reviews.jsonl                   # claude 백엔드 판정 캐시 — 저장소에 커밋한다(아래 참고)
  artifacts/{version}/
    model.ubj              # 결합(82피처) 부스터. pickle 아님(설계서 6.5)
    calibrator.joblib      # sigmoid(Platt) 보정기 — raw_score(스칼라) 만 입력으로 받는다
    feature_names.json     # FEATURE_SCHEMA_VERSION + 컬럼 순서 + best_threshold
    metrics.json            # 3조건(룰단독/모델단독/결합) × 2비율(자연/균형) 평가표(부트스트랩 95% CI 포함)
                             # + 누수/분리력 진단 + min_child_weight 민감도 표 + 성공 판정
    calibration_curve.png  # 10구간 신뢰도 다이어그램(평가셋, 자연 비율)
    dataset_manifest.json  # 학습·평가 데이터셋 시드/규모 요약
```

\* `train.py` 는 평가(test) 목적으로만 `eval_sealed_2000.parquet` 을 읽는다 — 학습·보정·임계값
튜닝에는 절대 쓰지 않는다(임계값 튜닝·min_child_weight 스윕은 학습셋 내 validation 분할로 한다).

`ai/f3_research/data/` 는 기본적으로 `.gitignore` 대상이다(생성물이므로 저장소에 커밋하지
않는다). **예외: `data/reviews/`** — claude 백엔드 판정 캐시는 재현성 아티팩트이므로
저장소에 커밋한다(설계서 5.5: "제3자는 키 없이 동일 데이터셋을 재생성할 수 있다").

## 라벨 누수 차단 (가장 중요한 불변식)

`synth/rule_sim.py`(채널 A, 피처)와 `synth/review.py`(채널 B, 라벨)는 서로 import 하지
않는다. 둘 다 `injected_defects[]` 를 독립적으로 읽어 각자 다른 노이즈 모델로
판정한다. `ai/f3_research/tests/test_no_leakage.py` 가 이 불변식과 설계서 1절의
진단 임계값(phi < 0.95, 룰 미발화 시 하자 비율 ≥ 0.10, 룰 발화 시 수리 비율 ≥ 0.10,
**룰 밖 하자 유형별 단일 피처 최대 AUC < 0.85, 무하자/하자 분포 겹침**)을 검사한다.

## 채널 B 백엔드 (설계서 5.5)

`config.REVIEWER_BACKEND`(환경변수 `DEFECT_MODEL_REVIEWER_BACKEND` 로 덮어쓸 수 있음)로
`constant_table`(기본값, 오프라인) / `claude`(Batches API, 논문용) 를 고른다.

- `claude` 백엔드는 `injected_defects`/`covered_by_rule`/룰 코드를 **절대 프롬프트에
  넣지 않는다** — 렌더링된 서류 세트(B/L·L/C·송장·포장명세서)만 보고 UCP600/ISBP
  관점에서 판정한다(`synth/review.py::render_document_set`). 구조적 출력
  (`{verdict, reasons, confidence}`)을 강제하고, 실패·거부·스키마 위반은 재시도
  2회 후 `constant_table` 로 폴백하며 폴백 건수를 데이터셋 매니페스트에 기록한다.
- 이 저장소 환경에는 `ANTHROPIC_API_KEY` 가 없다 — 그래서 기본값은 `constant_table`
  이며, `claude` 를 선택했는데 키가 없으면 명확한 `RuntimeError` 로 즉시 실패한다.
  `tests/test_review_claude.py` 가 claude 백엔드 로직 전체(프롬프트 구성·캐시·
  구조적 출력 파싱·재시도/폴백)를 mocked client 로 검증한다 — 실제 API 는 호출하지 않는다.

## 하이퍼파라미터 민감도 (검증자 지적 반영)

독립 검증에서 `min_child_weight=5`(설계서 6.2 예시값) 는 결합 F1 0.613으로 룰 단독
(0.798)보다 낮았다 — 결과가 그 값 근처에서만 성립하는 취약한 설정이었다. `train.py`
가 학습 때마다 학습셋 내 validation holdout(봉인 평가셋 아님)에서
`config.MCW_SWEEP_VALUES` 를 스윕해 `metrics.json::mcw_sensitivity` 에 그 취약성을
그대로 기록한다 — 숨기지 않는다. `config.py::XGB_PARAMS` 의 `min_child_weight` 는
이 스윕 결과에 맞춰 선택한 값이다(자세한 근거는 `config.py` 주석 참고).

## 알려진 제약

- `synth/rule_sim.py` 는 실제 룰엔진이 없는 현재 단계의 임시 대역이다(설계서 5.4,
  11절 8단계). 룰엔진이 완성되면 동일 출력 타입의 어댑터로 교체한다.
- `registry.py` 는 `smart_e_bl` ORM 을 지연 import 한다 — DB 가 없는 환경에서도
  `train`(register 없이)까지는 정상 동작한다.
- `claude` 백엔드를 쓰면 모델이 학습하는 것은 "은행의 판정"이 아니라 **"Claude 의
  판정"**이다 — 성능 상한이 Claude 의 무역서류 이해도가 된다. 논문 기술 시 이
  한계를 데이터셋 구성과 함께 명시해야 한다(설계서 5.5).

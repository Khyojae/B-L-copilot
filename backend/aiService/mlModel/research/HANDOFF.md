# F3 하이브리드 — 인계 문서

> **새 세션은 이 문서를 먼저 읽는다.** 설계 *근거*는 `docs/F3_예측모델_설계.md`,
> 진행 *상태*는 이 문서. 계획서는 `~/.claude/plans/xgboost-rule-async-kahn.md`.
>
> 최종 갱신: 2026-08-16 · 9단계 완료

---

## 1. 지금 어디까지 왔나

**현재 단계: 9 완료, 10단계(Gemini 백엔드) 착수 전** · 테스트 **121 통과**

| 단계 | 상태 |
|---|---|
| — fs-1 결과 보존 | ✅ `docs/artifacts_fs1/` (data/는 gitignore라 재생성하면 소실됨) |
| 0 의존성 + conftest | ✅ pyyaml 6.0.3 / google-genai 2.18.1 선언. `tests/conftest.py` autouse 픽스처 + `test_backend_defaults.py` |
| 1 룰엔진 테스트 | ✅ `tests/test_rule_engine.py` 23개. **돌연변이 검사로 안전망 작동 확인** |
| 2 rule_adapter | ✅ `rule_adapter.py` + `tests/test_rule_adapter.py` 7개. **돌연변이 검사 통과** |
| 3 fs-2 스키마 범프 | ✅ `schema.py`/`features.py` 82→74, `RuleFiringV2`→`RuleFiring`(구 버전 삭제), `rule_sim.py` 는 실제 카탈로그 값을 쓰는 임시 시뮬레이터로 축소(5단계에서 파일째 삭제 예정). 테스트 82개 그린, `gen-data` 성공(§4 참고) |
| 4a 생성기 필드 12개 추가 | ✅ 깨끗한 선적 평가 룰 **19.1/21**(전 11 skip → 평균 1.9), **위반 0건**. `bl_no`·`lc_port_of_loading` 등 |
| 5 실제 엔진 배선 + 관측 노이즈 + rule_sim 삭제 | ✅ `synth/extraction_view.py` 신설, `rule_sim.py` **삭제**, `dataset.py` 가 관측값 위에서 실제 엔진 실행. 삼진 피처가 처음으로 작동(`rv_skipped_count` 고유값 7, 이전 상수 0) |
| 6 정적 독립성 테스트 복원 | ✅ **v3부터 반쯤 공허했던 것을 발견·수정** — 아래 3절 참고 |
| 4b 인젝터 재정렬 **[최난도]** | ✅ `COVERED_SPECS`/`UNCOVERED_SPECS` 재편(설계서 §5.3.1), `DefectSpec.target_rule` 추가, `tests/test_injector_alignment.py` 21개 신설. **아래 "4b 단계 직후 진단"이 결과다** |
| 7 fs-2 베이스라인 (LLM 없이) | ✅ `fs-2-20260816-24d9c4`. **절제 실험에서 재설계 목표 달성 확인** — 4절 참고. 아티팩트는 `docs/artifacts_fs2/` 에 보존(data/ 는 gitignore) |
| 8 LLM 피처 골격 (offline) | ✅ `llm_features.py` — offline 백엔드, 채널 독립 가드(`check_channel_independence`), `tests/test_llm_features.py`. (이 표가 9단계 착수 시점까지 갱신되지 않아 ⬜로 남아 있었다 — 실제로는 이미 완료 상태였다) |
| 9 47A 풀 분할 **[워터마크 위험]** | ✅ `LC_47A_VERIFIABLE_POOL`/`LC_47A_UNVERIFIABLE_POOL`(`synth/generator.py`) + `sample_47a_conditions()` 공유 샘플러(무하자 0.0~0.6, 하자 0.3~0.9, `injector.FREEFORM_47A_UNVERIFIABLE_RATIO_RANGE`) + 언어적 단서 분류기(`llm_features._is_unverifiable_47a_condition`, 풀 소속 미참조, 참 라벨 대비 정확도 0.828). **아래 "9단계 직후 진단"이 결과다** |
| 10 Gemini 백엔드 | 🔄 키 확보·스모크 통과. 아래 실측 참고 |

### 10단계 실측 (스모크 테스트 1건, `gemini-3.7-flash`)

`client.models.list()` 53개 조회 성공 — **`gemini-3.7-flash` 실존 확인**(문서를 믿지 않고 조회함).

| 항목 | 실측 |
|---|---|
| 렌더링 문서 | 1,333자 |
| 입력 토큰 | **628** |
| 출력 토큰 | **109** |
| 지연 | **2.5초** |
| 재시도 | 첫 시도 **503 UNAVAILABLE** → 1초 백오프 후 성공 |

**503 은 예외가 아니라 상시 발생한다.** 백오프·재시도는 선택이 아니라 필수.

**비용**: 무료 등급이면 0원. 유료 환산 시 건당 약 $0.00088
(628×$0.75/M + 109×$3.75/M) → 5,000건 **약 $4.40**. 설계서가 Claude Opus 기준으로
적어 둔 $50~240 은 무효 — 출력이 1/4(109 vs 400)이고 flash 단가가 훨씬 낮다.

**주의**: `response_schema` 에 Pydantic 모델을 넘기면 SDK 가 automatic function
calling 경로로 들어가며 경고를 낸다. dict 스키마를 쓰면 깔끔하다.

### 🚨 10단계 하드 블로커 — 무료 등급 일일 한도

20건 파일럿 실행 결과: **성공 1 / 캐시히트 7 / 폴백 12**, 재시도 36회, 288초.
실패 12건 전부 429:

```
quotaId:    GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue: 20
```

**무료 등급은 모델당 하루 20건이다** (분당이 아니라 **하루**).
5,000건 ÷ 20 = **250일**. 현 구성으로 전체 데이터셋 생성은 불가능하다.

한도는 **모델별로 따로** 잡힌다(`PerProjectPerModel`). 실측 가용 모델:
`gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite` (3.5-flash 는 503,
2.5 계열은 404). 3개를 돌려 써도 하루 60건 → 83일. 역시 불가능.

**→ 결론: 유료 등급 활성화(전체 약 $4.40)가 유일하게 현실적인 경로다.**
비용이 아니라 무료 등급의 일일 한도가 블로커다.

### 파일럿의 유의미한 소득 — Gemini 는 휴리스틱과 실제로 다르게 말한다

`offline` vs `gemini` 불일치(결측 제외):

| 피처 | 불일치 |
|---|---|
| `goods_semantic_equiv` | **8/20** |
| `goods_invoice_semantic_equiv` | **8/20** |
| `doc_conflict_count` | **7/20** |
| `lc_complexity_score` | **7/19** |
| `verifiable_47a_ratio` | 2/19 |
| `party_semantic_equiv_min` | 2/20 |

의미 동등성·충돌 판단에서 40% 안팎이 갈린다 — **Gemini 투자를 정당화할 신호가
실재한다는 초기 근거**다. 다만 이게 *더 나은* 값인지는 11단계의
`combined − combined_no_llm` 로만 판정할 수 있다.

### 10단계에서 고친 결함

| 결함 | 내용 |
|---|---|
| **캐시가 24.7MB 로 비대** | `offline` 백엔드가 결과를 캐시에 쓰고 있었다(80,163건, Gemini 는 7건). 캐시는 **비싼 호출의 재현성 아티팩트**인데 결정론적 휴리스틱 결과로 뒤덮였다. offline 경로의 캐시 쓰기를 제거(명시적으로 cache 인자를 넘긴 테스트만 예외)하고 Gemini 레코드만 남겨 **4KB** 로 정리 |
| **레코드에 출처 표기 없음** | 캐시 키 해시에는 백엔드가 들어 있지만 파일을 눈으로 봐서는 알 수 없었다. Gemini 레코드에 `backend` 필드를 명시하도록 수정 |
| 11 6조건 평가 | ⬜ |
| 12 추론 경로 | ⬜ |

### 9단계 직후 진단 (47A 풀 분할) — 목표 달성

`llm_47a_verifiable_ratio`/`llm_47a_unverifiable_count` 가 처음으로 NaN 이 아닌 값을
낸다. 룰 밖 하자 유형별 단일 피처 최대 AUC(설계서 1절 신규 진단, `train_3000`/
`eval_sealed_2000`, seed=42/20260814):

| type | train | eval | train 최대 피처 | eval 최대 피처 |
|---|---|---|---|---|
| `goods_wording_diff` | 0.805 | 0.809 | `llm_goods_invoice_semantic_equiv` | `llm_goods_invoice_semantic_equiv` |
| `qty_sum_mismatch` | 0.842 | 0.761 | `dc_qty_deviation_ratio` | `dc_qty_deviation_ratio` |
| `weight_sum_mismatch` | 0.772 | 0.825 | `dc_weight_deviation_ratio` | `dc_weight_deviation_ratio` |
| **`freeform_47a_unmet`** | **0.703** | **0.780** | `llm_47a_verifiable_ratio` | `llm_47a_unverifiable_count` |
| `invoice_amount_mismatch` | 0.636 | 0.810 | `dc_amount_deviation_ratio` | `dc_amount_deviation_ratio` |
| `invoice_consignee_mismatch` | 0.726 | 0.772 | `llm_party_semantic_equiv_min` | `tm_days_to_expiry` |
| `customary_wording_missing` | 0.711 | 0.662 | `dc_conflict_field_count` | `dc_conflict_field_count` |
| `insufficient_originals` | 0.648 | 0.657 | `dc_weight_deviation_ratio` | `tm_presentation_period_remaining_ratio` |
| `signer_authority_ambiguous` | 0.647 | 0.620 | `eq_recommend_check_count` | `dc_mean_edit_distance_ratio` |

전부 **< 0.85, 분포 겹침 확인**. `freeform_47a_unmet` 은 v3(0.730)·8단계 직전 관찰값
(0.730/—)에서 크게 벗어나지 않았고, 이번 단계 전까지 무정보였던
`llm_47a_verifiable_ratio`/`llm_47a_unverifiable_count` 가 최대 분리 피처로
처음 등장했다 — 47A 풀 분할이 의도한 신호를 실제로 만든다는 뜻이다.

**분류기 정확도(참 라벨=풀 소속 대비)**: **0.828** (24/29 조건 문구). `tests/test_llm_features.py::test_47a_classifier_accuracy_is_meaningfully_below_oracle`
가 이 값을 0.95 미만·0.5 초과로 묶어 둔다 — 오라클(1.000)도, 무정보(0.5)도 아니다.

**측정된(분류기) 검증불가 비율 분포** (`train_3000`, L/C 있는 행만):

| 구분 | n | min | max | mean |
|---|---|---|---|---|
| 무하자(`defect_count==0`) | 287 | 0.000 | 1.000 | 0.497 |
| `freeform_47a_unmet` 단독 | 30 | 0.333 | 1.000 | 0.728 |

**생성 시 참 비율 분포**(사후 검증용, 풀 소속 기준 — 모델은 이 값을 절대 보지 않는다.
`sample_47a_conditions()` 를 2,000회 직접 호출해 계산):

| 구분 | min | max | mean |
|---|---|---|---|
| 무하자(범위 0.0~0.6) | 0.000 | 1.000 | 0.271 |
| 하자(범위 0.3~0.9) | 0.000 | 1.000 | 0.621 |

(min/max 가 양쪽 다 0~1인 것은 조건 개수가 1~6개로 적어 개수가 작을 때 반올림이
0 또는 1로 쏠리는 양자화 효과다 — 평균이 설계 범위 중앙값(0.3/0.6)에 가깝다는 게
핵심 증거다.) 측정치(분류기)는 참값보다 평균이 더 벌어져 있다(0.497 vs 0.271,
0.728 vs 0.621) — 분류기가 "단서 없음→검증불가" 기본값을 쓰기 때문에 계통적으로
검증불가 쪽으로 치우치지만(§5.3.2가 요구하는 "틀리는" 분류기), 두 구분 모두
같은 방향으로 치우쳐 순서(무하자 < 하자)는 보존된다.

**되돌리지는 않았지만 기록해 둘 whack-a-mole**: 47A 샘플링 로직 교체가 공용 RNG
스트림의 소비 패턴을 바꿔(호출 횟수가 달라짐), 47A 와 무관한 `goods_wording_diff`
축(품명 표기 변동)의 단일 피처 AUC 가 학습셋 0.845→0.857 로 0.85 를 넘었다
(`llm_goods_invoice_semantic_equiv`). **하자를 약화하지 않고**(injector 의
`_apply_goods_wording_diff` ratio_range 0.15~0.55 는 손대지 않음) 무하자 쪽
`invoice_goods_desc` 변동 상한만 0.30→0.34 로 넓혀 0.805(학습)/0.809(평가) 로
되돌렸다(`synth/generator.py` `_build_shipment`). `qty_sum_mismatch`/
`weight_sum_mismatch`/`invoice_amount_mismatch` 는 같은 RNG 흔들림에 스치긴
했지만 0.85 를 넘지 않아 손대지 않았다(qty 학습셋 0.842 는 원래 기준값 0.841과
사실상 동일 — 이번 단계 전부터 있던 여유임).

### ⚠️ 구조적 취약점 — 분리력 여유가 전반적으로 얇다

9단계에서 드러난 것: **47A 샘플링 로직만 바꿨는데 무관한 `goods_wording_diff` 축이
0.845 → 0.857 로 문턱을 넘었다.** 인과관계가 아니라 **공용 RNG 스트림의 소비 패턴이
바뀐 탓**이다. 즉 현재 분리력 수치들은 상당 부분 **표집 노이즈** 위에 앉아 있다.

현재 0.80 을 넘는 유형이 학습·평가 합쳐 5종이고, 문턱까지 여유가 0.01~0.05다.
**앞으로 생성기·인젝터를 건드리는 모든 변경은 무관해 보여도 이 진단을 다시 돌려야 한다.**

근본 대응 후보(아직 미적용, 11단계 이후 판단):
- 진단을 여러 시드에서 돌려 평균·분산으로 보고 (단일 시드 점추정은 노이즈)
- 진단 표본이 유형당 27~75건으로 작다 — 신뢰구간을 붙이면 실제 여유가 보인다

### 4b 단계 직후 진단 (인젝터 재정렬 후) — 목표 달성

```
phi(y, rv_any_critical)        0.257   ← 재정렬 전 0.074 (5단계 직후, 아래 참고)
defect_rate_when_rule_silent   0.534   (하한 0.10 ✓)
repair_rate_when_rule_fired    0.189   (하한 0.10 ✓)
overall_defect_rate            0.756
```
(출처: `train_3000.parquet`, seed=42, base=1000×3. 봉인 평가셋 2,000건도 유사:
phi=0.298, defect_rate_silent=0.485, repair_rate_fired=0.190, overall=0.745.)

**한 번도 발화하지 않는 룰은 이제 카탈로그 21개 중 5개뿐**(전 10개) —
`D007B D013 D014 D015 D016`, 전부 설계서 §5.3.1이 "룰 커버 하자 목표에서
의도적으로 제외"라고 명시한 것과 정확히 일치한다(측정 한계·드문 금지조건·
info 등급). 나머지 16개는 전부 발화한다. `D010`(통지처 누락)·`D011`(선박명
누락)도 `required_field_missing` 이 7개 필드 중 하나를 무작위로 비우는 방식이라
발화 건수가 적다(33/402건).

**되돌린 시도(3절에 추가할 것과 같은 패턴, 개발 중 자체 발견·수정)**: 룰 밖 신규
5종 중 `invoice_amount_mismatch`(dc_amount_deviation_ratio AUC 0.929)와
`invoice_consignee_mismatch`(구 코드가 `" (TRADING DIV.)"` 를 100% 확률로 붙여
dc_party_name_mismatch_count AUC 0.970)가 초판에서 0.85 문턱을 넘었다. 전자는
`generator.natural_deviation_ratio` 의 `base_hi`/`extra_hi` 를 조정해, 후자는
고정 문자열을 50% 확률의 `vary_wording` 이동으로 바꿔 고쳤다(자세한 내용은
`synth/injector.py`/`synth/generator.py` 주석 참고). 최종 수치(학습셋 seed=42
기준, 전부 0.85 미만·분포 겹침 확인됨)는 `python -m f3_research.cli gen-data`
출력의 "룰 밖 하자 유형별 단일 피처 분리력 진단" 참고.

### 5단계 직후 진단 (인젝터 재정렬 전, 역사적 기록) — 4b가 고친 것

```
phi(y, rv_any_critical)        0.074   ← fs-1 0.441, 시뮬레이터 0.232 에서 붕괴
defect_rate_when_rule_silent   0.655   (하한 0.10 ✓)
repair_rate_when_rule_fired    0.277   (하한 0.10 ✓ — 여유 커짐)
overall_defect_rate            0.692
```

**phi 0.074 = 룰 발화가 라벨과 거의 무상관.** 지금 발화의 대부분이 실제 하자가 아니라
**OCR 관측 노이즈** 때문이다. 인젝터가 주입하는 하자를 엔진이 대부분 못 보기 때문
(§5 참고). 계획서 R6이 예측한 "엉뚱한 이유로 붕괴"가 실제로 일어났다.

**한 번도 발화하지 않는 룰 10개**: `D006 D007B D008 D010 D011 D013 D014 D015 D016 D017`

- `D008`(유효기간)은 `expiry_exceeded` 를 주입해도 안 터진다 — 인젝터가 `onboard_date`
  를 바꾸는데 D008 은 `date_of_issue` 를 본다(설계서 §5.3.1 표가 지적한 그대로).
- `D013/D014`는 L/C 가 실제로 금지할 때만 평가된다 — 판정불가 1869/2181 건은 정상.

**마지막으로 전체 검증을 통과한 지점**: fs-1, 아티팩트 `fs-1-20260814-00bc3e`, 45/45 테스트.

---

## 2. 협상 불가 불변식

이 프로젝트는 3회의 적대적 검증에서 **미묘한 라벨 누수를 세 번** 발견했다. 아래는 전부
그 결과로 생긴 방어선이다. **완화하지 말 것.**

1. **채널 독립.** 피처(채널 A: 룰엔진 + LLM)와 라벨(채널 B: `review.py`)은 서로를 참조하지
   않는다. `review.py`는 룰 관련 모듈을 import 하지 않는다.
2. **LLM은 피처와 라벨을 동시에 만들지 않는다.** 같은 모델 계열이 양쪽을 만들면 상위 잠재변수를
   공유해 누수가 되고, **기존 테스트가 이걸 못 잡는다.** 코드로 동시 활성을 금지한다.
3. **워터마크 금지.** 하자에만 등장하는 고정 문자열, 자연 분포 최솟값 아래로의 클램프,
   하자 유형과 1:1 대응하는 플래그 필드. 룰 밖 하자의 단일 피처 AUC는 **0.85 미만**이어야 하고
   무하자/하자 분포가 각 축에서 **겹쳐야** 한다.
4. **HISTORY는 데이터셋 밖에서 온다.** 별도 과거 기간에서 계산하며, 어떤 형태의 타깃 인코딩
   (LOO / leave-group-out / out-of-fold)도 금지.
5. **백엔드 기본값은 오프라인.** `REVIEWER_BACKEND="constant_table"`,
   `LLM_FEATURE_BACKEND="offline"`. 테스트가 유료 호출을 하면 안 된다.
6. **성공 판정은 신뢰구간 하한 기준.** 점추정이 0.85를 넘어도 하한이 미달이면 "달성" 아님.

---

## 3. 되돌린 시도와 그 이유 (같은 함정 재방문 금지)

| 시도 | 왜 되돌렸나 |
|---|---|
| 인젝터가 룰 밖 하자에 OCR 신뢰도 0.35 클램프 | "약한 상관"이라 기록됐으나 **실측 단일 피처 AUC 1.000** — 자연 분포 최솟값(0.394) 아래로 클램프한 결정론적 워터마크였다. 제거해도 결합 F1 불변(0.856), model_only는 오히려 개선 |
| `:47A:` 하자에 전용 고정 문자열 2개 추가 | `lc_47a_char_length` AUC 1.000 (하자 최소 342자 vs 무하자 최대 268자, 중첩 0) |
| 품명 하자에 `"REPACKED GRADE B ALT SPEC"` 추가 | `dc_max_edit_distance_ratio` AUC 1.000 (0.72 vs 0.05) |
| HISTORY를 leave-base-out 타깃 인코딩으로 계산 | 자기 라벨의 LOO 인코딩. 평가셋 라벨을 **한 줄 디코더로 AUC 1.000 복원** 가능. 학습 홀드아웃 0.894 vs 평가셋 0.687 격차의 전원인이었고, **"결합 < 룰 단독"이라는 결론 자체가 이 버그의 산물**이었다 |
| `min_child_weight=50` 선택 | 위 누수 상태의 홀드아웃에서 고른 값. 누수 제거 후 재측정하니 스윕이 **평평**했고(mcw 1~75에서 AUC 0.803~0.814) 원래의 "단조 감소" 서사는 전부 누수 암기였다 |
| LLM 피처 테스트를 **손으로 쓴 문서 문자열**로 작성 | 렌더 형식(섹션 헤더·필드 라벨)과 달라 파서가 **전 필드 None** 을 냈는데, 결정론·순서무관·캐시 검사가 **전부 통과했다**(전부 None 이면 자명하게 성립). "무언가를 실제로 뽑았다"를 명시 검사하지 않으면 스위트가 통째로 공허해진다. → 픽스처를 **실제 `render_document_set` 출력**으로 바꾸고 `test_offline_backend_actually_extracts_something` 추가 |
| **채널 독립성 정적 테스트(`_imported_module_names`)** | **v3부터 반쯤 공허했다.** `ast.ImportFrom` 에서 `node.module` 만 담고 import 한 *이름*은 안 담아서, `from f3_research import rule_adapter` 형태가 **통째로 안 보였다.** 프로젝트에서 가장 중요하다고 문서에 적어 둔 테스트가 정작 절반을 못 막고 있었다. 돌연변이 검사(일부러 import 추가 → 실패해야 함)를 돌려서야 발견. **교훈: 테스트를 새로 쓰거나 고칠 때마다 돌연변이 검사로 비공허성을 증명한다.** |

---

## 4. 최신 측정 — fs-2 (7단계, LLM 없이)

출처: `ai/f3_research/data/artifacts/fs-2-20260816-24d9c4/metrics.json` · 봉인 평가셋 2,000건 · 부트스트랩 95% CI

| 자연 비율 | F1@0.5 | ROC-AUC |
|---|---|---|
| 룰 단독 | 0.838 [0.825, 0.851] | 0.637 [0.615, 0.659] |
| 모델 단독 | 0.854 [0.841, 0.866] | 0.667 [0.640, 0.693] |
| **결합** | **0.855 [0.843, 0.867]** | **0.724 [0.697, 0.750]** |

| 균형 비율 | F1@0.5 | ROC-AUC |
|---|---|---|
| 룰 단독 | **0.704** | 0.636 |
| 결합 | 0.672 | **0.728** |

- **F1 ≥ 0.85: 점추정은 처음으로 넘겼으나(0.855) CI 하한 0.843 미달 → "달성" 아님**(불변식 6).
- **결합 > 룰: 자연 비율에선 모든 지표 우세. 균형 비율 F1 에서만 역전**(0.672 < 0.704).
  AUC 는 균형 비율에서도 결합이 크게 우세(0.728 vs 0.636)하므로, 이건 **임계값 보정
  문제**다 — 모델은 자연 비율 분포에서 보정됐는데 균형 표본에서 임계 0.5 를 그대로
  쓰면 과소예측한다. 룰 단독은 고정 이진 판정이라 재표집에 흔들리지 않는다.
  11단계에서 조건별 임계 처리를 정리할 때 함께 본다.

### ★ 절제 실험 — 이번 재설계의 존재 이유가 해소됐다

같은 봉인 평가셋에서 피처군을 나눠 각각 학습:

| 조건 | fs-1 (이전) | **fs-2 (지금)** |
|---|---|---|
| 룰 피처만 | AUC 0.7916 (46개) | 0.7188 (30개) |
| 비룰 피처만 | — | 0.7093 (44개) |
| 결합 | AUC 0.7918 (82개) | **0.7600 (74개)** |
| **비룰 추가 효과** | **+0.0002** | **+0.041** |
| 룰 추가 효과 | — | **+0.051** |

fs-1 에서는 비룰 36개를 얹어도 AUC 가 0.0002 움직였다 — ML 이 룰 발화 벡터를 다시
읽는 것 외엔 아무 일도 안 했다는 뜻이었고, 그게 이 재설계의 출발점이었다.
**이제 양쪽이 서로를 대체하지 못한다.** 룰과 비룰이 각각 독립적인 신호를 낸다.

원인: 송장·포장명세서 하자 5종이 **구조적으로** 룰 밖(엔진이 두 서류를 입력으로
받지도 않음)이면서 `dc_*` 편차율에 연속적·자연 중첩 흔적을 남기기 때문. 상수를
조작해서가 아니라 구조에서 나왔다.

### ⚠️ 감시 항목 — 분리력이 문턱에 근접 (9단계 이후 재측정)

문턱 0.85. **9단계(47A 풀 분할) 직후 재측정 — 47A 샘플링 로직 교체가 공용 RNG
스트림을 흔들어 아래 수치가 8단계 시점과 달라졌다(9단계 진단 절 참고, `goods_wording_diff`
는 그 결과로 무하자 쪽 변동 폭을 0.30→0.34 로 넓혀 되돌렸다).**

| 유형 | 학습셋 seed=42 | 봉인평가셋 seed=20260814 | 최대 AUC 피처 |
|---|---|---|---|
| `goods_wording_diff` | 0.805 | 0.809 | `llm_goods_invoice_semantic_equiv` |
| `qty_sum_mismatch` | 0.842 (여유 0.008) | 0.761 | `dc_qty_deviation_ratio` |
| `weight_sum_mismatch` | 0.772 | 0.825 (여유 0.025) | `dc_weight_deviation_ratio` |
| `invoice_amount_mismatch` | 0.636 | 0.810 | `dc_amount_deviation_ratio` |

`qty_sum_mismatch`(학습, 여유 0.008)와 `weight_sum_mismatch`(평가, 여유 0.025)가
가장 여유가 적다 — 둘 다 이번 단계에서 손대지 않은 축이라 8단계 이전부터 있던
여유다(qty 는 원래 0.841). 10단계 이후 재측정 시 우선 확인 대상.

`goods_wording_diff` 는 8단계에서 0.701 → 0.845 로 올랐다(새 `llm_goods_semantic_equiv`
— 토큰 Jaccard — 가 Levenshtein 보다 이 하자를 잘 잡기 때문). 피처가 제 역할을
한 것이지 워터마크(고정 문자열·클램프·1:1 플래그)는 아니고 분포도 겹친다.

**지금 튜닝하지 않기로 한 이유**: 10단계에서 Gemini 가 `llm_goods_semantic_equiv` 를
통째로 대체한다. 곧 없어질 오프라인 휴리스틱에 맞춰 DGP 를 조정하면 **대역품에
과적합**하는 셈이다. Gemini 실측 후 재측정해서, 그때도 넘으면 **문턱을 낮추지 말고**
무하자 쪽 표기 변동 폭을 넓히는 방향(설계서 1절이 규정한 방향)으로 고친다.

### 알려진 미완 — `llm_available` 이 상수 1.0

오프라인 백엔드는 실패하지 않으므로 `llm_available` 이 전 행 1.0 이라 정보량이 0이다.
계획대로라면 학습 시 **3~5% 정도 LLM 결측 행을 일부러 섞어야** 모델이 NaN 방향을
학습하고, 실서비스에서 Gemini 장애가 났을 때 조용히 성능이 무너지지 않는다.
10단계에서 처리한다.

---

## 4-1. 이전 측정 (fs-1 — 무효, 역사적 기록)

출처: `docs/artifacts_fs1/fs-1-20260814-00bc3e/metrics.json` · 봉인 평가셋 2,000건 · 부트스트랩 95% CI

| 자연 비율 | F1@0.5 | ROC-AUC |
|---|---|---|
| 룰 단독 | 0.785 [0.766, 0.802] | 0.731 [0.709, 0.752] |
| 모델 단독 | 0.821 [0.806, 0.836] | 0.753 [0.731, 0.776] |
| **결합** | **0.844 [0.829, 0.857]** | **0.792 [0.769, 0.814]** |

- 결합 > 룰 단독: **달성** (모든 지표·양쪽 비율, 페어드 부트스트랩 P=1.000)
- F1 ≥ 0.85: **미달**

**⚠️ 단, 절제 실험이 마진의 실체를 뒤집었다.** 룰 피처만(46개) = AUC 0.7916, 결합(82개) = 0.7918
→ **비룰 36개를 얹어도 +0.0002.** 마진은 "룰이 못 보는 위험 포착"이 아니라 **"룰 발화 벡터를
이진 판정보다 잘 읽는 것"**이다. 룰 밖 하자만 가진 양성 행은 음성보다 **낮게** 랭크된다(AUC 0.415).

**이번 재설계의 존재 이유가 이것이다.**

### fs-2 구조 전환 후 1차 `gen-data` 진단 (3단계, 모델 재학습 전 — 참고용)

`rule_sim.py`(임시 시뮬레이터, 실제 21개 D-코드로 발화)로 만든 학습셋(3,000건) 기준.
**아직 인젝터를 재정렬하지 않았고(4단계 몫) 모델을 재학습하지도 않았다** — 위 F1/AUC
표와 직접 비교 가능한 숫자가 아니다. `train.py` 를 돌리는 7단계에서 정식 비교표가 나온다.

```json
{
  "phi_y_vs_rv_any_critical": 0.2322,
  "defect_rate_when_rule_silent": 0.6025,
  "repair_rate_when_rule_fired": 0.1781,
  "n_rule_silent": 1804,
  "n_rule_fired": 1196,
  "overall_defect_rate": 0.69
}
```

fs-1 의 `repair_rate_when_rule_fired`(R5 위험 표 기준 0.144, 여유 0.044)보다 **여유가 커졌다**
(0.178, 여유 0.078) — DEFECT_TYPE_TO_RULE 을 실제 카탈로그 3개(D008/D018/D004)로만
좁혔더니 룰이 덜 쏘고, FP 비중이 상대적으로 늘어난 결과로 보인다. 4단계에서 인젝터를
재정렬하면 다시 크게 움직일 수치다.

룰 밖 하자 4종(§1절 신규 진단, UNCOVERED_SPECS 는 이번 단계에서 손대지 않았으므로 fs-1과
동일 4종)의 단일 피처 최대 AUC는 전부 0.85 미만으로 유지된다(0.594~0.735, 전부 분포 겹침
확인됨) — 워터마크 재발 없음.

---

## 5. 이번 재설계의 핵심 발견

실제 룰엔진(`ruleEngine/`, 21룰)은 **B/L ↔ L/C만 비교한다. 송장 룰 0개, 포장명세서 룰 0개.**
`verify(bl, lc)` 시그니처가 두 서류만 받는다.

→ 기존 "룰 커버" 하자 7종 중 **6종이 실제 엔진에는 안 보인다.** 룰엔진만 갈아끼우면 룰
베이스라인이 엉뚱한 이유로 붕괴한다. **인젝터 재정렬(4단계)이 필수 동반 작업.**

→ 동시에 이것이 §6.4 문제를 푼다. 송장·포장명세서 불일치는 **구조적으로** 룰 밖이면서
`dc_qty/amount/weight_deviation_ratio`에 연속적·자연 중첩 흔적을 남긴다. 상수를 조작하지 않고도
"룰 밖 하자를 ML이 탐지"가 처음으로 성립한다.

실측으로 확인한 것들:
- `_tokens_match("LOS ANGELES, USA (ALT)", "LOS ANGELES, USA")` → `True` (port_mismatch 미탐)
- `parse_quantity("512.0", "KG")` → `None` (단위 접미사 필수)
- `Verdict.defect_probability` → **1.0 클리핑**, 쓰지 말 것
- 동명이물 `LCTerms` 2개 (필드 완전 불일치) — `EngineLCTerms` 별칭 강제

### 2단계에서 추가로 드러난 갭 (4단계에서 해소해야 함)

`SynthShipment`에 없는 필드 때문에 **일부 룰이 구조적으로 항상 같은 결과를 낸다.**

| 증상 | 원인 | 4단계 조치 |
|---|---|---|
| **D001(B/L 번호 누락)이 항상 발화** | `SynthShipment`에 `bl_no` 없음 → 어댑터가 키를 안 넣음 → `required`가 매번 누락 판정 | `bl_no` 추가 |
| **D005B(수하인 불일치)가 항상 skip** | `EngineLCTerms.consignee`에 대응하는 L/C 필드가 없음 (`lc_port_of_discharge`만 있음) | `lc_consignee` 추가 |
| D007/D007B/D017 항상 skip | `measurement_cbm`, `freight_amount_usd`, `lc_max_*`, `lc_freight_amount` 없음 | 전부 추가 |
| D002(선적기한) 항상 skip | `lc_latest_shipment_date` 없음 | 추가 |

**항상 같은 값인 피처는 XGBoost에 정보가 0이면서 열만 차지한다.** 4단계에서 필드를 채우지 않으면
21개 룰 중 실제로 변동하는 건 소수에 그친다.

---

## 6. 모델 역할 분담

| 역할 | 모델 |
|---|---|
| 설계 | **Opus** (메인 세션) |
| 코딩 | **Sonnet** |
| 단순 기계 작업 | **Haiku** |
| 검증 | **Fable** |

4·5·9·10단계는 지난 3회 검증에서 버그가 나온 자리다. **Haiku에 위임하지 않는다.**

---

## 7. 갱신 규약

**매 단계 종료 시 이 문서를 갱신한다.** 특히:
- 1절 표의 상태
- 3절에 새로 되돌린 시도가 있으면 **이유와 함께** 추가
- 4절 숫자는 재측정될 때마다 교체하되, 이전 값의 출처 아티팩트 경로를 남긴다

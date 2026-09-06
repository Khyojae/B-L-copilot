"""경로·시드·하이퍼파라미터 상수.

설계서 3절: 이 디렉토리 밖의 파일을 읽기만 하고 쓰지 않는다.
AI Hub 라벨 경로는 로컬 전용이므로 환경변수로 덮어쓸 수 있게 한다
(설계서: "이 경로는 로컬 머신 전용이며, config.py 에서 설정 가능해야 한다").
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# .env 로드 (계획서 10단계 — GEMINI_API_KEY 를 .env 에 두기 위함)
#
# 이 모듈은 원래 os.environ 만 읽었기 때문에 프로젝트 루트 `.env` 에 키를 적어도
# **조용히 무시됐다.** 아무 에러 없이 "키가 없다"로 떨어지는 종류의 함정이라
# 명시적으로 로드한다.
#
# `override=False` 가 중요하다 — 이미 환경에 있는 값을 .env 가 덮어쓰지 않는다.
# 그래야 CI·쉘 export 가 항상 .env 를 이긴다.
#
# 테스트 안전성: tests/conftest.py 의 autouse 픽스처가 매 테스트마다 API 키
# 환경변수를 지우고 백엔드를 오프라인으로 고정하므로, .env 에 실제 키가 있어도
# 테스트가 유료 호출을 하지 못한다.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:  # python-dotenv 미설치 — 쉘 환경변수만 사용한다
    pass

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
POOLS_DIR = DATA_DIR / "pools"
DATASETS_DIR = DATA_DIR / "datasets"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

# AI Hub 선하증권 OCR 라벨 4,000건. 로컬 전용 경로 — 환경변수 AI_HUB_BL_LABEL_DIR 로
# 덮어쓸 수 있다. pools.py 는 이 경로가 없으면 명확한 에러로 종료한다(설계서 2절).
AI_HUB_LABEL_DIR = Path(
    os.environ.get(
        "AI_HUB_BL_LABEL_DIR",
        "/Users/ethanyang/Documents/B_L_model/Sample Data/"
        "025.OCR 데이터(금융 및 물류)/01-1.정식개방데이터/Training/"
        "02.라벨링데이터/TL_물류_3.선하증권_BL01",
    )
)

# 필드별 실측 추출 정확도 (설계서 2절, 5.1). Group 3 노이즈 강도의 근거.
EVAL_REPORT_PATH = Path(
    os.environ.get(
        "AI_HUB_EVAL_REPORT",
        str(
            PACKAGE_DIR.parent
            / "archive_bl_model_v2"
            / "reports_eval_2000"
            / "eval_report_merged.json"
        ),
    )
)

POOLS_FILE = POOLS_DIR / "value_pools.json"

TRAIN_DATASET_FILE = DATASETS_DIR / "train_3000.parquet"
EVAL_DATASET_FILE = DATASETS_DIR / "eval_sealed_2000.parquet"
TRAIN_MANIFEST_FILE = DATASETS_DIR / "train_3000.manifest.json"
EVAL_MANIFEST_FILE = DATASETS_DIR / "eval_sealed_2000.manifest.json"

# 검수 표본(설계서 5.6, 기획안 10.3 ⑥) — 평가셋에서 층화 추출한 200건(=10%).
REVIEW_SAMPLE_FILE = DATASETS_DIR / "eval_review_sample_200.parquet"
REVIEW_SAMPLE_MANIFEST_FILE = DATASETS_DIR / "eval_review_sample_200.manifest.json"

# ---------------------------------------------------------------------------
# 시드 (설계서 5.6) — 학습·평가는 반드시 다른 시드·다른 파일을 쓴다.
# ---------------------------------------------------------------------------

TRAIN_SEED = 42
EVAL_SEED = 20260814  # 오늘 날짜(YYYYMMDD) — 봉인 평가셋 재생성 방지용 고정 시드

TRAIN_BASE_COUNT = 1000
TRAIN_VARIANTS_PER_BASE = 3  # 3,000 선적

# 평가셋 2,000건(설계서 5.6). 200건에서는 결합 F1 95% CI 가 [0.808, 0.899] 로
# 벌어져 P(F1<0.85)=0.40 — "0.85를 넘겼다"는 주장이 통계적으로 성립하지 않는다.
# 생성 비용이 사실상 0이므로 표본을 키우는 것이 유일하게 합리적인 선택이다.
EVAL_BASE_COUNT = 2000
EVAL_VARIANTS_PER_BASE = 1  # 2,000 선적. 개발 중 열람 금지(봉인).

# 검수 표본(설계서 5.6) — 평가셋에서 층화 추출. 200/2,000 = 10% 로 기획안 10.3
# ⑥("전체의 10% 이상 표본 검수")과 정확히 맞아떨어진다.
REVIEW_SAMPLE_SIZE = 200

# ---------------------------------------------------------------------------
# XGBoost 하이퍼파라미터 (설계서 6.2) — 소표본이므로 얕게 간다.
# ---------------------------------------------------------------------------
#
# min_child_weight 재검증 (설계서 4절 하이퍼파라미터 민감도 요건, 검증자 지적 반영):
# 이전 서술("mcw 커질수록 단조 감소, mcw=1: AUC 0.901 … mcw=150: 붕괴")은 Group 6
# HISTORY 피처의 leave-group-out 라벨 누수(설계서 4절 ⚠️ 참고) 위에서 관측된 것이었다.
# 그 피처가 자기 라벨의 LOO 인코딩이었던 탓에 홀드아웃 자체가 오염돼 있었고, 스윕
# 결과도 그 오염을 그대로 반영한 것이었다.
#
# HISTORY 를 규칙대로 재구현(별도 이력 기간, 타깃 인코딩 없음)한 뒤 학습셋 내
# validation 분할(=봉인 평가셋과 무관한 holdout, 600건 — 3,000 × 20%. 과거 주석의
# "2,000건"은 오기였다)에서 다시 스윕한 실측 결과(train_3000/eval_sealed_2000,
# 결합 82피처, sigmoid 보정 전 booster ROC-AUC)는 **거의 평탄**하다 — mcw=1: 0.808,
# mcw=5(설계서 6.2 예시값): 0.810, mcw=10: 0.814, mcw=30: 0.806, mcw=50: 0.803,
# mcw=75: 0.804. mcw=100부터 무너지기 시작해(0.774) mcw=150에서는 트리가 사실상
# 1개만 남아 붕괴한다(0.500). 즉 "단조 감소"가 아니라 "1~75 구간은 평탄, 100 이상만
# 급락"이다 — 이전 주석의 극적인 단조 그림은 누수가 만든 착시였다. mcw=5는 이
# 평탄 구간 안에 있으므로 그대로 채택한다(굳이 튜닝해 옮길 이유가 없다). 자세한
# 수치는 metrics.json::mcw_sensitivity 참고.
XGB_PARAMS: dict[str, object] = {
    "max_depth": 3,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "learning_rate": 0.05,
    "tree_method": "hist",
    "random_state": 42,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
}
XGB_MAX_ESTIMATORS = 2000
XGB_EARLY_STOPPING_PATIENCE = 50

# min_child_weight 민감도 스윕 값(설계서 4절 "하이퍼파라미터 탐색이 학습셋 내
# holdout 에서만 이뤄진다" 요건 — 민감도 표 포함). train.py 가 validation
# 분할(학습셋 내부, 봉인 평가셋 아님)에서만 이 값들을 탐색한다.
MCW_SWEEP_VALUES: tuple[int, ...] = (1, 3, 5, 10, 20, 30, 50, 75, 100, 150)

# 3분할 비율 (설계서 6.1)
SPLIT_TRAIN_RATIO = 0.60
SPLIT_CALIBRATION_RATIO = 0.20
SPLIT_VALIDATION_RATIO = 0.20

# 성공 판정 (설계서 0절, 6.4, 기획안 10.4) — 신뢰구간 하한 기준(설계서 5.6).
SUCCESS_F1_THRESHOLD = 0.85

# 부트스트랩 신뢰구간(설계서 5.6) — 모든 보고 지표에 부트스트랩 95% CI를 붙인다.
BOOTSTRAP_N = 1000
BOOTSTRAP_CI = 0.95

# 은행 재량 노이즈 파라미터 (설계서 5.5) — 채널 B 전용, rule_sim 과 공유하지 않는다.
BASE_FALSE_DEFECT_RATE = 0.05
LENIENT_RATE = 0.08
BANK_STRICTNESS_RANGE = (0.8, 1.2)

# 거래처·화물유형 잠재 하자 성향 (설계서 4절 Group 6 규칙 3) — Beta(2,2) 분포에서
# 뽑아 [low, high] 로 스케일한 승수. 평균이 1.0 이 되는 대칭 범위를 쓴다.
# generator.py 가 은행 strictness 와 함께 combined_strictness = bank_strictness *
# counterparty_propensity * cargo_type_propensity 를 구성해 채널 B(review.py)에
# 넘긴다 — 이 값이 있어야 HISTORY 피처군(Group 6)이 정당한 신호를 갖는다(v2는
# 이 성향이 없어서 hist_counterparty_defect_rate 등이 누수 운반체로만 존재했다).
COUNTERPARTY_PROPENSITY_RANGE = (0.80, 1.20)
CARGO_TYPE_PROPENSITY_RANGE = (0.90, 1.10)

# 이력 기간(history period) 건수 범위 (설계서 4절 Group 6 규칙 4) — 거래처마다
# 이 범위에서 균등하게 뽑는다. 0건이면 콜드스타트(hist_is_cold_start=1, 세 비율 NaN).
# 건수가 적을수록 관측 비율이 잠재 성향에서 벗어나는 관측 잡음(이항 표집)의 근거다.
HISTORY_SHIPMENT_COUNT_RANGE = (0, 50)

# ---------------------------------------------------------------------------
# [채널 A] 관측 노이즈 계층 파라미터 (설계서 5.4, HANDOFF.md 5단계 — synth/extraction_view.py)
#
# v3의 rule_sim.py 는 RULE_FIRE_PROB_RANGE/RULE_SPURIOUS_FIRE_PROB_RANGE 라는
# 두 개의 임의 상수로 FN/FP 를 직접 흉내냈다. v4(실제 룰엔진 배선)부터는 룰이
# 실제로 돈다 — 그래서 FN/FP 는 "룰이 놓친다"가 아니라 "룰이 보는 입력값 자체가
# OCR 추출값이라 틀리다"에서 파생된다. 아래 상수는 신뢰도 자체(측정값,
# generator.load_field_accuracy() 출처)가 아니라 "신뢰도 → 드랍/왜곡 확률" 변환
# 강도만 규정한다 — review.py 와 공유하지 않는다(채널 독립, 설계서 1절).
# ---------------------------------------------------------------------------

# 신뢰도 1.0(완전 확신)에서도 드랍/왜곡 확률이 0이 아니다 — 실측 필드 정확도가
# 100%인 필드는 없다(eval_report_merged.json). 신뢰도 0에 가까울수록 상한에 수렴한다.
EXTRACTION_DROP_PROB_AT_FULL_CONF = 0.01
EXTRACTION_DROP_PROB_AT_ZERO_CONF = 0.65
EXTRACTION_GARBLE_PROB_AT_FULL_CONF = 0.02
EXTRACTION_GARBLE_PROB_AT_ZERO_CONF = 0.55

# no_evidence_fields(생성기가 이미 "근거 문자열을 찾지 못함"으로 표시한 필드, 설계서
# 5.1)는 값 자체는 있으나 신뢰할 수 없다는 뜻이므로, 드랍이 아니라 왜곡 쪽으로
# 치우친 확률 하한을 둔다 — "값은 있지만 틀렸다"가 "값이 없다"보다 이 상태에 더
# 가깝다.
EXTRACTION_GARBLE_PROB_NO_EVIDENCE_FLOOR = 0.5

# 필드 종류별 왜곡 강도. 문자열은 편집 연산 횟수, 날짜는 최대 이동일수, 수치는
# 상대 왜곡 비율 범위.
EXTRACTION_GARBLE_TEXT_OPS_RANGE = (1, 3)
EXTRACTION_GARBLE_DATE_MAX_SHIFT_DAYS = 6
EXTRACTION_GARBLE_NUMERIC_JITTER_RANGE = (0.05, 0.35)

# ---------------------------------------------------------------------------
# [채널 B] 모의 심사기 백엔드 선택 (설계서 5.5 "두 개의 백엔드")
# ---------------------------------------------------------------------------
#
# constant_table: ICC/ISBP 유형별 적발 확률 상수 테이블(review.py::P_DETECT).
#                 오프라인·API 키 불필요. 기본값 — 이 저장소는 API 키 없이도
#                 gen-data/train 이 끝까지 돌아가야 한다(설계서 5.5).
# claude:         Claude 가 서류 세트(injected_defects 는 보지 않음)를 읽고
#                 UCP600/ISBP 심사역 관점에서 수리/하자를 판정한다. 논문용
#                 데이터셋 생성 시에만 쓴다 — 이 환경에는 ANTHROPIC_API_KEY 가
#                 없으므로 기본값을 절대 "claude" 로 바꾸지 않는다.
REVIEWER_BACKEND: str = os.environ.get("DEFECT_MODEL_REVIEWER_BACKEND", "constant_table")

CLAUDE_REVIEW_MODEL = "claude-opus-5"
REVIEWS_DIR = DATA_DIR / "reviews"
REVIEW_CACHE_FILE = REVIEWS_DIR / "claude_reviews.jsonl"
CLAUDE_MAX_RETRIES = 2  # 설계서 5.5: 실패·거부·스키마 위반은 재시도 2회 후 constant_table 폴백
CLAUDE_BATCH_POLL_INTERVAL_SECONDS = 10

# ---------------------------------------------------------------------------
# [채널 A] LLM 피처(Group 7, LLM_SEMANTIC) 백엔드 선택 (계획서 8단계, HANDOFF.md 8단계)
# ---------------------------------------------------------------------------
#
# null:    snapshot.llm 을 항상 None 으로 둔다(llm_available=0, 나머지 전부 NaN).
#          단위테스트 전용 — Group 7 이 전혀 관여하지 않는 경로를 검증할 때 쓴다.
# offline: 문서 텍스트만으로 결정론적 휴리스틱(토큰 자카드·조건 개수 등)을
#          계산한다. 오프라인·API 키 불필요. 기본값 — 이 저장소는 API 키 없이도
#          gen-data/train 이 끝까지 돌아가야 한다(HANDOFF.md 불변식 5).
# gemini:  10단계에서 이 인터페이스 뒤에 실제 Gemini 호출을 슬롯인다. 지금은
#          NotImplementedError. ★ HANDOFF.md 불변식 2 — REVIEWER_BACKEND 도
#          실전 LLM(constant_table 이외)이면 절대 함께 켜지지 않는다
#          (llm_features.check_channel_independence() 가 코드로 막는다).
LLM_FEATURE_BACKEND: str = os.environ.get("DEFECT_MODEL_LLM_FEATURE_BACKEND", "offline")

LLM_FEATURES_DIR = DATA_DIR / "llm_features"
LLM_FEATURE_CACHE_FILE = LLM_FEATURES_DIR / "llm_feature_cache.jsonl"

# ---------------------------------------------------------------------------
# gemini 백엔드 전송 파라미터 (계획서 10단계, HANDOFF.md "10단계 실측")
# ---------------------------------------------------------------------------
#
# 모델 ID는 실측으로 확인했다 — `client.models.list()` 조회 결과에 실존하며
# (문서를 믿지 않고 직접 조회함), 1,333자 문서 1건 기준 628 입력/109 출력
# 토큰, 지연 2.5초를 관측했다.
# ⚠️ gemini-3.7-flash 는 **무료 등급 하루 20건**이다(실측, 429 의 quotaValue).
# 5,000건이면 250일 — 사용 불가. Gemini 계열은 전부 15~20/day 였다
# (3.6-flash, 3.1-flash-lite, 3.5-flash-lite 실측. *-latest 는 별칭이라 같은 버킷).
#
# gemma-* 는 오픈 모델이라 무료 정책이 다르다. gemma-4-31b-it 로 **66건 연속
# 성공**(중단은 한도가 아니라 일시적 5xx), RPM 11.5, 건당 660입력/109출력 토큰,
# 지연 중앙 4.2초. 5,000건 ≈ 7시간. 같은 SDK·같은 구조적 출력 스키마·같은
# 프롬프트로 그대로 동작한다 — 바뀌는 건 이 상수 하나뿐이다.
GEMINI_FEATURE_MODEL = "gemma-4-31b-it"

# 동시성 상한 — 무료 등급 분당 호출 한도(GEMINI_RPM_LIMIT)와 별개로 순간 동시
# 연결 수 자체를 제한한다(스레드풀 크기).
GEMINI_MAX_CONCURRENCY = 4

# 503(UNAVAILABLE)이 "예외가 아니라 상시 발생"함을 실측으로 확인했다(HANDOFF.md
# 10단계) — 재시도는 선택이 아니라 필수다. review.py::CLAUDE_MAX_RETRIES(2)와
# 별개 상수로 둔다(백엔드별로 재시도 정책이 다를 수 있다).
GEMINI_MAX_RETRIES = 3

# 무료 등급 분당 호출 한도(RPM) — 토큰 버킷 리미터가 이 값을 지킨다. 공식 문서를
# 믿지 않고 조회하는 게 원칙이지만(위 모델 ID 실측과 동일 원칙) RPM 한도는
# `client.models.list()` 로 알 수 없으므로 보수적인 기본값을 둔다. 429 를 실제로
# 관측하면(파일럿 실행) 이 값을 조정한다.
GEMINI_RPM_LIMIT = 10

# 지수 백오프(+지터) 경계. Retry-After 헤더가 있으면 그 값을 우선한다.
GEMINI_BACKOFF_BASE_SECONDS = 1.0
GEMINI_BACKOFF_MAX_SECONDS = 20.0
GEMINI_BACKOFF_JITTER_SECONDS = 0.5

# 공개 단가(설계서 5.5/HANDOFF.md 10단계 실측 근거, USD/1M 토큰) — 비용 추정용.
# gemini-3.7-flash 는 opus 대비 출력이 1/4(109 vs 400)이고 단가도 훨씬 낮다.
GEMINI_INPUT_PRICE_PER_MTOK = 0.75
GEMINI_OUTPUT_PRICE_PER_MTOK = 3.75

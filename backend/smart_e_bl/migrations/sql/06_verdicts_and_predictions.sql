-- ============================================================================
-- F3 판정 — 룰엔진 판정(계층 A) · 하자 확률 예측(계층 B)
-- 근거: 기획안 5.3, 5.8
-- ============================================================================

-- ---------------------------------------------------------------------------
-- verdict — F3 생산 → F4 소비 (기획안 5.8)
-- ---------------------------------------------------------------------------
CREATE TABLE verdict (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id           uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id         uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
  rule_id             uuid NOT NULL REFERENCES rule(id) ON DELETE RESTRICT,

  severity            severity NOT NULL,
  status              verdict_status NOT NULL DEFAULT 'OPEN',

  -- 대상 필드와 값 (기획안 5.4 ②: 현재 값·기대 값·근거 조문 원문)
  target_field_code   text REFERENCES field_definition(code),
  target_field_value_id uuid REFERENCES field_value(id) ON DELETE SET NULL,
  actual_value        text,
  expected_value      text,
  message             text NOT NULL,

  -- 기획안 5.3: 동일 근본 원인에서 파생된 위반은 대표 위반으로 병합하고
  -- 하위 위반을 접어서 표시한다.
  merged_into_id      uuid REFERENCES verdict(id) ON DELETE SET NULL,

  -- 기획안 5.8 판정 재현성: 룰·모델·용어사전 버전을 함께 저장한다.
  rule_catalog_version text NOT NULL REFERENCES rule_catalog_version(version),
  glossary_version     text,

  judged_at           timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT verdict_no_self_merge_ck CHECK (merged_into_id <> id)
);

-- S4 검증 결과: 심각도순 정렬
CREATE INDEX verdict_shipment_idx ON verdict (shipment_id, severity, status);
-- 상태 게이트: Critical 미해결이 남아 있으면 VERIFIED 로 전이하지 않는다(기획안 5.8)
CREATE INDEX verdict_open_critical_idx ON verdict (shipment_id)
  WHERE status = 'OPEN' AND severity = 'CRITICAL';
CREATE INDEX verdict_rule_idx ON verdict (rule_id);
-- field_value 삭제(재업로드 CASCADE) 시 SET NULL 검사가 타는 인덱스
CREATE INDEX verdict_target_field_value_idx ON verdict (target_field_value_id)
  WHERE target_field_value_id IS NOT NULL;
-- 대표 위반 삭제 시 하위 병합 위반의 SET NULL 검사
CREATE INDEX verdict_merged_into_idx ON verdict (merged_into_id)
  WHERE merged_into_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- verdict_evidence
-- 기획안 5.3 수용 기준: "모든 룰 위반 항목의 조문 근거 표시율 100%,
-- 해당 필드로의 바로가기 링크 보유율 100%"
-- 판정 설명(F7)의 인용 무결성 검사도 이 테이블을 대조 대상으로 삼는다.
-- ---------------------------------------------------------------------------
CREATE TABLE verdict_evidence (
  id               uuid PRIMARY KEY DEFAULT uuidv7(),
  verdict_id       uuid NOT NULL REFERENCES verdict(id) ON DELETE CASCADE,
  -- DOCUMENT_SIDE: 서류측 근거 필드, AUTHORITY: 조문 스니펫
  evidence_side    text NOT NULL,
  field_value_id   uuid REFERENCES field_value(id) ON DELETE CASCADE,
  snippet          text,
  created_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT verdict_evidence_side_ck
    CHECK (evidence_side IN ('DOCUMENT_SIDE', 'AUTHORITY')),
  -- 근거는 둘 중 하나를 반드시 가리킨다. 빈 근거는 저장하지 않는다.
  CONSTRAINT verdict_evidence_target_ck
    CHECK (num_nonnulls(field_value_id, snippet) >= 1)
);

CREATE INDEX verdict_evidence_verdict_idx ON verdict_evidence (verdict_id, evidence_side);
CREATE INDEX verdict_evidence_field_idx ON verdict_evidence (field_value_id);

-- ---------------------------------------------------------------------------
-- verdict_disposition — 사람의 처리 이력
-- 기획안 5.3: Warning 은 사용자가 사유를 남기고 보류할 수 있다.
-- 기획안 5.8 공통 규약: 자동 반영하지 않고 명시적 승인으로만 확정한다.
-- ---------------------------------------------------------------------------
CREATE TABLE verdict_disposition (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  verdict_id   uuid NOT NULL REFERENCES verdict(id) ON DELETE CASCADE,
  to_status    verdict_status NOT NULL,
  reason       text NOT NULL,
  actor_id     uuid REFERENCES app_user(id),
  decided_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX verdict_disposition_verdict_idx ON verdict_disposition (verdict_id, decided_at DESC);

-- ---------------------------------------------------------------------------
-- model_version — F3 계층 B 모델 레지스트리
-- 기획안 5.3: 재학습 후 검증셋 성능이 하락하면 이전 모델로 자동 롤백한다.
-- 롤백 판단에는 버전별 지표가 남아 있어야 한다.
-- ---------------------------------------------------------------------------
CREATE TABLE model_version (
  version              text PRIMARY KEY,
  trained_at           timestamptz NOT NULL DEFAULT now(),
  training_label_count integer NOT NULL DEFAULT 0,
  -- 기획안 5.3 평가 지표: F1, ROC-AUC, Brier score
  metric_f1            numeric(5,4),
  metric_roc_auc       numeric(5,4),
  metric_brier         numeric(6,5),
  is_active            boolean NOT NULL DEFAULT false,
  rolled_back_from     text REFERENCES model_version(version),
  note                 text
);

CREATE UNIQUE INDEX model_version_active_uk ON model_version (is_active) WHERE is_active;

-- ---------------------------------------------------------------------------
-- defect_prediction — F3 계층 B (XGBoost)
-- 기획안 5.3: 확률 보정을 적용하고, 보정 전 원점수는 표시하지 않는다.
-- ---------------------------------------------------------------------------
CREATE TABLE defect_prediction (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id           uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id         uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,

  probability         numeric(5,4) NOT NULL,   -- 보정 후 확률
  raw_score           numeric(5,4),            -- 보정 전 원점수(표시 금지, 분석용)
  is_calibrated       boolean NOT NULL DEFAULT true,

  model_version       text NOT NULL REFERENCES model_version(version),
  rule_catalog_version text NOT NULL REFERENCES rule_catalog_version(version),
  feature_snapshot    jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- 기획안 5.4 예외: 판정 보류 항목이 많으면 확률 대신 범위를 제시한다.
  deferred_field_count integer NOT NULL DEFAULT 0,
  is_range_only        boolean NOT NULL DEFAULT false,

  created_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT defect_prediction_probability_ck CHECK (probability BETWEEN 0 AND 1),
  CONSTRAINT defect_prediction_raw_ck CHECK (raw_score IS NULL OR raw_score BETWEEN 0 AND 1)
);

CREATE INDEX defect_prediction_shipment_idx ON defect_prediction (shipment_id, created_at DESC);

-- 기획안 5.3: SHAP 기여도 상위 5개 요인을 함께 반환하여
-- F4 리포트가 "왜 이 확률인가"를 서술할 수 있게 한다.
CREATE TABLE prediction_factor (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  prediction_id  uuid NOT NULL REFERENCES defect_prediction(id) ON DELETE CASCADE,
  rank           smallint NOT NULL,
  feature_name   text NOT NULL,
  -- 기획안 5.3 피처군: 룰 위반 / 서류 정합성 / 추출 품질 / L/C 복잡도 / 시간 여유 / 이력
  feature_group  text,
  shap_value     numeric(10,6) NOT NULL,
  CONSTRAINT prediction_factor_rank_ck CHECK (rank BETWEEN 1 AND 20)
);

CREATE UNIQUE INDEX prediction_factor_uk ON prediction_factor (prediction_id, rank);

COMMENT ON COLUMN defect_prediction.raw_score IS '기획안 5.3: 보정 전 원점수는 사용자에게 표시하지 않는다';

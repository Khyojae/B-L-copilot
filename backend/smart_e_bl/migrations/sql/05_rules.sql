-- ============================================================================
-- F3 계층 A — 룰 카탈로그
-- 근거: 기획안 5.3
--
-- 기획안 5.3: "룰은 코드가 아니라 데이터(룰 카탈로그 테이블)로 관리하여
-- 조문 개정 시 배포 없이 갱신한다"
-- ============================================================================

-- ---------------------------------------------------------------------------
-- rule_catalog_version — 판정 재현성의 단위
-- 기획안 5.3 예외: 룰 카탈로그 버전을 판정 결과에 함께 저장하여
-- 과거 판정을 당시 기준으로 재현할 수 있게 한다.
-- ---------------------------------------------------------------------------
CREATE TABLE rule_catalog_version (
  version      text PRIMARY KEY,          -- 예) '2026.08.1'
  released_at  timestamptz NOT NULL DEFAULT now(),
  note         text,
  is_current   boolean NOT NULL DEFAULT false
);

-- 현재 버전은 하나뿐이다.
CREATE UNIQUE INDEX rule_catalog_version_current_uk
  ON rule_catalog_version (is_current) WHERE is_current;

-- ---------------------------------------------------------------------------
-- rule
-- 기획안 5.3 룰 정의 구조: rule_id, 근거 조문, 심각도, 검사 대상 필드,
-- 판정식, 사용자 메시지 템플릿, 수정 가이드, 활성 여부, 버전
-- ---------------------------------------------------------------------------
CREATE TABLE rule (
  id                   uuid PRIMARY KEY DEFAULT uuidv7(),
  rule_code            text NOT NULL,            -- 예) 'R-UCP-14C'
  catalog_version      text NOT NULL REFERENCES rule_catalog_version(version) ON DELETE CASCADE,

  title                text NOT NULL,
  authority_ref        text NOT NULL,            -- 예) 'UCP600 14(c)'
  -- 기획안 5.3: 모든 판정에는 조문 원문 스니펫이 함께 저장되어
  -- 판정 설명의 인용 근거가 된다.
  authority_snippet    text NOT NULL,
  severity             severity NOT NULL,

  target_field_codes   text[] NOT NULL DEFAULT '{}',

  -- 내부 DSL 판정식. 예) 'bl.onboard_date + 21d < presentation_date'
  expression           text NOT NULL,
  -- 기획안 5.3: 자유서식 조건(:47A:)은 룰이 조건 문장을 분해하고
  -- LLM 은 충족 여부만 판정한다.
  is_llm_assisted      boolean NOT NULL DEFAULT false,

  message_template     text NOT NULL,
  remediation_template text NOT NULL,

  -- 기획안 5.3 예외: L/C 없는 거래는 UCP600 계열 룰을 비활성화한다.
  requires_lc          boolean NOT NULL DEFAULT false,
  is_active            boolean NOT NULL DEFAULT true,

  created_at           timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT rule_code_format_ck CHECK (rule_code ~ '^R-[A-Z]+-[A-Z0-9]+$')
);

CREATE UNIQUE INDEX rule_code_version_uk ON rule (rule_code, catalog_version);
CREATE INDEX rule_active_idx ON rule (catalog_version, is_active, severity);
-- 특정 필드를 검사하는 룰 역조회 (S4 "해당 필드로 바로가기")
CREATE INDEX rule_target_fields_idx ON rule USING gin (target_field_codes);

COMMENT ON COLUMN rule.authority_snippet
  IS '기획안 5.3: 조문 원문 스니펫. UCP600·ISBP 는 ICC 저작물이므로 라이선스 확보 후 채운다';

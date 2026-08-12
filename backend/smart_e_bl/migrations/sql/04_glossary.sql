-- ============================================================================
-- F2 표준 용어 교정 — 용어사전 및 제안 카드
-- 근거: 기획안 5.2
-- ============================================================================

-- ---------------------------------------------------------------------------
-- glossary_term
-- 기획안 5.2 사전 스키마:
--   term_id, canonical, category, lang, aliases[], authority, version,
--   effective_date, deprecated_by
-- 별칭은 유사도 검색 대상이라 배열이 아니라 별도 테이블로 정규화한다.
-- ---------------------------------------------------------------------------
CREATE TABLE glossary_term (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  term_code      text NOT NULL,               -- 예) 'KRPUS'
  canonical      text NOT NULL,               -- 예) 'KRPUS (Busan)'
  category       text NOT NULL,               -- port | unit | container | party | incoterms | hs | phrase
  lang           text NOT NULL DEFAULT 'en',
  authority      glossary_authority NOT NULL,

  -- 기획안 5.2 계층 구조: 표준(읽기 전용) → 조직(오버라이드) → 선적 예외
  scope          glossary_scope NOT NULL DEFAULT 'STANDARD',
  tenant_id      uuid REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id    uuid REFERENCES shipment(id) ON DELETE CASCADE,

  -- 기획안 5.2 버전 관리: 과거 판정을 당시 버전으로 재현 가능하게 유지
  version        text NOT NULL,
  effective_date date NOT NULL,
  deprecated_by  uuid REFERENCES glossary_term(id) ON DELETE SET NULL,
  is_active      boolean NOT NULL DEFAULT true,

  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT glossary_term_lang_ck CHECK (lang IN ('ko', 'en')),
  CONSTRAINT glossary_term_category_ck CHECK (category IN
    ('port', 'unit', 'container', 'party', 'incoterms', 'hs', 'phrase', 'document_term')),
  -- 계층에 맞는 소유자만 갖는다. 표준 사전은 테넌트에 속하지 않는다.
  CONSTRAINT glossary_term_scope_owner_ck CHECK (
    (scope = 'STANDARD'     AND tenant_id IS NULL AND shipment_id IS NULL) OR
    (scope = 'ORGANIZATION' AND tenant_id IS NOT NULL AND shipment_id IS NULL) OR
    (scope = 'SHIPMENT'     AND tenant_id IS NOT NULL AND shipment_id IS NOT NULL)
  )
);

CREATE UNIQUE INDEX glossary_term_std_uk
  ON glossary_term (term_code, category, version) WHERE scope = 'STANDARD';
CREATE INDEX glossary_term_lookup_idx
  ON glossary_term (category, scope, is_active);
CREATE INDEX glossary_term_tenant_idx
  ON glossary_term (tenant_id) WHERE tenant_id IS NOT NULL;
-- 구버전 용어 삭제 시 후속 버전의 SET NULL 검사
CREATE INDEX glossary_term_deprecated_by_idx
  ON glossary_term (deprecated_by) WHERE deprecated_by IS NOT NULL;

CREATE TRIGGER glossary_term_set_updated_at
  BEFORE UPDATE ON glossary_term FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- glossary_alias — 비표준 표기
-- 기획안 5.2 처리 절차 ①~④: 정확 일치 조회 → 별칭 조회 → 패턴 규칙 →
-- 미매칭 시 유사도 검색(문자 n-gram + 임베딩)
-- ---------------------------------------------------------------------------
CREATE TABLE glossary_alias (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  term_id         uuid NOT NULL REFERENCES glossary_term(id) ON DELETE CASCADE,
  alias_text      text NOT NULL,
  -- 대소문자·공백·구두점을 제거한 조회 키. ①·② 단계의 정확 일치 대상.
  normalized_key  text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX glossary_alias_uk ON glossary_alias (term_id, normalized_key);
CREATE INDEX glossary_alias_exact_idx ON glossary_alias (normalized_key);
-- ④ 유사도 검색: 문자 n-gram
CREATE INDEX glossary_alias_trgm_idx ON glossary_alias USING gin (normalized_key gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- normalization_suggestion — 제안 카드
-- 기획안 5.2: 자동 치환은 하지 않는다. 사용자가 승인해야 반영되며,
-- 거절 시 사유를 기록해 사전 개선과 조직별 예외 규칙 생성에 사용한다.
-- ---------------------------------------------------------------------------
CREATE TABLE normalization_suggestion (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id       uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id     uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
  field_value_id  uuid NOT NULL REFERENCES field_value(id) ON DELETE CASCADE,

  as_is           text NOT NULL,
  to_be           text NOT NULL,
  term_id         uuid REFERENCES glossary_term(id) ON DELETE SET NULL,
  authority       glossary_authority,
  confidence      numeric(4,3),

  -- 기획안 5.2 처리 절차 ④: 유사도 검색으로 산출한 상위 후보 5건.
  -- 동음이의 항구처럼 판별 불가한 경우 "후보를 나열해 사용자에게 선택시킨다
  -- (임의 선택 금지)"는 예외 규칙이 이 목록을 필요로 한다.
  -- [{term_id, canonical, score, reason}] 형태.
  candidates      jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- 후보 중 사용자가 고른 값이 to_be 와 다를 수 있으므로 선택 결과를 따로 남긴다.
  chosen_term_id  uuid REFERENCES glossary_term(id) ON DELETE SET NULL,

  -- 기획안 5.2 일괄 적용: 같은 as_is 가 걸린 다른 서류·필드 수
  impact_scope_count integer NOT NULL DEFAULT 1,

  status          suggestion_status NOT NULL DEFAULT 'PROPOSED',
  reject_reason   suggestion_reject_reason,
  decided_by      uuid REFERENCES app_user(id),
  decided_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT normalization_suggestion_confidence_ck
    CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  CONSTRAINT normalization_suggestion_no_op_ck CHECK (as_is <> to_be),
  CONSTRAINT normalization_suggestion_candidates_ck
    CHECK (jsonb_typeof(candidates) = 'array' AND jsonb_array_length(candidates) <= 5),
  -- 거절에는 사유가 따른다.
  CONSTRAINT normalization_suggestion_reject_ck
    CHECK (status <> 'REJECTED' OR reject_reason IS NOT NULL),
  -- 결정된 제안은 결정 시각과 결정자를 갖는다.
  CONSTRAINT normalization_suggestion_decided_ck CHECK (
    status = 'PROPOSED' OR (decided_at IS NOT NULL AND decided_by IS NOT NULL)
  )
);

CREATE INDEX normalization_suggestion_shipment_idx
  ON normalization_suggestion (shipment_id, status);
-- 부분 인덱스가 아니어야 한다: field_value 삭제(문서 재업로드 CASCADE) 시
-- FK 검사가 이 인덱스를 타는데, WHERE 절이 붙으면 FK 검사에 쓰이지 못해
-- 삭제마다 순차 스캔이 난다.
CREATE INDEX normalization_suggestion_field_idx
  ON normalization_suggestion (field_value_id);
-- 반복 거절/승인 집계 → 조직 사전 자동 제안의 입력
CREATE INDEX normalization_suggestion_learning_idx
  ON normalization_suggestion (tenant_id, as_is, to_be, status);

COMMENT ON TABLE normalization_suggestion
  IS '기획안 5.2 제안 카드. 자동 치환 없이 사용자 승인으로만 반영된다';

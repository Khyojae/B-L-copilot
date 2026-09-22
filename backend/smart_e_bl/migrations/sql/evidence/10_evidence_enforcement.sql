-- ============================================================================
-- 저장 계층 근거 강제 (내용 수준) — ACK 2026 논문 프로토타입
-- 근거: 논문계획서 §4.1~4.6, 기술담당 작업분배 B1~B5
--
-- 이 파일은 baseline(0001) 이 아니라 0003 리비전이 적용한다.
-- (migrations/sql/*.sql 은 baseline 이 통째로 실행하므로 하위 디렉터리에 둔다.)
--
--   B1  document_token · field_value 근거 컬럼 · 열거형
--   B3  fn_field_value_enforce_evidence() 트리거 (Algorithm 1)
--   B4  격리(거부 아님) · 신뢰 뷰 field_value_trusted · 검토 큐 뷰
--   B5  evidence_enforcement_config — P · E1 · E2 · E3 모드 스위치
--   B2  evidence_format_rule (변환 규칙표) — 용어사전은 20_evidence_glossary_seed.sql
--
-- 기존 CHECK field_value_evidence_required_ck(E1: 좌표 존재) 는 이 파일이 대체한다.
-- 같은 명제를 트리거의 E1 모드가 검사하되, 거부(RAISE) 대신 격리(UNGROUNDED +
-- REVIEW_REQUIRED)한다 — 계획서 §4.4 "거부가 아니라 격리". 기본 모드는 E3 이므로
-- 운영 경로의 보장은 E1 의 상위 집합이다.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 열거형
-- ---------------------------------------------------------------------------

-- 계획서 §3 표 1 / 작업분배 B5. 절제 실험의 4조건.
CREATE TYPE evidence_mode AS ENUM (
  'P',   -- 강제 없음(프롬프트 지시만). 하한선
  'E1',  -- 근거 좌표가 존재한다 (구 field_value_evidence_required_ck 와 같은 명제)
  'E2',  -- 근거 스팬 텍스트가 값을 문자열 수준에서 뒷받침한다 (EXACT · SUBSTRING)
  'E3'   -- E2 + 선언된 파생 규칙(FORMAT · GLOSSARY · SIMILARITY)으로 유도 가능하면 인정
);

-- 계획서 §4.2. "어떻게든 맞으면 통과"가 아니라 선언된 파생 규칙 중 하나로만 통과한다.
CREATE TYPE evidence_derivation AS ENUM (
  'EXACT',       -- 정규화 후 완전 일치
  'SUBSTRING',   -- 정규화한 스팬 텍스트에 포함
  'FORMAT',      -- 날짜·수량 포맷 정규화(evidence_format_rule) 후 일치
  'GLOSSARY',    -- 표준 용어사전(glossary_alias)의 별칭을 거쳐 일치
  'SIMILARITY',  -- 근거 역추적(§4.6) trigram 유사도 ≥ θ. θ 는 실험 전 고정(A5)
  'NONE'         -- 파생 없음 (E1 통과 · 격리)
);

CREATE TYPE evidence_status AS ENUM ('GROUNDED', 'DERIVED', 'UNGROUNDED');

-- ---------------------------------------------------------------------------
-- B5  모드 스위치 — 단일 행 설정
--
-- 실험기(A6)는 이 한 값만 바꿔 가며 같은 DB 에 값을 넣는다. 트리거는 매 행마다
-- 이 값을 읽고 판정에 쓴 모드를 행(field_value.evidence_mode)에 남긴다.
-- ---------------------------------------------------------------------------
CREATE TABLE evidence_enforcement_config (
  singleton           boolean PRIMARY KEY DEFAULT true,
  mode                evidence_mode NOT NULL DEFAULT 'E3',
  -- §4.6 근거 역추적 임계값 θ. 검수 100건으로 A5 가 정한다 (작업분배).
  reattach_threshold  numeric(4,3) NOT NULL DEFAULT 0.800,
  -- 역추적 시 살펴볼 시작 토큰 후보 수 (word_similarity 상위 N)
  reattach_candidates integer NOT NULL DEFAULT 20,
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_enforcement_config_singleton_ck CHECK (singleton),
  CONSTRAINT evidence_enforcement_config_threshold_ck
    CHECK (reattach_threshold BETWEEN 0 AND 1),
  CONSTRAINT evidence_enforcement_config_candidates_ck CHECK (reattach_candidates >= 1)
);

INSERT INTO evidence_enforcement_config DEFAULT VALUES;

CREATE TRIGGER evidence_enforcement_config_set_updated_at
  BEFORE UPDATE ON evidence_enforcement_config FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE FUNCTION current_evidence_mode() RETURNS evidence_mode
LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT mode FROM evidence_enforcement_config), 'E3'::evidence_mode);
$$;

CREATE FUNCTION set_evidence_mode(p_mode evidence_mode) RETURNS evidence_mode
LANGUAGE sql AS $$
  UPDATE evidence_enforcement_config SET mode = p_mode RETURNING mode;
$$;

CREATE FUNCTION set_evidence_reattach_threshold(p_theta numeric) RETURNS numeric
LANGUAGE sql AS $$
  UPDATE evidence_enforcement_config SET reattach_threshold = p_theta RETURNING reattach_threshold;
$$;

COMMENT ON TABLE evidence_enforcement_config IS
  '작업분배 B5 모드 스위치. P·E1·E2·E3 를 set_evidence_mode() 로 전환한다';

-- ---------------------------------------------------------------------------
-- 정규화
--
-- 대소문자·공백·구두점을 모두 버리고 영숫자·한글만 남긴다. 값과 토큰 양쪽에 같은
-- 함수를 적용하므로 "KR PUS" 와 "KRPUS", "1,234.50" 과 "1234.50" 이 같아진다.
-- 문자 자체가 다른 변형(12 AUG 2026 vs 2026-08-12, KGS vs KGM)은 여기서 같아지지
-- 않는다 — 그것은 E3 의 FORMAT · GLOSSARY 파생이 맡는다.
-- ---------------------------------------------------------------------------
CREATE FUNCTION evidence_norm(p text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT regexp_replace(upper(p), '[^0-9A-Z가-힣]+', '', 'g');
$$;

COMMENT ON FUNCTION evidence_norm(text) IS
  '근거 대조용 정규화. document_token.norm_text 스냅샷과 값 대조에 같이 쓴다';

-- ---------------------------------------------------------------------------
-- B1  document_token — OCR 토큰 계층의 영속화 (계획서 §4.1 요건 1)
--
-- 저장 계층이 "이 값의 좌표" 뿐 아니라 "그 좌표 안에 무엇이 쓰여 있었는가"를
-- 물어볼 수 있어야 내용 검증이 가능하다. 실험 불변식(§5): 이 표는 OCR 엔진 실행
-- 결과로만 채우고, 데이터셋 라벨은 오라클로만 쓴다.
-- ---------------------------------------------------------------------------
CREATE TABLE document_token (
  document_id    uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  page           integer NOT NULL,
  idx            integer NOT NULL,          -- 페이지 내 읽기 순서 (center_y, x_min), 0부터 연속
  text           text NOT NULL,
  norm_text      text NOT NULL DEFAULT '',  -- evidence_norm(text) 스냅샷(트리거가 채움). 규칙이 바뀌어도 과거 판정 근거 보존
  -- 기획안 5.1 과 같이 이미지 너비/높이 대비 0~1 비율
  bbox_x1        numeric(8,5) NOT NULL,
  bbox_y1        numeric(8,5) NOT NULL,
  bbox_x2        numeric(8,5) NOT NULL,
  bbox_y2        numeric(8,5) NOT NULL,
  ocr_confidence numeric(4,3),
  PRIMARY KEY (document_id, page, idx),
  CONSTRAINT document_token_page_ck CHECK (page >= 1),
  CONSTRAINT document_token_idx_ck CHECK (idx >= 0),
  CONSTRAINT document_token_bbox_ck CHECK (
    bbox_x1 < bbox_x2 AND bbox_y1 < bbox_y2
    AND bbox_x1 >= 0 AND bbox_y1 >= 0 AND bbox_x2 <= 1 AND bbox_y2 <= 1
  ),
  CONSTRAINT document_token_confidence_ck
    CHECK (ocr_confidence IS NULL OR ocr_confidence BETWEEN 0 AND 1)
);

-- §4.6 근거 역추적: 좌표 없는 값을 norm_text 로 trigram 검색
CREATE INDEX document_token_norm_trgm ON document_token USING gin (norm_text gin_trgm_ops);

-- norm_text 는 항상 이 DB 의 evidence_norm() 으로 채운다. 적재기(A2)가 넘긴 값은
-- 무시한다 — 두 곳에서 정규화하면 스냅샷의 재현성이 깨진다.
CREATE FUNCTION fn_document_token_norm() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.norm_text := evidence_norm(NEW.text);
  RETURN NEW;
END;
$$;

CREATE TRIGGER document_token_norm
  BEFORE INSERT OR UPDATE OF text ON document_token
  FOR EACH ROW EXECUTE FUNCTION fn_document_token_norm();

COMMENT ON TABLE document_token IS
  '계획서 §4.1 OCR 토큰 계층. OCR 엔진 출력만 적재한다(라벨 적재 금지 — 오라클 오염)';

-- ---------------------------------------------------------------------------
-- B1  field_value — 값·근거 결속 컬럼 (계획서 §4.2 요건 2)
-- ---------------------------------------------------------------------------
ALTER TABLE field_value
  -- 파서가 값과 함께 넘기는 출처 계층 (논문초안 v3.2 §2). 지표를 계층별로 나눌 때 쓴다.
  ADD COLUMN source_layer        text,
  -- 근거 스팬: document_token(document_id, page, [from, to)) — half-open
  ADD COLUMN evidence_token_from integer,
  ADD COLUMN evidence_token_to   integer,
  -- 트리거가 채우는 판정. 쓰기 경로가 넣은 값은 트리거가 덮어쓴다.
  ADD COLUMN derivation          evidence_derivation,
  ADD COLUMN evidence_status     evidence_status,
  ADD COLUMN evidence_mode       evidence_mode,
  ADD COLUMN evidence_reason     text,
  -- §4.5 면제 조항 봉인: "사람이 편집했다"는 주장은 실제 행위자를 동반해야 한다.
  ADD COLUMN edited_by           uuid REFERENCES app_user(id),
  ADD CONSTRAINT field_value_source_layer_ck
    CHECK (source_layer IS NULL OR source_layer IN ('REGION', 'ANCHOR', 'LLM')),
  ADD CONSTRAINT field_value_evidence_span_ck CHECK (
    num_nulls(evidence_token_from, evidence_token_to) IN (0, 2)
    AND (evidence_token_from IS NULL
         OR (evidence_token_from >= 0 AND evidence_token_to > evidence_token_from))
  );

-- E1(좌표 존재)의 검사는 트리거의 E1 모드로 옮긴다. 파일 머리말 참고.
ALTER TABLE field_value DROP CONSTRAINT field_value_evidence_required_ck;

-- §4.5 요건 3: 면제 조항은 자동 경로가 충족할 수 없는 외부 사실(행위자)을 요구한다.
-- NOT VALID 로 추가해도 새로 쓰는 행에는 즉시 적용된다. 기존 행은 감사 로그의
-- 행위자로 백필한 뒤 VALIDATE 를 시도한다.
ALTER TABLE field_value ADD CONSTRAINT field_value_manual_actor_ck
  CHECK (extractor <> 'MANUAL' OR edited_by IS NOT NULL) NOT VALID;

UPDATE field_value fv
SET edited_by = a.actor_id
FROM (
  SELECT DISTINCT ON (entity_id) entity_id, actor_id
  FROM audit_log
  WHERE entity_type = 'field_value' AND actor_id IS NOT NULL
  ORDER BY entity_id, occurred_at DESC
) a
WHERE fv.id = a.entity_id AND fv.extractor = 'MANUAL' AND fv.edited_by IS NULL;

DO $$
BEGIN
  ALTER TABLE field_value VALIDATE CONSTRAINT field_value_manual_actor_ck;
EXCEPTION WHEN check_violation THEN
  -- 백필로 채울 수 없는 과거 MANUAL 행이 남아 있다. 제약은 NOT VALID 상태로도
  -- 새 쓰기를 막으므로 마이그레이션을 실패시키지 않고 경고만 남긴다.
  RAISE WARNING 'field_value_manual_actor_ck: 행위자 없는 기존 MANUAL 행이 있어 VALIDATE 를 보류합니다';
END;
$$;

CREATE INDEX field_value_evidence_status_idx ON field_value (shipment_id, evidence_status)
  WHERE evidence_status = 'UNGROUNDED';

COMMENT ON COLUMN field_value.evidence_token_from IS '근거 스팬 시작 idx (document_token, 같은 document_id·page). half-open [from, to)';
COMMENT ON COLUMN field_value.evidence_reason IS '격리 사유 코드 또는 통과 비고(REATTACHED sim=… · SPAN_FROM_BBOX)';
COMMENT ON CONSTRAINT field_value_manual_actor_ck ON field_value IS
  '계획서 §4.5 면제 조항 봉인: 수동 입력 주장은 행위자 식별자를 동반해야 한다';

-- ---------------------------------------------------------------------------
-- B2  변환 규칙표 — FORMAT 파생이 인정하는 표기 목록
--
-- 결과를 본 뒤에는 바꾸지 않는다 (작업분배 "하지 말 것" 3번). 날짜는 to_date 포맷
-- 문자열이고, 순서대로 시도해 왕복(to_char) 이 원문과 일치하는 첫 해석을 취한다.
-- ---------------------------------------------------------------------------
CREATE TABLE evidence_format_rule (
  data_type text NOT NULL,
  ordinal   integer NOT NULL,
  pattern   text NOT NULL,
  note      text,
  PRIMARY KEY (data_type, ordinal),
  CONSTRAINT evidence_format_rule_type_ck CHECK (data_type IN ('date', 'number'))
);

INSERT INTO evidence_format_rule (data_type, ordinal, pattern, note) VALUES
  ('date',  1, 'YYYY-MM-DD',     'ISO 8601'),
  ('date',  2, 'DD MON YYYY',    '12 AUG 2026 — B/L 관행'),
  ('date',  3, 'MON DD YYYY',    'AUG 12 2026'),
  ('date',  4, 'MON DD, YYYY',   'AUG 12, 2026'),
  ('date',  5, 'DD-MON-YYYY',    '12-AUG-2026'),
  ('date',  6, 'DD MONTH YYYY',  '12 AUGUST 2026'),
  ('date',  7, 'MONTH DD, YYYY', 'AUGUST 12, 2026'),
  ('date',  8, 'YYYY/MM/DD',     '2026/08/12'),
  ('date',  9, 'DD/MM/YYYY',     '12/08/2026 — 영국식. MM/DD 는 모호하여 두지 않는다'),
  ('date', 10, 'DD.MM.YYYY',     '12.08.2026'),
  ('date', 11, 'YYYYMMDD',       '20260812'),
  ('number', 1, '[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?',
     '천 단위 구분자 쉼표, 소수점 마침표. 단위(KGS·KGM 등)는 무시하고 수치만 비교한다');

COMMENT ON TABLE evidence_format_rule IS
  '작업분배 B2 변환 규칙표. 실험 결과를 본 뒤 수정 금지';

-- 숫자 앞 0 무시 비교용 ("01 AUG" ≡ "1 AUG")
CREATE FUNCTION evidence_strip_leading_zeros(p text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
  SELECT regexp_replace(p, '(^|[^0-9])0+([0-9])', '\1\2', 'g');
$$;

-- 규칙표의 날짜 포맷을 순서대로 시도한다. 왕복이 원문과 일치해야 채택한다 —
-- to_date 는 관대해서 엉뚱한 포맷으로도 값을 내놓을 수 있기 때문이다.
CREATE FUNCTION evidence_parse_date(p text) RETURNS date
LANGUAGE plpgsql STABLE AS $$
DECLARE
  s text := btrim(p);
  r record;
  d date;
BEGIN
  IF s IS NULL OR s = '' THEN
    RETURN NULL;
  END IF;
  FOR r IN SELECT pattern FROM evidence_format_rule WHERE data_type = 'date' ORDER BY ordinal LOOP
    BEGIN
      d := to_date(s, r.pattern);
      IF evidence_strip_leading_zeros(evidence_norm(to_char(d, r.pattern)))
         = evidence_strip_leading_zeros(evidence_norm(s)) THEN
        RETURN d;
      END IF;
    EXCEPTION WHEN OTHERS THEN
      NULL;  -- 이 포맷이 아님. 다음 규칙
    END;
  END LOOP;
  RETURN NULL;
END;
$$;

-- 첫 번째 수치 리터럴 (값 쪽)
CREATE FUNCTION evidence_parse_number(p text) RETURNS numeric
LANGUAGE sql STABLE STRICT AS $$
  SELECT replace((regexp_match(p, (SELECT pattern FROM evidence_format_rule
                                   WHERE data_type = 'number' AND ordinal = 1)))[1], ',', '')::numeric;
$$;

-- 스팬에 등장하는 모든 수치 리터럴 (스팬 쪽)
CREATE FUNCTION evidence_numbers(p text) RETURNS numeric[]
LANGUAGE sql STABLE STRICT AS $$
  SELECT COALESCE(array_agg(replace(m[1], ',', '')::numeric), '{}')
  FROM regexp_matches(p, (SELECT pattern FROM evidence_format_rule
                          WHERE data_type = 'number' AND ordinal = 1), 'g') m;
$$;

-- GLOSSARY 파생: 값의 정규화 키가 가리키는 용어의 다른 표기가 스팬 안에 있는가.
-- glossary_alias.normalized_key 는 evidence_norm(alias_text) 로 적재한다
-- (20_evidence_glossary_seed.sql). 표준 사전과 해당 테넌트의 조직 사전만 본다.
CREATE FUNCTION evidence_glossary_match(p_value_norm text, p_span_norm text, p_tenant_id uuid)
RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM glossary_alias v
    JOIN glossary_term t ON t.id = v.term_id
    JOIN glossary_alias s ON s.term_id = v.term_id
    WHERE v.normalized_key = p_value_norm
      AND t.is_active
      AND (t.scope = 'STANDARD' OR t.tenant_id = p_tenant_id)
      AND s.normalized_key <> ''
      AND position(s.normalized_key IN p_span_norm) > 0
  );
$$;

-- 스팬 [from, to) 의 원문·정규화 텍스트와 실제 토큰 수
CREATE FUNCTION evidence_span_text(
  p_document_id uuid, p_page integer, p_from integer, p_to integer,
  OUT raw_text text, OUT norm_text text, OUT token_count integer
)
LANGUAGE sql STABLE AS $$
  SELECT string_agg(t.text, ' ' ORDER BY t.idx),
         string_agg(t.norm_text, '' ORDER BY t.idx),
         count(*)::integer
  FROM document_token t
  WHERE t.document_id = p_document_id AND t.page = p_page
    AND t.idx >= p_from AND t.idx < p_to;
$$;

-- §4.4 격리: 삭제하지 않고 사람 검토 등급으로 강등한다. 대표값 자격은 유지한다 —
-- 박탈하면 "대표값 중 확인 필요"를 조건으로 삼는 검토 큐에서도 사라진다.
CREATE FUNCTION evidence_quarantine(r field_value, p_reason text) RETURNS field_value
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  r.evidence_status := 'UNGROUNDED';
  r.derivation := 'NONE';
  r.evidence_reason := p_reason;
  r.grade := 'REVIEW_REQUIRED';
  RETURN r;
END;
$$;

-- ---------------------------------------------------------------------------
-- B3  검증 트리거 — Algorithm 1 (계획서 §4.3)
--
-- CHECK 는 같은 행 밖을 볼 수 없다. 내용 검증은 document_token 조회가 필수이므로
-- BEFORE INSERT OR UPDATE 트리거로 쓴다.
--
--   0. 판정 컬럼은 쓰기 경로가 정할 수 없다 — 항상 여기서 다시 계산한다
--   1. 면제: MANUAL(행위자 필수) · JSON(구조화 입력) · NOT_FOUND(값 없음)
--   E1  좌표(document_id·page·bbox 또는 스팬)가 존재하면 GROUNDED/NONE
--   E2·E3
--   2. 스팬 확보: 명시 스팬 → bbox 기하로 도출 → §4.6 역추적(trigram, θ)
--   3. span_text := document_token [from, to) 연결
--   4. norm(value) 대조: EXACT · SUBSTRING → GROUNDED
--      (E3 만) FORMAT · GLOSSARY · SIMILARITY → DERIVED
--   5. 그 외 → UNGROUNDED: REVIEW_REQUIRED 로 강등 + 사유 기록 (대표값 자격 유지)
-- ---------------------------------------------------------------------------
CREATE FUNCTION fn_field_value_enforce_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  cfg         evidence_enforcement_config%ROWTYPE;
  v_mode      evidence_mode;
  v_norm      text;
  v_data_type text;
  v_note      text := NULL;
  v_from      integer;
  v_to        integer;
  span        record;
  -- §4.6 역추적
  n_words     integer;
  cand        record;
  win_len     integer;
  win_norm    text;
  sim         real;
  best_sim    real := 0;
  best_page   integer;
  best_from   integer;
  best_to     integer;
  -- FORMAT
  v_date      date;
  win_raw     text;
  i           integer;
  matched     boolean := false;
BEGIN
  IF TG_OP = 'UPDATE' AND NOT (
       NEW.value              IS DISTINCT FROM OLD.value
    OR NEW.document_id        IS DISTINCT FROM OLD.document_id
    OR NEW.page               IS DISTINCT FROM OLD.page
    OR NEW.bbox_x1            IS DISTINCT FROM OLD.bbox_x1
    OR NEW.bbox_y1            IS DISTINCT FROM OLD.bbox_y1
    OR NEW.bbox_x2            IS DISTINCT FROM OLD.bbox_x2
    OR NEW.bbox_y2            IS DISTINCT FROM OLD.bbox_y2
    OR NEW.evidence_token_from IS DISTINCT FROM OLD.evidence_token_from
    OR NEW.evidence_token_to  IS DISTINCT FROM OLD.evidence_token_to
    OR NEW.extractor          IS DISTINCT FROM OLD.extractor
    OR NEW.grade              IS DISTINCT FROM OLD.grade
    OR NEW.edited_by          IS DISTINCT FROM OLD.edited_by
  ) THEN
    -- 근거와 무관한 갱신(대표값 전환 등). 판정은 손대지 않고, 손댈 수도 없다.
    NEW.evidence_status := OLD.evidence_status;
    NEW.derivation      := OLD.derivation;
    NEW.evidence_mode   := OLD.evidence_mode;
    NEW.evidence_reason := OLD.evidence_reason;
    RETURN NEW;
  END IF;

  SELECT * INTO cfg FROM evidence_enforcement_config;
  v_mode := COALESCE(cfg.mode, 'E3');
  NEW.evidence_mode   := v_mode;
  NEW.evidence_status := NULL;
  NEW.derivation      := NULL;
  NEW.evidence_reason := NULL;

  -- P: 강제 없음. 값이 무엇이든 그대로 저장되고 신뢰 뷰에 나온다 (실험 하한선).
  IF v_mode = 'P' THEN
    RETURN NEW;
  END IF;

  -- 1. 면제 — 좌표 개념이 없는 입력. MANUAL 은 field_value_manual_actor_ck 가 행위자를 요구한다.
  IF NEW.extractor IN ('MANUAL', 'JSON') THEN
    NEW.evidence_reason := 'EXEMPT_' || NEW.extractor::text;
    RETURN NEW;
  END IF;
  IF NEW.grade = 'NOT_FOUND' THEN
    NEW.evidence_reason := 'NOT_FOUND';
    RETURN NEW;
  END IF;
  IF NEW.value IS NULL THEN
    NEW := evidence_quarantine(NEW, 'NO_VALUE');
    RETURN NEW;
  END IF;

  -- E1: 근거 좌표가 존재한다 — 구 CHECK 와 같은 명제, 내용은 보지 않는다.
  IF v_mode = 'E1' THEN
    IF NEW.document_id IS NOT NULL AND NEW.page IS NOT NULL
       AND (NEW.bbox_x1 IS NOT NULL OR NEW.evidence_token_from IS NOT NULL) THEN
      NEW.evidence_status := 'GROUNDED';
      NEW.derivation      := 'NONE';
      NEW.evidence_reason := 'COORDS_PRESENT';
      RETURN NEW;
    END IF;
    NEW := evidence_quarantine(NEW, 'NO_COORDS');
    RETURN NEW;
  END IF;

  -- E2 · E3: 내용 검증
  IF NEW.document_id IS NULL THEN
    NEW := evidence_quarantine(NEW, 'NO_DOCUMENT');
    RETURN NEW;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM document_token WHERE document_id = NEW.document_id) THEN
    -- 토큰 계층이 없으면 검증할 수 없다. 통과가 아니라 격리 (정직성 규약).
    NEW := evidence_quarantine(NEW, 'NO_TOKEN_LAYER');
    RETURN NEW;
  END IF;

  v_norm := evidence_norm(NEW.value);
  IF v_norm = '' THEN
    NEW := evidence_quarantine(NEW, 'EMPTY_VALUE');
    RETURN NEW;
  END IF;

  -- 2a. 스팬이 없고 bbox 만 있으면(기존 파이프라인 경로) 중심점이 bbox 안에 드는 토큰으로 도출
  IF NEW.evidence_token_from IS NULL AND NEW.bbox_x1 IS NOT NULL AND NEW.page IS NOT NULL THEN
    SELECT min(idx), max(idx) + 1 INTO v_from, v_to
    FROM document_token
    WHERE document_id = NEW.document_id AND page = NEW.page
      AND (bbox_x1 + bbox_x2) / 2 BETWEEN NEW.bbox_x1 AND NEW.bbox_x2
      AND (bbox_y1 + bbox_y2) / 2 BETWEEN NEW.bbox_y1 AND NEW.bbox_y2;
    IF v_from IS NOT NULL THEN
      NEW.evidence_token_from := v_from;
      NEW.evidence_token_to   := v_to;
      v_note := 'SPAN_FROM_BBOX';
    END IF;
  END IF;

  -- 2b. §4.6 근거 역추적 — 좌표 없는 값(LLM 갭필)을 토큰 계층에서 되찾는다
  IF NEW.evidence_token_from IS NULL THEN
    n_words := COALESCE(array_length(regexp_split_to_array(btrim(NEW.value), '\s+'), 1), 1);
    FOR cand IN
      SELECT page, idx
      FROM document_token
      WHERE document_id = NEW.document_id AND norm_text <> ''
      ORDER BY word_similarity(norm_text, v_norm) DESC, page, idx
      LIMIT cfg.reattach_candidates
    LOOP
      FOR win_len IN 1 .. n_words + 1 LOOP
        SELECT string_agg(norm_text, '' ORDER BY idx) INTO win_norm
        FROM document_token
        WHERE document_id = NEW.document_id AND page = cand.page
          AND idx >= cand.idx AND idx < cand.idx + win_len;
        sim := similarity(win_norm, v_norm);
        IF sim > best_sim THEN
          best_sim  := sim;
          best_page := cand.page;
          best_from := cand.idx;
          best_to   := cand.idx + win_len;
        END IF;
      END LOOP;
    END LOOP;

    IF best_sim >= cfg.reattach_threshold THEN
      NEW.page                := best_page;
      NEW.evidence_token_from := best_from;
      NEW.evidence_token_to   := best_to;
      v_note := format('REATTACHED sim=%s', round(best_sim::numeric, 3));
    ELSE
      NEW := evidence_quarantine(NEW, format('NO_EVIDENCE_SPAN best_sim=%s', round(best_sim::numeric, 3)));
    RETURN NEW;
    END IF;
  END IF;

  IF NEW.page IS NULL THEN
    NEW := evidence_quarantine(NEW, 'NO_PAGE');
    RETURN NEW;
  END IF;

  -- 3. span_text
  SELECT * INTO span
  FROM evidence_span_text(NEW.document_id, NEW.page, NEW.evidence_token_from, NEW.evidence_token_to);
  IF COALESCE(span.token_count, 0) = 0
     OR span.token_count <> NEW.evidence_token_to - NEW.evidence_token_from THEN
    -- 스팬이 가리키는 토큰이 (일부) 없다 = 좌표 날조 후보
    NEW := evidence_quarantine(NEW, 'SPAN_NOT_FOUND');
    RETURN NEW;
  END IF;

  -- 사람 검토 화면용 bbox 보완: 스팬 토큰들의 합집합
  IF NEW.bbox_x1 IS NULL THEN
    SELECT min(bbox_x1), min(bbox_y1), max(bbox_x2), max(bbox_y2)
    INTO NEW.bbox_x1, NEW.bbox_y1, NEW.bbox_x2, NEW.bbox_y2
    FROM document_token
    WHERE document_id = NEW.document_id AND page = NEW.page
      AND idx >= NEW.evidence_token_from AND idx < NEW.evidence_token_to;
  END IF;

  -- 4. 대조 — 선언된 파생 규칙 순서: EXACT ≺ SUBSTRING ≺ FORMAT ≺ GLOSSARY ≺ SIMILARITY
  SELECT data_type INTO v_data_type FROM field_definition WHERE code = NEW.field_code;

  IF v_norm = span.norm_text THEN
    NEW.derivation := 'EXACT';       NEW.evidence_status := 'GROUNDED';
  ELSIF v_data_type NOT IN ('number', 'date') AND position(v_norm IN span.norm_text) > 0 THEN
    -- 수치·날짜는 부분 문자열로 뒷받침되지 않는다 ("12" ⊂ "1234"). EXACT 아니면 FORMAT 으로만 통과한다.
    NEW.derivation := 'SUBSTRING';   NEW.evidence_status := 'GROUNDED';
  ELSIF v_mode = 'E3' THEN
    IF v_data_type = 'date' THEN
      v_date := evidence_parse_date(NEW.value);
      IF v_date IS NOT NULL THEN
        -- 스팬 안의 1~4 토큰 창 중 같은 날짜로 읽히는 것이 있는가 ("DATE OF ISSUE 12 AUG 2026")
        FOR i IN NEW.evidence_token_from .. NEW.evidence_token_to - 1 LOOP
          FOR win_len IN 1 .. LEAST(4, NEW.evidence_token_to - i) LOOP
            SELECT string_agg(text, ' ' ORDER BY idx) INTO win_raw
            FROM document_token
            WHERE document_id = NEW.document_id AND page = NEW.page
              AND idx >= i AND idx < i + win_len;
            IF evidence_parse_date(win_raw) = v_date THEN
              matched := true;
              EXIT;
            END IF;
          END LOOP;
          EXIT WHEN matched;
        END LOOP;
      END IF;
    ELSIF v_data_type = 'number' THEN
      matched := evidence_parse_number(NEW.value) IS NOT NULL
                 AND evidence_parse_number(NEW.value) = ANY (evidence_numbers(span.raw_text));
    END IF;

    IF matched THEN
      NEW.derivation := 'FORMAT';     NEW.evidence_status := 'DERIVED';
    ELSIF evidence_glossary_match(v_norm, span.norm_text, NEW.tenant_id) THEN
      NEW.derivation := 'GLOSSARY';   NEW.evidence_status := 'DERIVED';
    ELSIF similarity(v_norm, span.norm_text) >= cfg.reattach_threshold THEN
      NEW.derivation := 'SIMILARITY'; NEW.evidence_status := 'DERIVED';
    ELSE
      NEW := evidence_quarantine(NEW, 'CONTENT_MISMATCH');
    RETURN NEW;
    END IF;
  ELSE
    NEW := evidence_quarantine(NEW, 'CONTENT_MISMATCH');
    RETURN NEW;
  END IF;

  NEW.evidence_reason := v_note;
  RETURN NEW;
END;
$$;

CREATE TRIGGER field_value_enforce_evidence
  BEFORE INSERT OR UPDATE ON field_value
  FOR EACH ROW EXECUTE FUNCTION fn_field_value_enforce_evidence();

COMMENT ON FUNCTION fn_field_value_enforce_evidence() IS
  '계획서 §4.3 Algorithm 1. 저장 시점에 값이 근거 스팬 텍스트로부터 유도 가능한지 검증하고, 아니면 격리한다';

-- ---------------------------------------------------------------------------
-- B4  신뢰 뷰 · 검토 큐 — 사람에게는 보이고 기계에는 안 보이게 (계획서 §4.4)
--
-- 룰 엔진·리포트·재학습은 field_value 가 아니라 field_value_trusted 를 읽는다.
-- 격리값은 field_value 에 남아 검토 큐(사람)에는 보인다.
-- ---------------------------------------------------------------------------
CREATE VIEW field_value_trusted AS
  SELECT * FROM field_value
  WHERE evidence_status IS DISTINCT FROM 'UNGROUNDED';

CREATE VIEW field_value_review_queue AS
  SELECT * FROM field_value
  WHERE is_representative
    AND (evidence_status = 'UNGROUNDED' OR grade IN ('REVIEW_REQUIRED', 'REVIEW_SUGGESTED'));

COMMENT ON VIEW field_value_trusted IS
  '계획서 §4.4 기계 소비 경로(룰 엔진·리포트·재학습)용. UNGROUNDED 는 나오지 않는다';
COMMENT ON VIEW field_value_review_queue IS
  '계획서 §4.4 사람 검토 경로. 격리값은 대표값 자격을 유지하므로 여기에 남는다';

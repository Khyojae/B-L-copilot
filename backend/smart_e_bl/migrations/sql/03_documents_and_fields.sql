-- ============================================================================
-- F1 서류 인테이크 · 필드 값 (근거 보유)
-- 근거: 기획안 5.1
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 비동기 인테이크 잡 (기획안 5.1: 업로드 즉시 job_id 반환, 진행 상태 폴링)
-- ---------------------------------------------------------------------------
CREATE TABLE ingest_job (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id      uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id    uuid REFERENCES shipment(id) ON DELETE CASCADE,
  status         job_status NOT NULL DEFAULT 'QUEUED',
  progress       smallint NOT NULL DEFAULT 0,
  error_code     text,
  error_message  text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  started_at     timestamptz,
  finished_at    timestamptz,
  CONSTRAINT ingest_job_progress_ck CHECK (progress BETWEEN 0 AND 100),
  -- 실패 상태에는 사유 코드가 있어야 한다(기획안 5.1: 사유 코드와 함께 실패 처리)
  CONSTRAINT ingest_job_error_ck CHECK (status <> 'FAILED' OR error_code IS NOT NULL)
);

CREATE INDEX ingest_job_shipment_idx ON ingest_job (shipment_id, created_at DESC);
CREATE INDEX ingest_job_pending_idx ON ingest_job (status, created_at)
  WHERE status IN ('QUEUED', 'EXTRACTING');

-- ---------------------------------------------------------------------------
-- document
-- ---------------------------------------------------------------------------
CREATE TABLE document (
  id                uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id         uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id       uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
  ingest_job_id     uuid REFERENCES ingest_job(id) ON DELETE SET NULL,
  doc_type          document_type NOT NULL,
  source            document_source NOT NULL DEFAULT 'UPLOAD',

  original_filename text,
  mime_type         text,
  byte_size         bigint,
  page_count        integer,
  -- 기획안 5.1: 파일 해시로 중복 검출, 개정본이면 버전으로 누적
  file_hash         text NOT NULL,
  storage_uri       text,

  version           integer NOT NULL DEFAULT 1,
  supersedes_id     uuid REFERENCES document(id) ON DELETE SET NULL,

  -- 기획안 5.1: "한 파일에 여러 서류가 섞인 경우 페이지 단위로 분할·재분류한다."
  -- 업로드 파일 1개가 서류 N건이 되므로, 이 서류가 원본 파일의 몇 페이지를
  -- 차지하는지 기록한다. 분할하지 않은 경우 1 ~ page_count 이다.
  source_page_from  integer NOT NULL DEFAULT 1,
  source_page_to    integer,

  uploaded_by       uuid REFERENCES app_user(id),
  created_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT document_byte_size_ck CHECK (byte_size IS NULL OR byte_size <= 30 * 1024 * 1024),
  CONSTRAINT document_version_ck CHECK (version >= 1),
  CONSTRAINT document_page_count_ck CHECK (page_count IS NULL OR page_count >= 1),
  CONSTRAINT document_source_page_ck CHECK (
    source_page_from >= 1
    AND (source_page_to IS NULL OR source_page_to >= source_page_from)
  )
);

-- ingest_job 정리(오래된 잡 삭제) 시 SET NULL 검사가 타는 인덱스
CREATE INDEX document_ingest_job_idx ON document (ingest_job_id)
  WHERE ingest_job_id IS NOT NULL;

-- 같은 선적에 같은 파일의 같은 구간을 다시 올리면 중복이다(기획안 5.1 재업로드 처리).
-- 페이지 구간을 키에 포함해야 한 파일을 여러 서류로 분할하는 경로가 막히지 않는다.
CREATE UNIQUE INDEX document_shipment_hash_uk
  ON document (shipment_id, file_hash, source_page_from);
CREATE INDEX document_shipment_type_idx ON document (shipment_id, doc_type, version DESC);

COMMENT ON CONSTRAINT document_byte_size_ck ON document
  IS '기획안 5.1 업로드 제한: 파일당 30MB';

-- ---------------------------------------------------------------------------
-- field_definition — B/L 표준 필드 카탈로그
--
-- 두 가지 역할을 겸한다.
--   1. F1 출력 필드의 마스터 (기획안 5.1 출력 필드 표)
--   2. F5 정합성 그래프의 노드 (기획안 5.5: 노드는 (문서, 필드) 쌍)
-- ---------------------------------------------------------------------------
CREATE TABLE field_definition (
  code             text PRIMARY KEY,          -- 예) 'BL.PORT_OF_DISCHARGE'
  doc_type         document_type NOT NULL,
  field_group      text NOT NULL,             -- 당사자 / 식별번호 / 운송구간 / 화물 / 컨테이너 / 조건·발행
  label_ko         text NOT NULL,
  label_en         text NOT NULL,
  data_type        text NOT NULL DEFAULT 'text',  -- text | date | number | code
  -- 기획안 5.1 주 출처 우선순위. 예) '{LC_MT700,SI}'
  source_priority  document_type[] NOT NULL DEFAULT '{}',
  is_required      boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT field_definition_data_type_ck
    CHECK (data_type IN ('text', 'date', 'number', 'code'))
);

CREATE INDEX field_definition_doc_type_idx ON field_definition (doc_type, field_group);

-- ---------------------------------------------------------------------------
-- field_value — F1·F2 생산 → F3·F5 소비 (기획안 5.8)
--
-- 기획안 5.1 필드 값 객체 구조:
--   value, normalized_value, confidence, source_doc_id, page, bbox,
--   extractor, conflict_flag
-- 그리고 "원문 근거 좌표가 없는 값은 저장하지 않는다(추정 생성 금지 규칙)".
-- 이 규칙을 애플리케이션이 아니라 CHECK 제약으로 강제한다.
-- ---------------------------------------------------------------------------
CREATE TABLE field_value (
  id                uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id         uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id       uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
  field_code        text NOT NULL REFERENCES field_definition(code),

  -- 근거 (source_doc_id, page, bbox)
  document_id       uuid REFERENCES document(id) ON DELETE CASCADE,
  page              integer,
  bbox_x1           numeric(8,5),
  bbox_y1           numeric(8,5),
  bbox_x2           numeric(8,5),
  bbox_y2           numeric(8,5),

  value             text,
  normalized_value  text,           -- F2 교정 결과가 반영되는 자리
  confidence        numeric(4,3),
  grade             confidence_grade NOT NULL,
  extractor         extractor_kind NOT NULL,

  -- 기획안 5.1 다중 출처 충돌: 대표값을 정하되 후보를 폐기하지 않는다.
  is_representative boolean NOT NULL DEFAULT false,
  conflict_flag     boolean NOT NULL DEFAULT false,

  -- 기획안 5.8 판정 재현성: 어느 사전 버전으로 정규화했는지 남긴다.
  glossary_version  text,

  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT field_value_confidence_ck
    CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
  CONSTRAINT field_value_page_ck CHECK (page IS NULL OR page >= 1),
  -- 기획안 5.1: 좌표는 정규화된 비율(이미지 너비/높이 대비)이므로 0~1 범위다.
  CONSTRAINT field_value_bbox_ck CHECK (
    num_nulls(bbox_x1, bbox_y1, bbox_x2, bbox_y2) IN (0, 4)
    AND (bbox_x1 IS NULL OR (
      bbox_x1 < bbox_x2 AND bbox_y1 < bbox_y2
      AND bbox_x1 >= 0 AND bbox_y1 >= 0 AND bbox_x2 <= 1 AND bbox_y2 <= 1
    ))
  ),
  -- 추정 생성 금지: 자동 추출(RULE·OCR_LLM)이 만든 값은 반드시 근거 좌표를 갖는다.
  -- MANUAL(사용자 직접 입력)과 JSON(DCSA 구조화 입력)은 좌표 개념이 없어 제외한다.
  -- NOT_FOUND 는 값이 없는 상태이므로 제외한다.
  CONSTRAINT field_value_evidence_required_ck CHECK (
    extractor IN ('MANUAL', 'JSON')
    OR grade = 'NOT_FOUND'
    OR (document_id IS NOT NULL AND page IS NOT NULL AND bbox_x1 IS NOT NULL)
  ),
  -- 미검출은 값을 갖지 않는다(임의 추정값 표시 금지).
  CONSTRAINT field_value_not_found_ck
    CHECK (grade <> 'NOT_FOUND' OR value IS NULL)
);

-- 한 선적의 한 필드에 대표값은 하나뿐이다. 나머지는 후보로 보존된다.
CREATE UNIQUE INDEX field_value_representative_uk
  ON field_value (shipment_id, field_code) WHERE is_representative;

CREATE INDEX field_value_shipment_field_idx ON field_value (shipment_id, field_code);
CREATE INDEX field_value_document_idx ON field_value (document_id);
-- S3 편집기: 확인이 필요한 필드부터 보여준다.
CREATE INDEX field_value_needs_review_idx ON field_value (shipment_id, grade)
  WHERE grade IN ('REVIEW_REQUIRED', 'REVIEW_SUGGESTED') AND is_representative;

CREATE TRIGGER field_value_set_updated_at
  BEFORE UPDATE ON field_value FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON CONSTRAINT field_value_evidence_required_ck ON field_value
  IS '기획안 5.1 추정 생성 금지 규칙: 원문 근거 좌표가 없는 자동 추출 값은 저장하지 않는다';

-- ============================================================================
-- F4 선제 대응 서류 분석 리포트
-- 근거: 기획안 5.4
--
-- 스냅샷 불변성: 생성된 리포트는 report_id·생성 시각·입력 서류 해시·룰/모델
-- 버전과 함께 고정 저장된다. 이후 서류가 수정되어도 과거 리포트는 변경되지 않으며,
-- 최신 상태와 다르면 열람 시 "이후 N건 변경됨" 배너를 표시한다.
-- ============================================================================

CREATE TABLE report (
  id                   uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id            uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  shipment_id          uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,

  -- 리포트 본문 전체를 고정 저장한다. 참조가 아니라 값으로 굳혀야
  -- 이후 원본이 바뀌어도 리포트가 흔들리지 않는다.
  -- 섹션 ①요약 ②항목별 리스크 ③체크리스트 ④수정 권고 ⑤예상 심사 결과 ⑥부록
  snapshot             jsonb NOT NULL,
  content_hash         text NOT NULL,

  -- 부록 ⑥: 판정에 사용된 룰 카탈로그 버전, 모델 버전, 입력 서류 목록과 해시
  input_document_hashes text[] NOT NULL DEFAULT '{}',
  rule_catalog_version text NOT NULL REFERENCES rule_catalog_version(version),
  model_version        text REFERENCES model_version(version),
  glossary_version     text,
  prediction_id        uuid REFERENCES defect_prediction(id) ON DELETE SET NULL,

  -- ①요약의 수치. 기획안 5.4: 모든 수치는 템플릿이 데이터에서 직접 채우고
  -- LLM 은 이미 채워진 수치를 서술하는 역할만 한다.
  defect_probability   numeric(5,4),
  critical_count       integer NOT NULL DEFAULT 0,
  warning_count        integer NOT NULL DEFAULT 0,
  info_count           integer NOT NULL DEFAULT 0,
  -- 기획안 5.4 예외: 위반이 없을 때 "검사하지 않아서 깨끗한 것"과 구분하기 위해
  -- 검증 범위(적용 룰 수·보류 항목)를 함께 남긴다.
  applied_rule_count   integer NOT NULL DEFAULT 0,
  deferred_count       integer NOT NULL DEFAULT 0,

  -- 한/영 이중 언어 (기획안 10.1: 이번 기간은 리포트 출력만 한/영 지원)
  language             text NOT NULL DEFAULT 'ko',

  pdf_storage_uri      text,
  generated_by         uuid REFERENCES app_user(id),
  generated_at         timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT report_probability_ck
    CHECK (defect_probability IS NULL OR defect_probability BETWEEN 0 AND 1),
  CONSTRAINT report_language_ck CHECK (language IN ('ko', 'en')),
  CONSTRAINT report_counts_ck CHECK (
    critical_count >= 0 AND warning_count >= 0 AND info_count >= 0
    AND applied_rule_count >= 0 AND deferred_count >= 0
  )
);

CREATE INDEX report_shipment_idx ON report (shipment_id, generated_at DESC);
-- defect_prediction 삭제 시 SET NULL 검사가 타는 인덱스
CREATE INDEX report_prediction_idx ON report (prediction_id)
  WHERE prediction_id IS NOT NULL;

-- 스냅샷 불변성을 DB 에서 강제한다. 허용 컬럼(PDF 경로)만 나열하는 화이트리스트
-- 방식이라, 이후 컬럼이 추가되어도 기본값이 "불변"이다. 블랙리스트로 짜면
-- 요약 수치(critical_count 등)처럼 목록에서 빠진 컬럼이 변조 가능해진다.
CREATE FUNCTION report_enforce_immutability() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'pdf_storage_uri') IS DISTINCT FROM (to_jsonb(OLD) - 'pdf_storage_uri')
  THEN
    RAISE EXCEPTION
      '리포트 스냅샷은 불변입니다(기획안 5.4). 새 리포트를 생성하세요. report_id=%', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER report_immutable
  BEFORE UPDATE ON report FOR EACH ROW EXECUTE FUNCTION report_enforce_immutability();

COMMENT ON TRIGGER report_immutable ON report
  IS '기획안 5.4 스냅샷 불변성. 서류가 수정되어도 과거 리포트는 변경되지 않는다';

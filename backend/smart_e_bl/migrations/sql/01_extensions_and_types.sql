-- ============================================================================
-- B/L Copilot — 확장 및 공통 타입
-- 구현 범위: F1 서류 인테이크 · F2 표준 용어 교정 · F3 하자 예측 · F4 리포트
-- 근거: 기획안 5.1~5.4, 5.8
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- F2 별칭 유사도 검색(문자 n-gram)
CREATE EXTENSION IF NOT EXISTS btree_gin; -- 복합 조건 인덱스

-- PostgreSQL 18의 uuidv7() 를 기본 PK 로 사용한다.
-- 시간순 정렬 UUID 라 B-tree 삽입이 말단에 집중되어, uuidv4 대비 인덱스 단편화가 적다.

-- ---------------------------------------------------------------------------
-- 열거형: 값 집합이 닫혀 있고 코드가 분기 조건으로 쓰는 것만 ENUM 으로 둔다.
-- 값이 늘어나는 카탈로그(룰, 용어)는 테이블로 관리한다. (기획안 5.3:
-- "룰은 코드가 아니라 데이터로 관리하여 조문 개정 시 배포 없이 갱신한다")
-- ---------------------------------------------------------------------------

-- 기획안 5.8 선적 상태 전이.
-- SUBMITTED 이후 상태(MONITORING·CLOSED)는 F6·플라이휠 소관이라 이번 범위 밖이지만,
-- 상태 컬럼 하나로 선적의 전 생애를 표현해야 하므로 값은 남긴다.
CREATE TYPE shipment_status AS ENUM (
  'DRAFT', 'REVIEWING', 'VERIFIED', 'SUBMITTED', 'MONITORING', 'CLOSED'
);

-- 기획안 5.3 심각도 정의
CREATE TYPE severity AS ENUM ('CRITICAL', 'WARNING', 'INFO');

-- 기획안 5.1 신뢰도 등급과 휴먼 확인 라우팅
CREATE TYPE confidence_grade AS ENUM (
  'CONFIRMED',        -- 확정: 0.90 이상
  'REVIEW_SUGGESTED', -- 확인 권고: 0.70 이상 0.90 미만
  'REVIEW_REQUIRED',  -- 필수 확인: 0.70 미만 · 스키마 위반 · 출처 간 충돌
  'NOT_FOUND'         -- 미검출: 근거 위치를 찾지 못함
);

-- 기획안 5.1 필드 값 객체 구조의 extractor
CREATE TYPE extractor_kind AS ENUM ('RULE', 'OCR_LLM', 'JSON', 'MANUAL');

CREATE TYPE document_type AS ENUM (
  'BL_DRAFT',            -- B/L 초안(시스템 생성)
  'BL_COPY',             -- 기존 B/L 사본
  'SI',                  -- Shipping Instruction
  'COMMERCIAL_INVOICE',
  'PACKING_LIST',
  'LC_MT700',
  'INSURANCE_POLICY',
  'CERTIFICATE_OF_ORIGIN',
  'EXPORT_DECLARATION',
  'OTHER'
);

CREATE TYPE document_source AS ENUM ('UPLOAD', 'DCSA_JSON', 'MANUAL', 'GENERATED');

-- 기획안 5.1 비동기 처리: 대기·추출중·완료·실패
CREATE TYPE job_status AS ENUM ('QUEUED', 'EXTRACTING', 'DONE', 'FAILED');

CREATE TYPE verdict_status AS ENUM (
  'OPEN',          -- 미해결
  'RESOLVED',      -- 수정으로 해소
  'DEFERRED',      -- 기획안 5.3 "판정 보류"(필수 확인 필드 미처리)
  'ACKNOWLEDGED'   -- Warning 을 사유와 함께 보류
);

-- 기획안 5.2 용어사전 authority
CREATE TYPE glossary_authority AS ENUM (
  'UNLOCODE', 'DCSA', 'ISBP', 'UCP600', 'UNECE_REC20', 'ISO6346',
  'INCOTERMS_2020', 'HS', 'ORGANIZATION'
);

-- 기획안 5.2 계층 구조: 표준 사전 → 조직 사전 → 선적 예외
CREATE TYPE glossary_scope AS ENUM ('STANDARD', 'ORGANIZATION', 'SHIPMENT');

CREATE TYPE suggestion_status AS ENUM ('PROPOSED', 'ACCEPTED', 'REJECTED');

-- 기획안 5.2: 거절 시 사유를 기록해 사전 개선과 조직별 예외 규칙 생성에 사용한다
CREATE TYPE suggestion_reject_reason AS ENUM (
  'INTERNAL_PRACTICE',     -- 사내 관행
  'COUNTERPARTY_REQUEST',  -- 거래처 요구
  'WRONG_SUGGESTION'       -- 오제안
);

-- ---------------------------------------------------------------------------
-- 공통 트리거 함수
-- ---------------------------------------------------------------------------

CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

COMMENT ON FUNCTION set_updated_at() IS 'updated_at 자동 갱신 트리거';

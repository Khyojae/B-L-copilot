-- ============================================================================
-- 테넌트 · 사용자 · 선적
-- 근거: 기획안 6.1 L4 공유 데이터 척추, 5.8 선적 상태 전이
-- ============================================================================

CREATE TABLE tenant (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  code          text NOT NULL UNIQUE,
  name          text NOT NULL,
  -- 기획안 6.1 이중 배포 프로파일. 온프레미스는 외부 링크 공유 비활성화 등
  -- 동작이 갈리므로 데이터에도 남긴다.
  is_onpremise  boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER tenant_set_updated_at
  BEFORE UPDATE ON tenant FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE app_user (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id   uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  email       text NOT NULL,
  name        text NOT NULL,
  role        text NOT NULL DEFAULT 'MEMBER',
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TRIGGER app_user_set_updated_at
  BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- shipment — 전 기능 공통 키 (기획안 5.8)
-- ---------------------------------------------------------------------------
CREATE TABLE shipment (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id           uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  status              shipment_status NOT NULL DEFAULT 'DRAFT',

  -- 식별번호 (기획안 5.1 출력 필드의 식별번호 그룹)
  bl_no               text,
  booking_no          text,
  lc_no               text,
  cargo_control_no    text,   -- 화물관리번호(MRN 계열)

  -- 당사자 (대표값. 필드 단위 근거는 field_value 가 보유한다)
  shipper_name        text,
  consignee_name      text,
  notify_party_name   text,
  carrier_name        text,

  -- 기한 (기획안 F3 R-LC-31D / R-LC-48)
  lc_expiry_date      date,          -- MT700 :31D:
  presentation_period_days integer
    CONSTRAINT shipment_presentation_period_ck CHECK (presentation_period_days IS NULL OR presentation_period_days > 0),  -- MT700 :48:
  latest_shipment_date date,         -- MT700 :44C:
  onboard_date        date,
  submitted_at        timestamptz,

  -- 기획안 5.3 예외: L/C 없는 거래(추심·송금)는 UCP600 계열 룰을 비활성화하고
  -- 하자 확률 대신 "정합성 위험도"로 표기한다.
  has_letter_of_credit boolean NOT NULL DEFAULT true,

  created_by          uuid REFERENCES app_user(id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- 같은 테넌트 안에서 B/L 번호는 유일하다. NULL 은 초안 단계라 중복을 허용한다.
CREATE UNIQUE INDEX shipment_tenant_bl_no_key
  ON shipment (tenant_id, bl_no) WHERE bl_no IS NOT NULL;

CREATE INDEX shipment_tenant_status_idx ON shipment (tenant_id, status, updated_at DESC);

CREATE TRIGGER shipment_set_updated_at
  BEFORE UPDATE ON shipment FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 상태 전이 이력
-- 기획안 5.8: Critical 미해결 시 VERIFIED 로 전이하지 않는다. 사용자는 사유를
-- 기록하고 강제 진행할 수 있으며 이 사유는 리포트와 피드백 데이터에 남는다.
-- ---------------------------------------------------------------------------
CREATE TABLE shipment_status_history (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  shipment_id  uuid NOT NULL REFERENCES shipment(id) ON DELETE CASCADE,
  from_status  shipment_status,
  to_status    shipment_status NOT NULL,
  is_forced    boolean NOT NULL DEFAULT false,
  force_reason text,
  actor_id     uuid REFERENCES app_user(id),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  -- 강제 진행에는 반드시 사유가 있어야 한다.
  CONSTRAINT shipment_status_force_reason_ck
    CHECK (NOT is_forced OR force_reason IS NOT NULL)
);

CREATE INDEX shipment_status_history_shipment_idx
  ON shipment_status_history (shipment_id, occurred_at DESC);

COMMENT ON COLUMN shipment.cargo_control_no IS '화물관리번호(MRN 계열). F6 도입 시 UNI-PASS 조회 키가 된다';

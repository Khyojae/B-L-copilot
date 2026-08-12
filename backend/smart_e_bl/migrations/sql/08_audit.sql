-- ============================================================================
-- 감사 로그
-- 근거: 기획안 5.8 공통 규약
--
-- "필드 변경·승인·거절·리포트 공유는 행위자와 시각을 남긴다
--  (폐쇄망 프로파일의 감사 요건 대응)"
-- ============================================================================

CREATE TABLE audit_log (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  tenant_id    uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  actor_id     uuid REFERENCES app_user(id) ON DELETE SET NULL,
  -- FIELD_UPDATE | SUGGESTION_ACCEPT | SUGGESTION_REJECT | VERDICT_DEFER
  -- | REPORT_GENERATE | STATUS_FORCE ...
  action       text NOT NULL,
  entity_type  text NOT NULL,
  entity_id    uuid,
  shipment_id  uuid REFERENCES shipment(id) ON DELETE SET NULL,
  before_state jsonb,
  after_state  jsonb,
  client_ip    inet,
  occurred_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_tenant_idx ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX audit_log_entity_idx ON audit_log (entity_type, entity_id);
CREATE INDEX audit_log_shipment_idx ON audit_log (shipment_id, occurred_at DESC)
  WHERE shipment_id IS NOT NULL;

COMMENT ON TABLE audit_log IS '기획안 5.8 감사 로그. 폐쇄망 프로파일의 감사 요건 대응';

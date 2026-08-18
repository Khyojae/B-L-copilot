/**
 * B/L Copilot — 공유 도메인 타입
 *
 * 근거: 기획안 v2 §5.1 / §5.2 / §5.5 / §5.6 / §5.8
 * 규약: FE 개발규약 v0.2 §3
 *
 * ⚠ 이 파일은 FE 2인의 공유 정의입니다.
 *   수정 시 반드시 상호 리뷰를 거칩니다. (규약 §6.3)
 */

// ─────────────────────────────────────────────
// 공통 열거형
// ─────────────────────────────────────────────

/** 심각도 3단계 — F3·F6이 공유. 화면 색상·정렬 순서 동일 적용 (§5.8) */
export type Severity = 'Critical' | 'Warning' | 'Info';

/** 선적 상태 6종 — 임의 추가 금지 (§5.8) */
export type ShipmentStatus =
  | 'DRAFT'        // 초안 생성
  | 'REVIEWING'    // 필수 확인 필드 처리 중
  | 'VERIFIED'     // 검증 완료 · Critical 미해결 없음
  | 'SUBMITTED'    // 제출
  | 'MONITORING'   // 현실 대조 중
  | 'CLOSED';      // 결과 기록 완료

/** 필드 신뢰도 등급 (§5.1) */
export type ConfidenceGrade =
  | 'CONFIRMED'   // 확정      — 0.90 이상
  | 'ADVISORY'    // 확인 권고  — 0.70 이상 0.90 미만
  | 'REQUIRED'    // 필수 확인  — 0.70 미만 · 스키마 위반 · 값 충돌
  | 'NOT_FOUND';  // 미검출    — 근거 위치 없음

/** 정정 영향의 담당 당사자 (§5.5) */
export type Party = '화주' | '포워더' | '선사' | '은행' | '관세사';

/** ISO8601 UTC 문자열. 표시 시에만 현지 시간대로 변환 (§5.6) */
export type UtcTimestamp = string;

// ─────────────────────────────────────────────
// F1 — 서류 인테이크 · 초안
// ─────────────────────────────────────────────

/** 원문 근거 좌표 [x0, y0, x1, y1] */
export type BBox = [number, number, number, number];

/**
 * 추출 필드값 (§5.1)
 *
 * ⚠ bbox가 null인 값은 저장·표시하지 않습니다.
 *   추정 생성 금지 원칙 (규약 §2.4)
 */
export interface FieldValue {
  field_name: string;
  value: string | null;
  normalized_value: string | null;
  confidence: number;
  source_doc_id: string | null;
  page: number | null;
  bbox: BBox | null;
  extractor: 'rule' | 'ocr+llm' | 'json';
  conflict_flag: boolean;
  /** 다중 출처 충돌 시 후보를 폐기하지 않고 모두 보존 (§5.1) */
  candidates?: FieldValue[];
}

export type DocumentKind =
  | 'BL'          // 선하증권
  | 'INVOICE'     // 상업송장
  | 'PACKING'     // 포장명세서
  | 'LC'          // 신용장 (MT700)
  | 'SI'          // 선적요청서
  | 'UNKNOWN';

export interface DocumentMeta {
  document_id: string;
  kind: DocumentKind;
  file_name: string;
  file_hash: string;
  page_count: number;
  version: number;
  uploaded_at: UtcTimestamp;
}

/** 비동기 추출 작업 상태 (§5.1) */
export type JobStatus = 'PENDING' | 'EXTRACTING' | 'DONE' | 'FAILED';

export interface Job {
  job_id: string;
  status: JobStatus;
  progress: number | null;
  failure_reason: string | null;
}

// ─────────────────────────────────────────────
// F2 — 표준 용어 교정
// ─────────────────────────────────────────────

/** 교정 근거 출처 (§5.2) */
export type Authority =
  | 'UN/LOCODE'
  | 'UN/ECE Rec 20'
  | 'ISO 6346'
  | 'Incoterms 2020'
  | 'ISBP 745'
  | 'DCSA'
  | '조직사전';

/** 교정 거절 사유 — 사전 개선 입력이므로 수집 생략 불가 (§5.2) */
export type RejectReason = 'INTERNAL_PRACTICE' | 'COUNTERPARTY' | 'WRONG_SUGGESTION';

export interface Suggestion {
  suggestion_id: string;
  field: string;
  as_is: string;
  to_be: string;
  authority: Authority;
  glossary_term_id: string;
  confidence: number;
  /** 동일 값이 쓰인 다른 서류·필드 — "전체 적용" 일괄 승인 범위 */
  scope: { doc_id: string; field: string }[];
}

// ─────────────────────────────────────────────
// F3 · F6 — 판정
// ─────────────────────────────────────────────

export type VerdictResult =
  | 'VIOLATION'
  | 'PASS'
  | 'DEFERRED';   // 판정 보류 — 필수 확인 필드 미처리 (§5.3)

export interface VerdictEvidence {
  /** 조문 원문 스니펫 — F7 설명의 인용 근거 */
  clause_text: string;
  /** F6 모순 경보의 근거 이벤트 (서류측·현실측 각 1건 이상) */
  event_ids?: string[];
}

export interface Verdict {
  verdict_id: string;
  rule_id: string;
  target_fields: string[];
  result: VerdictResult;
  severity: Severity;
  message: string;
  /** 수정 가이드 — 모든 위반은 최소 1개의 구체적 조치 문장 보유 (§5.4) */
  action_hint: string | null;
  evidence: VerdictEvidence;
  judged_at: UtcTimestamp;
  /** 판정 재현성 — 당시 버전으로 과거 판정 재현 (§5.8) */
  rule_version: string;
  model_version: string | null;
}

/** 하자 확률 예측 결과 (§5.3 계층 B) */
export interface DefectPrediction {
  /** 보정(캘리브레이션) 후 확률. 보정 전 원점수는 표시하지 않음 */
  probability: number;
  /** SHAP 기여도 상위 5개 */
  top_factors: { factor: string; contribution: number }[];
  /** 판정 보류 건수 — 20% 초과 시 신뢰도 제한 경고 (§5.4) */
  deferred_count: number;
}

// ─────────────────────────────────────────────
// F5 — 정정 영향분석
// ─────────────────────────────────────────────

/** 제약 유형 — 타입은 6종 유지, 이번 기간 렌더는 EQ·SUM·REF 3종 (§10.1) */
export type ConstraintType = 'EQ' | 'SUM' | 'DERIVE' | 'REF' | 'COND' | 'EXT';

export interface ImpactItem {
  affected_doc: string;
  affected_field: string;
  action: string;
  party: Party;
  urgency: Severity;
  requires_recheck: boolean;
  rule_id: string | null;
  constraint_type: ConstraintType;
  /** 탐색 깊이 초과분 — 접어서 건수만 노출 (§5.5) */
  indirect: boolean;
}

/** B/L 발행 후 변경 시 재발행 경로 (§5.5) */
export type ReissuePath = 'DRAFT_EDIT' | 'ENDORSEMENT' | 'REISSUE' | 'SWITCH_BL';

export interface ImpactResult {
  items: ImpactItem[];
  indirect_count: number;
  reissue_path: ReissuePath;
  /** 이미 은행 제출 건이면 조건 변경(amendment) 필요 표시 */
  requires_amendment: boolean;
}

// ─────────────────────────────────────────────
// F6 — 현실 대조
// ─────────────────────────────────────────────

export type EventSource = 'UNIPASS' | 'DCSA' | 'USER' | 'INTERNAL';

/** 소스 신뢰등급 (§5.6) */
export type TrustGrade = 'A' | 'B' | 'C' | 'INTERNAL';

export interface RealityEvent {
  event_id: string;
  shipment_id: string;
  source: EventSource;
  source_event_code: string;
  event_type: string;
  occurred_at: UtcTimestamp;
  recorded_at: UtcTimestamp;
  location: string | null;      // UN/LOCODE
  quantity: number | null;
  container_no: string | null;
  trust_grade: TrustGrade;
  /** 날짜만 제공된 이벤트는 시각을 표시하지 않음 (§5.6) */
  precision: 'DATE' | 'DATETIME';
}

/** 어댑터 연결 상태 — S5에 표시. 데이터 없음을 정상으로 판단하지 않음 (§5.6) */
export interface AdapterStatus {
  name: EventSource;
  connected: boolean;
  last_synced_at: UtcTimestamp | null;
  consecutive_failures: number;
}

/**
 * F6 모순 경보 — S6 경보 센터(전역, 여러 선적을 한 화면에 모아 보여줌)에서 사용 (§5.6)
 *
 * ⚠ 서류측·현실측 근거 이벤트를 각각 1건 이상 가져야 합니다.
 *   document_event_ids·reality_event_ids 둘 다 비어 있는 경보는 만들지 않습니다.
 */
export interface Alert {
  alert_id: string;
  shipment_id: string;
  severity: Severity;
  message: string;
  /** 목록에서 선적을 바로 식별할 수 있도록. S6은 여러 선적의 경보를 한 화면에서 다룸 */
  bl_no: string;
  /** 서류측 근거 — 관련 FieldValue.field_name 참조. 최소 1건 */
  document_event_ids: string[];
  /** 현실측 근거 — RealityEvent.event_id 참조. 최소 1건 */
  reality_event_ids: string[];
  acknowledged: boolean;
  created_at: UtcTimestamp;
}

// ─────────────────────────────────────────────
// 선적 (전 기능 공통 키)
// ─────────────────────────────────────────────

export interface Shipment {
  shipment_id: string;
  status: ShipmentStatus;
  bl_no: string | null;
  cargo_control_no: string | null;
  lc_no: string | null;
  created_at: UtcTimestamp;
  updated_at: UtcTimestamp;
  /** 유효기일 등 기한 */
  lc_expiry_date: string | null;
}

export interface ShipmentDraft {
  shipment: Shipment;
  documents: DocumentMeta[];
  fields: FieldValue[];
  suggestions: Suggestion[];
}

/**
 * S1 대시보드 카드용 요약 번들. 새 개념이 아니라 기존 F1·F3·F4 타입을
 * 선적 하나 기준으로 묶은 것뿐입니다 — 실제 API가 생기면 이 모양 그대로
 * "선적 목록 + 요약" 응답이 될 가능성이 높습니다.
 */
export interface ShipmentStats {
  fields: FieldValue[];
  verdicts: Verdict[];
  /** null = 검증을 아직 한 번도 실행하지 않음 (추정하지 않음, §5.4) */
  prediction: DefectPrediction | null;
}

/** 상태 강제 진행 시 기록 — 리포트와 피드백 데이터에 남음 (§5.8) */
export interface StatusOverride {
  from: ShipmentStatus;
  to: ShipmentStatus;
  reason: string;
  actor: string;
  at: UtcTimestamp;
}

/**
 * B/L Copilot — 도메인 상수 및 표시 매핑
 *
 * 근거: 기획안 v2 §5.1 / §5.3 / §5.8 / §10.5
 * 규약: FE 개발규약 v0.2 §2 / §9
 *
 * ⚠ 색상은 이 파일에서만 정의합니다. 화면별로 다시 정하지 않습니다. (규약 §6.1)
 * ⚠ 심각도·신뢰도를 색으로만 구분하지 않습니다. 아이콘·텍스트 병기 필수. (규약 §6.2)
 */

import type {
  Severity,
  ShipmentStatus,
  ConfidenceGrade,
  VerdictResult,
  JobStatus,
  ReissuePath,
} from '../types/domain';

// ─────────────────────────────────────────────
// 잠정 임계값 — 기획안 §10.5에 따라 측정 후 조정
// 하드코딩 금지. 반드시 이 상수를 참조할 것.
// ─────────────────────────────────────────────

export const CONFIDENCE_THRESHOLD = {
  /** 확정 등급 하한 */
  CONFIRMED: 0.9,
  /** 확인 권고 등급 하한. 미만은 필수 확인 */
  ADVISORY: 0.7,
} as const;

/** 성능 목표 — 통과 기준이 아니라 조정 대상 (§10.5) */
export const PERF_TARGET_MS = {
  IMPACT_PANEL_REFRESH: 500,
  VERIFY: 10_000,
  SUGGEST_FIELD: 2_000,
  SUGGEST_SHIPMENT: 10_000,
  REPORT_RENDER: 15_000,
  REPORT_PDF: 30_000,
} as const;

/** 업로드 제한 (§5.1) */
export const UPLOAD_LIMIT = {
  FILE_SIZE_MB: 30,
  FILES_PER_BATCH: 20,
  TOTAL_PER_SHIPMENT_MB: 200,
} as const;

/** 이번 기간 지원 입력 형식 — 나머지는 거부 처리 + 사유 안내 (§10.1) */
export const SUPPORTED_INPUT = {
  ACCEPTED_EXT: ['.pdf', '.jpg', '.jpeg', '.png', '.tif', '.txt'],
  /** 명세에는 있으나 이번 기간 미지원. 거부 시 안내 문구에 사용 */
  DEFERRED_EXT: ['.xlsx', '.csv', '.eml', '.msg', '.json'],
} as const;

// ─────────────────────────────────────────────
// 심각도 (§5.3 / §5.8)
// ─────────────────────────────────────────────

export interface SeverityMeta {
  label: string;
  /** 정렬 가중치 — 오름차순. Critical이 항상 최상단 */
  order: number;
  colorVar: string;
  bgVar: string;
  icon: string;
  description: string;
}

export const SEVERITY: Record<Severity, SeverityMeta> = {
  Critical: {
    label: '위반',
    order: 0,
    colorVar: '--severity-critical',
    bgVar: '--severity-critical-bg',
    icon: 'alert-octagon',
    description: '제출 시 하자 판정 가능성이 매우 높은 명백한 위반',
  },
  Warning: {
    label: '주의',
    order: 1,
    colorVar: '--severity-warning',
    bgVar: '--severity-warning-bg',
    icon: 'alert-triangle',
    description: '은행 재량·관행 차이로 하자가 될 수 있는 항목',
  },
  Info: {
    label: '참고',
    order: 2,
    colorVar: '--severity-info',
    bgVar: '--severity-info-bg',
    icon: 'info',
    description: '하자 사유는 아니나 개선이 바람직한 항목',
  },
};

/** 판정 목록 정렬 비교자 — S4·S6·S7 공통 */
export const bySeverity = (a: { severity: Severity }, b: { severity: Severity }) =>
  SEVERITY[a.severity].order - SEVERITY[b.severity].order;

// ─────────────────────────────────────────────
// 신뢰도 등급 (§5.1)
// ─────────────────────────────────────────────

export interface ConfidenceMeta {
  label: string;
  bgVar: string | null;
  icon: string | null;
  /** 이 등급이 남아 있으면 검증 실행을 막는가 */
  blocksVerify: boolean;
  hint: string;
}

export const CONFIDENCE: Record<ConfidenceGrade, ConfidenceMeta> = {
  CONFIRMED: {
    label: '확정',
    bgVar: null,
    icon: null,
    blocksVerify: false,
    hint: '자동 반영됨. 확인 불필요',
  },
  ADVISORY: {
    label: '확인 권고',
    bgVar: '--confidence-advisory-bg',
    icon: 'help-circle',
    blocksVerify: false,
    hint: '검증은 가능하나 리포트에 미확인 항목으로 기재됩니다',
  },
  REQUIRED: {
    label: '필수 확인',
    bgVar: '--confidence-required-bg',
    icon: 'alert-circle',
    blocksVerify: true,
    hint: '확인 전까지 검증을 실행할 수 없습니다',
  },
  NOT_FOUND: {
    label: '출처 없음',
    bgVar: '--confidence-not-found-bg',
    icon: 'minus-circle',
    blocksVerify: false,
    hint: '원문에서 근거를 찾지 못했습니다. 직접 입력하세요',
  },
};

/**
 * 신뢰도 → 등급 판정 (§5.1)
 *
 * ⚠ 추정값 금지 원칙: bbox 없는 값은 NOT_FOUND.
 *   값이 있어도 근거가 없으면 표시하지 않습니다. (규약 §2.4)
 */
export function toConfidenceGrade(field: {
  value: string | null;
  bbox: unknown | null;
  confidence: number;
  conflict_flag: boolean;
}): ConfidenceGrade {
  if (field.value === null || field.bbox === null) return 'NOT_FOUND';
  if (field.conflict_flag) return 'REQUIRED';
  if (field.confidence < CONFIDENCE_THRESHOLD.ADVISORY) return 'REQUIRED';
  if (field.confidence < CONFIDENCE_THRESHOLD.CONFIRMED) return 'ADVISORY';
  return 'CONFIRMED';
}

// ─────────────────────────────────────────────
// 선적 상태 (§5.8)
// ─────────────────────────────────────────────

export interface StatusMeta {
  label: string;
  order: number;
  colorVar: string;
  /** 이 상태에서 초안 편집(S3)이 가능한가 */
  editable: boolean;
}

export const SHIPMENT_STATUS: Record<ShipmentStatus, StatusMeta> = {
  DRAFT:      { label: '초안',     order: 0, colorVar: '--status-draft',      editable: true  },
  REVIEWING:  { label: '검토 중',  order: 1, colorVar: '--status-reviewing',  editable: true  },
  VERIFIED:   { label: '검증 완료', order: 2, colorVar: '--status-verified',   editable: true  },
  SUBMITTED:  { label: '제출됨',   order: 3, colorVar: '--status-submitted',  editable: false },
  MONITORING: { label: '모니터링', order: 4, colorVar: '--status-monitoring', editable: false },
  CLOSED:     { label: '종료',     order: 5, colorVar: '--status-closed',     editable: false },
};

/** 정상 전이 경로 — 건너뛰기 없음 (§5.8) */
export const STATUS_FLOW: ShipmentStatus[] = [
  'DRAFT', 'REVIEWING', 'VERIFIED', 'SUBMITTED', 'MONITORING', 'CLOSED',
];

/**
 * 전이 게이트 (§5.8)
 *
 * ⚠ M-1 미결: 강제 진행 시 DEFERRED 처리 규칙이 팀 확정 대기 중입니다.
 *   확정 전까지 VerifyBar 착수 보류. (규약 §8 M-1)
 */
export interface GateResult {
  allowed: boolean;
  /** 사유 기록 후 강제 진행이 가능한가 */
  overridable: boolean;
  blockers: string[];
}

export function canTransitionToVerified(input: {
  requiredFieldCount: number;
  unresolvedCriticalCount: number;
}): GateResult {
  const blockers: string[] = [];
  if (input.requiredFieldCount > 0) {
    blockers.push(`필수 확인 필드 ${input.requiredFieldCount}건이 남아 있습니다`);
  }
  if (input.unresolvedCriticalCount > 0) {
    blockers.push(`미해결 Critical 위반 ${input.unresolvedCriticalCount}건이 있습니다`);
  }
  return {
    allowed: blockers.length === 0,
    overridable: true,   // 사유 기록 시 강제 진행 가능 (§5.8)
    blockers,
  };
}

// ─────────────────────────────────────────────
// 추출 필드 표시명 (§5.1)
//
// FieldValue.field_name은 API·bbox와 맞물린 식별자라 영문 그대로 둡니다.
// 화면에 보여줄 한글 이름만 여기서 매핑합니다. 화면마다 다르게 부르지
// 않도록(예: measurement를 어디선 "용적", 어디선 "체적") 이 파일이 유일한
// 정의처입니다.
//
// mockFields의 26개 필드를 모두 담고 있습니다. 새 필드가 생기면 여기에도
// 추가해야 하며, 빠지면 labelOfField가 영문 식별자를 그대로 돌려줍니다.
// ─────────────────────────────────────────────

export const FIELD_LABEL: Record<string, string> = {
  // 당사자
  shipper: '송하인',
  consignee: '수하인',
  notify_party: '통지처',
  carrier: '운송인',
  // 식별번호
  bl_no: 'B/L 번호',
  booking_no: '부킹 번호',
  lc_no: '신용장 번호',
  cargo_control_no: '화물관리번호',
  // 운송구간
  place_of_receipt: '수탁지',
  port_of_loading: '선적항',
  port_of_discharge: '양륙항',
  place_of_delivery: '인도지',
  vessel_voyage: '선박·항차',
  // 화물
  marks_and_numbers: '화인 및 번호',
  no_of_packages: '포장 수량',
  description_of_goods: '물품 명세',
  hs_code: 'HS 부호',
  gross_weight: '총중량',
  measurement: '용적',
  // 컨테이너
  container_no: '컨테이너 번호',
  seal_no: '봉인번호',
  // 조건 · 발행
  freight_terms: '운임 조건',
  incoterms: '인코텀즈',
  no_of_original_bl: '원본 B/L 통수',
  shipped_on_board_date: '본선적재일',
  place_and_date_of_issue: '발행지·발행일',
};

/** 한글 표시명. 매핑에 없는 필드는 영문 식별자를 그대로 씁니다 (지어내지 않음) */
export function labelOfField(fieldName: string): string {
  return FIELD_LABEL[fieldName] ?? fieldName;
}

// ─────────────────────────────────────────────
// 기타 표시 매핑
// ─────────────────────────────────────────────

export const VERDICT_RESULT_LABEL: Record<VerdictResult, string> = {
  VIOLATION: '위반',
  PASS: '통과',
  DEFERRED: '판정 보류',
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  PENDING: '대기 중',
  EXTRACTING: '추출 중',
  DONE: '완료',
  FAILED: '실패',
};

/** 교정 거절 사유 선택지 (§5.2) */
export const REJECT_REASON_LABEL = {
  INTERNAL_PRACTICE: '사내 관행',
  COUNTERPARTY: '거래처 요구',
  WRONG_SUGGESTION: '잘못된 제안',
} as const;

/** B/L 발행 후 정정 시 재발행 경로 표시 (§5.5) */
export const REISSUE_PATH_LABEL: Record<ReissuePath, string> = {
  DRAFT_EDIT: '초안 수정',
  ENDORSEMENT: '배서',
  REISSUE: '재발행',
  SWITCH_BL: '스위치 B/L',
};

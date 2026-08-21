/**
 * B/L Copilot — 선적별 목데이터 묶음 + shipment_id로 찾기
 *
 * shipment.fixture.ts는 "선적 1건(SHP-2026-0812-001)"의 원재료를 담고 있습니다.
 * 이 파일은 그 원재료를 선적 4건에 나눠 담고, URL의 :id로 꺼내 쓸 수 있게
 * 조회 객체를 만듭니다. fixture 쪽이 이미 549줄이라 더 키우지 않고 분리했습니다.
 *
 * ⚠ Verdict 타입에 shipment_id를 추가하지 않은 이유
 *   판정은 언제나 선적 1건 안에서만 봅니다(S4·S7 둘 다 URL에 :id가 있음).
 *   실제 API도 GET /shipments/{id}/verdicts 형태로 선적 단위로 내려올 것이라
 *   판정마다 shipment_id를 다시 넣는 건 중복입니다. 여러 선적을 한 화면에
 *   모으는 Alert에만 shipment_id가 있는 것도 같은 이유입니다 (types/domain.ts §F6).
 *   무엇보다 types/domain.ts는 FE 2인 상호 리뷰 대상이라(규약 §6.3), 목데이터
 *   사정으로 공유 타입을 건드리지 않았습니다.
 */

import type {
  Alert,
  DefectPrediction,
  FieldValue,
  ImpactResult,
  RealityEvent,
  Shipment,
  Suggestion,
  Verdict,
} from '../types/domain';
import {
  mockAlerts,
  mockFields,
  mockImpactResult,
  mockPrediction,
  mockRealityEvents,
  mockShipment,
  mockShipmentDraft,
  mockShipmentSubmitted,
  mockShipmentVerified,
  mockSuggestions,
  mockVerdicts,
} from './shipment.fixture';

/**
 * 한 선적을 화면에 그리는 데 필요한 목데이터 묶음.
 *
 * 목데이터 전용 타입입니다 — 백엔드가 이런 모양으로 응답을 준다는 뜻이 아니라,
 * 화면 4개(S3·S4·S5·S7)가 같은 선적을 볼 때 흩어진 mock을 한 번에 꺼내려고
 * 묶어둔 것뿐입니다. 그래서 domain.ts가 아니라 이 파일에 둡니다.
 */
export interface ShipmentMockData {
  shipment: Shipment;
  fields: FieldValue[];
  /** 그 선적에 값이 있는 필드에 대한 교정 제안만 (suggestionsFor 참고) */
  suggestions: Suggestion[];
  /** 아직 검증을 실행하지 않은 선적은 빈 배열 */
  verdicts: Verdict[];
  /** 검증 전이면 null — 근거 없는 확률을 지어내 보여주지 않기 위함 (규약 §2.4) */
  prediction: DefectPrediction | null;
  /**
   * F6 현실 대조 이벤트 (S5 타임라인).
   *
   * ⚠ 지금 픽스처에는 SHP-2026-0812-001 것뿐입니다. 나머지 3건은 빈 배열로
   *   두고 화면에서 "아직 현실 대조 데이터가 없습니다"로 안내합니다. 어댑터가
   *   아직 안 붙은 것과 "이벤트가 정말 없는 것"은 다르지만, 어느 쪽이든
   *   이벤트를 지어내지는 않습니다 (규약 §2.4 / §5.6 "데이터 없음을 정상으로
   *   판단하지 않음").
   */
  realityEvents: RealityEvent[];
  /** F6 모순 경보 — S5 상단 요약. 이벤트와 같은 이유로 1건분만 있습니다 */
  alerts: Alert[];
  /**
   * S8 정정 영향분석 — port_of_loading을 고쳤을 때 무엇을 다시 봐야 하는가.
   *
   * 네 선적 모두 port_of_loading에 값이 있어 영향분석 대상이 되므로 null은
   * 두지 않았습니다. "아직 영향분석할 게 없다"는 상태는 ImpactPanel이 이미
   * 따로 다룹니다 — 그 필드를 아직 안 고친 경우입니다.
   */
  impact: ImpactResult;
}

/**
 * 아직 추출되지 않은 필드로 되돌립니다 — 값뿐 아니라 근거(bbox·출처·신뢰도)까지
 * 전부 비웁니다. 값만 지우고 bbox를 남기면 "출처는 있는데 값이 없는" 앞뒤 안 맞는
 * 필드가 되고, toConfidenceGrade가 NOT_FOUND로 안 떨어집니다.
 * conflict_flag·candidates도 함께 지웁니다 — 값이 없는데 충돌이 있을 수는 없으니까요.
 */
function toNotFound(field: FieldValue): FieldValue {
  return {
    field_name: field.field_name,
    value: null,
    normalized_value: null,
    confidence: 0,
    source_doc_id: null,
    page: null,
    bbox: null,
    extractor: field.extractor,
    conflict_flag: false,
  };
}

/**
 * mockFields(26개)를 그대로 재사용하되, 선적마다 달라야 하는 식별번호 3개만
 * 그 선적의 값으로 바꿔줍니다. 선적 4건치 필드를 전부 새로 쓰면 700줄이 넘고
 * 유지보수도 어려워서, 차이 나는 부분만 덮어쓰는 방식으로 했습니다.
 */
function withIdentityOf(shipment: Shipment): FieldValue[] {
  const overrides: Record<string, string | null> = {
    bl_no: shipment.bl_no,
    lc_no: shipment.lc_no,
    cargo_control_no: shipment.cargo_control_no,
  };

  return mockFields.map((field) => {
    if (!(field.field_name in overrides)) return field;

    const value = overrides[field.field_name];
    if (value === null) return toNotFound(field);

    return { ...field, value, normalized_value: value };
  });
}

/**
 * DRAFT 단계에서 이미 값이 있을 법한 필드.
 *
 * 초안(DRAFT)은 화주가 SI(선적요청서)를 내고 L/C를 받아둔 정도의 시점입니다.
 * 그래서 계약 당사자·구간·물품 명세처럼 SI·L/C에서 바로 나오는 값만 남기고,
 * 그 뒤 단계에서야 생기는 값들은 전부 미검출로 둡니다:
 *
 * - bl_no·no_of_original_bl·place_and_date_of_issue → B/L 발행 후에 생김
 * - booking_no·carrier·vessel_voyage → 선사 부킹이 확정돼야 나옴
 * - container_no·seal_no → 컨테이너 배정·봉인 후에 나옴
 * - shipped_on_board_date → 실제 본선적재 후에만 알 수 있음
 * - cargo_control_no·hs_code → 수출신고 단계
 * - gross_weight·measurement·no_of_packages·marks_and_numbers → 포장명세서에서
 */
const DRAFT_KNOWN_FIELDS: string[] = [
  'shipper',
  'consignee',
  'lc_no',
  'port_of_loading',
  'port_of_discharge',
  'description_of_goods',
];

/** 위 목록에 없는 필드를 전부 미검출로 바꿉니다 (DRAFT 전용) */
function toDraftFields(fields: FieldValue[]): FieldValue[] {
  return fields.map((field) =>
    DRAFT_KNOWN_FIELDS.includes(field.field_name) ? field : toNotFound(field),
  );
}

/**
 * 그 선적에 실제로 값이 있는 필드에 대한 제안만 남깁니다.
 *
 * 교정 제안은 "이 값을 이렇게 고치세요"라는 뜻이라, 아직 값이 없는 필드에
 * 대해서는 성립하지 않습니다. DRAFT에 container_no 제안이 뜨면 편집기에는
 * "출처 없음"인데 제안은 "MSKU 123456 5를 고치라"고 하는 셈이 됩니다.
 */
function suggestionsFor(fields: FieldValue[]): Suggestion[] {
  const filledFieldNames = new Set(
    fields.filter((field) => field.value !== null).map((field) => field.field_name),
  );
  return mockSuggestions.filter((suggestion) => filledFieldNames.has(suggestion.field));
}

// ─────────────────────────────────────────────
// MSCUBUS2608077 (VERIFIED) — 위반 없이 통과한 케이스
// Critical 0건이라 상태가 VERIFIED일 수 있습니다 (domain.ts: "Critical 미해결 없음")
// ─────────────────────────────────────────────

const verifiedVerdicts: Verdict[] = [
  {
    verdict_id: 'VD-101',
    rule_id: 'R-FMT-DATE',
    target_fields: ['shipped_on_board_date'],
    result: 'VIOLATION',
    severity: 'Warning',
    message: '본선적재일 표기 형식이 서류마다 다릅니다 (2026-08-05 / 05 AUG 2026).',
    action_hint: 'ISO 8601(YYYY-MM-DD) 형식으로 통일하는 것을 권장합니다.',
    evidence: {
      clause_text: 'ISBP 745 A6 — 날짜는 서류 간 동일한 형식으로 기재한다.',
    },
    judged_at: '2026-08-09T09:45:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
  {
    verdict_id: 'VD-102',
    rule_id: 'R-UCP-14E',
    target_fields: ['description_of_goods'],
    result: 'PASS',
    severity: 'Info',
    message: '물품 명세가 L/C 45A보다 축약되어 있으나 모순되지 않아 통과했습니다.',
    action_hint: '수정하지 않아도 됩니다. 참고만 하세요.',
    evidence: {
      clause_text:
        'UCP600 14(e) — B/L 외 서류의 물품 명세는 L/C와 모순되지 않는 일반 용어로 기재할 수 있다.',
    },
    judged_at: '2026-08-09T09:45:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
];

const verifiedPrediction: DefectPrediction = {
  probability: 0.12,
  top_factors: [
    { factor: '날짜 표기 형식 불일치', contribution: 0.07 },
    { factor: '물품 명세 축약', contribution: 0.03 },
  ],
  deferred_count: 0,
};

// ─────────────────────────────────────────────
// ONEYBUS2607512 (SUBMITTED) — 이미 제출된 건의 과거 판정 기록
// 위반이 남아 있어도 제출은 이미 넘어간 상태라, action_hint가 "고치세요"가 아니라
// "이제 초안 수정으로는 못 되돌린다"는 안내입니다. rule_version도 제출 당시의
// 옛 버전(RC-2026.07.2)으로 두어 과거 기록임을 드러냅니다 (§5.8 판정 재현성).
// ─────────────────────────────────────────────

const submittedVerdicts: Verdict[] = [
  {
    verdict_id: 'VD-201',
    rule_id: 'R-LC-31D',
    target_fields: ['shipped_on_board_date'],
    result: 'VIOLATION',
    severity: 'Critical',
    message: 'L/C 유효기일(2026-08-15)까지 3일 남은 시점에 제출되었습니다.',
    action_hint:
      '이미 제출된 건이라 초안 수정으로는 되돌릴 수 없습니다. 개설은행의 심사 결과를 기다리거나 조건 변경(amendment)을 협의하세요.',
    evidence: {
      clause_text: 'UCP600 6(d)(i) — 신용장은 제시를 위한 유효기일을 명시해야 한다.',
    },
    judged_at: '2026-08-01T07:15:00Z',
    rule_version: 'RC-2026.07.2',
    model_version: null,
  },
];

const submittedPrediction: DefectPrediction = {
  probability: 0.44,
  top_factors: [
    { factor: 'L/C 유효기일 임박 (3일)', contribution: 0.29 },
    { factor: '제출 후 정정 불가', contribution: 0.11 },
  ],
  deferred_count: 0,
};

// ─────────────────────────────────────────────
// S8 정정 영향분석 — 선적 상태에 따라 정정의 무게가 달라집니다
//
// 같은 port_of_loading을 고쳐도, 아직 초안이면 그냥 다시 쓰면 되지만 이미
// 은행에 제출됐으면 조건 변경(amendment)과 B/L 재발행까지 가야 합니다.
// 그 차이를 reissue_path·requires_amendment로 드러냅니다 (§5.5).
// ─────────────────────────────────────────────

// DRAFT — 아직 SI·L/C 2건만 올라와 있어 교차 참조할 대상이 적습니다.
// 포장명세서가 없으니 SUM(수량 합계) 제약도 걸리지 않아 1건뿐입니다.
const draftImpact: ImpactResult = {
  items: [
    {
      affected_doc: 'DOC-002',
      affected_field: 'port_of_loading',
      action: 'L/C 44E가 지정한 선적항(KRPUS)과 값이 같은지 확인해야 합니다.',
      party: '은행',
      urgency: 'Critical',
      requires_recheck: true,
      rule_id: 'R-LC-44EF',
      constraint_type: 'EQ',
      indirect: false,
    },
  ],
  indirect_count: 0,
  reissue_path: 'DRAFT_EDIT',
  requires_amendment: false,
};

// VERIFIED — 제출 전이라 초안 수정으로 충분하지만, 이미 통과한 판정을 다시
// 돌려야 해서 선적 상태가 검증 완료에서 검토 중으로 되돌아갑니다.
const verifiedImpact: ImpactResult = {
  items: [
    {
      affected_doc: 'DOC-002',
      affected_field: 'port_of_loading',
      action:
        '이미 통과한 L/C 대사를 다시 실행해야 합니다. 선적 상태가 검증 완료에서 검토 중으로 되돌아갑니다.',
      party: '은행',
      urgency: 'Critical',
      requires_recheck: true,
      rule_id: 'R-LC-44EF',
      constraint_type: 'EQ',
      indirect: false,
    },
    {
      affected_doc: 'DOC-004',
      affected_field: 'no_of_packages',
      action: '포장 수량 교차 검사를 다시 돌려야 합니다.',
      party: '화주',
      urgency: 'Warning',
      requires_recheck: true,
      rule_id: 'R-XREF-QTY',
      constraint_type: 'SUM',
      indirect: true,
    },
  ],
  indirect_count: 1,
  reissue_path: 'DRAFT_EDIT',
  requires_amendment: false,
};

// SUBMITTED — 이미 은행에 제출됐고 B/L도 발행된 상태라, 초안 수정으로는
// 되돌릴 수 없습니다. 조건 변경(amendment) + 재발행 경로로 넘어갑니다.
const submittedImpact: ImpactResult = {
  items: [
    {
      affected_doc: 'DOC-002',
      affected_field: 'port_of_loading',
      action:
        '이미 제출된 건이라 초안 수정으로는 고칠 수 없습니다. 개설은행에 조건 변경(amendment)을 요청하세요.',
      party: '은행',
      urgency: 'Critical',
      requires_recheck: true,
      rule_id: 'R-LC-44EF',
      constraint_type: 'REF',
      indirect: false,
    },
    {
      affected_doc: 'DOC-001',
      affected_field: 'bl_no',
      action: 'B/L이 이미 발행되어 선적항 변경은 재발행 절차가 필요합니다. 선사에 요청하세요.',
      party: '선사',
      urgency: 'Critical',
      requires_recheck: true,
      rule_id: null,
      constraint_type: 'REF',
      indirect: false,
    },
  ],
  indirect_count: 0,
  reissue_path: 'REISSUE',
  requires_amendment: true,
};

// ─────────────────────────────────────────────
// shipment_id → 목데이터 묶음
// ─────────────────────────────────────────────

// 제안 목록이 필드에서 파생되므로(suggestionsFor), 필드를 먼저 한 번만 만들어
// 두고 재사용합니다. 안 그러면 같은 계산을 두 번 하게 됩니다.
const draftFields = toDraftFields(withIdentityOf(mockShipmentDraft));
const verifiedFields = withIdentityOf(mockShipmentVerified);
const submittedFields = withIdentityOf(mockShipmentSubmitted);

export const mockDataByShipment: Record<string, ShipmentMockData> = {
  // 지금까지 개발 기준이던 선적. 판정 5건(위반 3·주의 1·참고 1) 그대로 유지합니다.
  [mockShipment.shipment_id]: {
    shipment: mockShipment,
    fields: mockFields,
    suggestions: suggestionsFor(mockFields),
    verdicts: mockVerdicts,
    prediction: mockPrediction,
    realityEvents: mockRealityEvents,
    alerts: mockAlerts,
    impact: mockImpactResult,
  },
  // DRAFT — 아직 검증 실행 전이라 판정도 하자 확률도 없고, 필드도 SI·L/C에서
  // 나오는 6개만 값이 있습니다. 그래서 교정 제안도 port_of_discharge 1건만
  // 남습니다 (gross_weight·container_no는 아직 값이 없어 제안이 성립 안 함).
  [mockShipmentDraft.shipment_id]: {
    shipment: mockShipmentDraft,
    fields: draftFields,
    suggestions: suggestionsFor(draftFields),
    verdicts: [],
    prediction: null,
    realityEvents: [],
    alerts: [],
    impact: draftImpact,
  },
  // VERIFIED — 검증을 통과한 선적이라 교정 제안은 이미 다 처리(승인/거절)된
  // 것으로 봅니다. 위반 0건으로 통과했는데 안 고친 제안이 3건 남아 있으면
  // "통과했다"와 "아직 고칠 게 있다"가 동시에 뜨는 셈이라 앞뒤가 안 맞습니다.
  // 그래서 suggestionsFor()로 거르지 않고 빈 배열로 둡니다.
  [mockShipmentVerified.shipment_id]: {
    shipment: mockShipmentVerified,
    fields: verifiedFields,
    suggestions: [],
    verdicts: verifiedVerdicts,
    prediction: verifiedPrediction,
    realityEvents: [],
    alerts: [],
    impact: verifiedImpact,
  },
  [mockShipmentSubmitted.shipment_id]: {
    shipment: mockShipmentSubmitted,
    fields: submittedFields,
    suggestions: suggestionsFor(submittedFields),
    verdicts: submittedVerdicts,
    prediction: submittedPrediction,
    realityEvents: [],
    alerts: [],
    impact: submittedImpact,
  },
};

/**
 * URL의 :id로 선적 묶음을 찾습니다. 없는 id면 null —
 * 화면 쪽에서 "선적을 찾을 수 없습니다" 안내를 띄우게 합니다.
 */
export function findShipmentData(shipmentId: string | undefined): ShipmentMockData | null {
  if (shipmentId === undefined) return null;
  return mockDataByShipment[shipmentId] ?? null;
}

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

import type { DefectPrediction, FieldValue, Shipment, Verdict } from '../types/domain';
import {
  mockFields,
  mockPrediction,
  mockShipment,
  mockShipmentDraft,
  mockShipmentSubmitted,
  mockShipmentVerified,
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
  /** 아직 검증을 실행하지 않은 선적은 빈 배열 */
  verdicts: Verdict[];
  /** 검증 전이면 null — 근거 없는 확률을 지어내 보여주지 않기 위함 (규약 §2.4) */
  prediction: DefectPrediction | null;
}

/**
 * mockFields(22개)를 그대로 재사용하되, 선적마다 달라야 하는 식별번호 3개만
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

    // DRAFT처럼 아직 값이 없는 경우. 값이 없으면 근거(bbox)도 없으므로
    // 신뢰도·출처를 전부 비워 미검출(NOT_FOUND)로 떨어뜨립니다. 값만 지우고
    // bbox를 남겨두면 "출처는 있는데 값이 없는" 앞뒤 안 맞는 필드가 됩니다.
    if (value === null) {
      return {
        ...field,
        value: null,
        normalized_value: null,
        confidence: 0,
        source_doc_id: null,
        page: null,
        bbox: null,
      };
    }

    return { ...field, value, normalized_value: value };
  });
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
// shipment_id → 목데이터 묶음
// ─────────────────────────────────────────────

export const mockDataByShipment: Record<string, ShipmentMockData> = {
  // 지금까지 개발 기준이던 선적. 판정 5건(위반 3·주의 1·참고 1) 그대로 유지합니다.
  [mockShipment.shipment_id]: {
    shipment: mockShipment,
    fields: mockFields,
    verdicts: mockVerdicts,
    prediction: mockPrediction,
  },
  // DRAFT — 아직 검증 실행 전이라 판정도 하자 확률도 없습니다.
  [mockShipmentDraft.shipment_id]: {
    shipment: mockShipmentDraft,
    fields: withIdentityOf(mockShipmentDraft),
    verdicts: [],
    prediction: null,
  },
  [mockShipmentVerified.shipment_id]: {
    shipment: mockShipmentVerified,
    fields: withIdentityOf(mockShipmentVerified),
    verdicts: verifiedVerdicts,
    prediction: verifiedPrediction,
  },
  [mockShipmentSubmitted.shipment_id]: {
    shipment: mockShipmentSubmitted,
    fields: withIdentityOf(mockShipmentSubmitted),
    verdicts: submittedVerdicts,
    prediction: submittedPrediction,
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

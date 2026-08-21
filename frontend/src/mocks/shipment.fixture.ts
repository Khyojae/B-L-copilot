/**
 * B/L Copilot — 목 픽스처 (선적 1건)
 *
 * 백엔드 없이 S2·S3·S4·S5·S6을 개발하기 위한 고정 데이터.
 * 신뢰도 4등급·충돌 필드·판정 3심각도·교정 제안·현실 대조 이벤트를 모두 포함합니다.
 *
 * 규약: FE 개발규약 v0.2 §6.1
 */

import type {
  Shipment,
  ShipmentDraft,
  DocumentMeta,
  FieldValue,
  Suggestion,
  Verdict,
  DefectPrediction,
  ImpactItem,
  ImpactResult,
  RealityEvent,
  Alert,
} from '../types/domain';

// ─────────────────────────────────────────────
// 선적
// ─────────────────────────────────────────────

export const mockShipment: Shipment = {
  shipment_id: 'SHP-2026-0812-001',
  status: 'REVIEWING',
  bl_no: 'HLCUBUS2608001',
  cargo_control_no: '26KRPUS0001234',
  lc_no: 'LC26081200123',
  created_at: '2026-08-10T02:14:00Z',
  updated_at: '2026-08-12T01:30:00Z',
  lc_expiry_date: '2026-09-05',
};

// S1 대시보드에서 여러 건이 동시에 보일 때 StatusBadge 색이 섞여 보이도록
// 상태를 다르게 준 선적 3건.
//
// 이 3건의 판정·필드·하자확률은 shipmentData.ts에서 선적별로 따로 묶습니다.
// S4·S7은 URL의 :id로 그 묶음을 찾아 쓰므로, 카드마다 다른 결과가 나옵니다.
// (S3 초안 편집기·S5 타임라인은 아직 mockShipment 것을 그대로 씁니다)
export const mockShipmentDraft: Shipment = {
  shipment_id: 'SHP-2026-0813-002',
  status: 'DRAFT',
  bl_no: null,
  cargo_control_no: null,
  lc_no: 'LC26081300456',
  created_at: '2026-08-13T06:20:00Z',
  updated_at: '2026-08-13T06:20:00Z',
  lc_expiry_date: '2026-09-20',
};

export const mockShipmentVerified: Shipment = {
  shipment_id: 'SHP-2026-0809-003',
  status: 'VERIFIED',
  bl_no: 'MSCUBUS2608077',
  cargo_control_no: '26KRPUS0009981',
  lc_no: 'LC26080900789',
  created_at: '2026-08-05T01:10:00Z',
  updated_at: '2026-08-09T09:45:00Z',
  lc_expiry_date: '2026-08-30',
};

export const mockShipmentSubmitted: Shipment = {
  shipment_id: 'SHP-2026-0801-004',
  status: 'SUBMITTED',
  bl_no: 'ONEYBUS2607512',
  cargo_control_no: '26KRPUS0007765',
  lc_no: 'LC26072800321',
  created_at: '2026-07-28T03:40:00Z',
  updated_at: '2026-08-01T07:15:00Z',
  lc_expiry_date: '2026-08-15',
};

/** S1 대시보드 목록용 — 상태가 섞인 선적 4건 */
export const mockShipments: Shipment[] = [
  mockShipment,
  mockShipmentDraft,
  mockShipmentVerified,
  mockShipmentSubmitted,
];

// ─────────────────────────────────────────────
// 업로드 서류
// ─────────────────────────────────────────────

export const mockDocuments: DocumentMeta[] = [
  {
    document_id: 'DOC-001',
    kind: 'SI',
    file_name: 'SI_20260810.pdf',
    file_hash: 'a3f1c9e2b7',
    page_count: 2,
    version: 1,
    uploaded_at: '2026-08-10T02:14:00Z',
  },
  {
    document_id: 'DOC-002',
    kind: 'LC',
    file_name: 'MT700_LC26081200123.txt',
    file_hash: 'd8b4a1f60c',
    page_count: 1,
    version: 1,
    uploaded_at: '2026-08-10T02:15:00Z',
  },
  {
    document_id: 'DOC-003',
    kind: 'INVOICE',
    file_name: 'CommercialInvoice_scan.pdf',
    file_hash: '5e7c2d9a83',
    page_count: 1,
    version: 1,
    uploaded_at: '2026-08-10T02:15:30Z',
  },
  {
    document_id: 'DOC-004',
    kind: 'PACKING',
    file_name: 'PackingList_scan.pdf',
    file_hash: '9c1b6f4e27',
    page_count: 3,
    version: 1,
    uploaded_at: '2026-08-10T02:16:00Z',
  },
];

// ─────────────────────────────────────────────
// 추출 필드 26건
// 확정 15 · 확인 권고 7 · 필수 확인 2(충돌 1 포함) · 미검출 2
// ─────────────────────────────────────────────

const f = (
  field_name: string,
  value: string | null,
  confidence: number,
  source_doc_id: string | null,
  page: number | null,
  bbox: [number, number, number, number] | null,
  extra: Partial<FieldValue> = {},
): FieldValue => ({
  field_name,
  value,
  normalized_value: value,
  confidence,
  source_doc_id,
  page,
  bbox,
  extractor: 'ocr+llm',
  conflict_flag: false,
  ...extra,
});

export const mockFields: FieldValue[] = [
  // ── 당사자 ──
  f('shipper', 'HANKOOK PRECISION CO.,LTD', 0.96, 'DOC-002', 1, [72, 118, 340, 136]),
  f('consignee', 'NORDWIND HANDELS GMBH', 0.94, 'DOC-002', 1, [72, 140, 352, 158]),
  f('notify_party', 'SAME AS CONSIGNEE', 0.91, 'DOC-001', 1, [72, 162, 268, 180]),
  f('carrier', 'HAPAG-LLOYD', 0.88, 'DOC-001', 1, [72, 184, 220, 202]),

  // ── 식별번호 ──
  f('bl_no', 'HLCUBUS2608001', 0.97, 'DOC-001', 1, [420, 96, 596, 114]),
  f('booking_no', 'BKG26080455', 0.95, 'DOC-001', 1, [420, 118, 580, 136]),
  f('lc_no', 'LC26081200123', 0.98, 'DOC-002', 1, [72, 60, 268, 78], { extractor: 'rule' }),
  f('cargo_control_no', '26KRPUS0001234', 0.93, 'DOC-001', 1, [420, 140, 612, 158]),

  // ── 운송구간 ──
  f('place_of_receipt', 'BUSAN CY', 0.92, 'DOC-001', 1, [72, 228, 232, 246]),
  // ⚠ 충돌: L/C는 KRPUS, SI는 KRINC → conflict_flag
  f('port_of_loading', 'BUSAN', 0.64, 'DOC-002', 1, [72, 250, 232, 268], {
    normalized_value: 'KRPUS',
    conflict_flag: true,
    candidates: [
      f('port_of_loading', 'BUSAN', 0.9, 'DOC-002', 1, [72, 250, 232, 268], {
        normalized_value: 'KRPUS',
      }),
      f('port_of_loading', 'INCHEON', 0.71, 'DOC-001', 1, [72, 250, 240, 268], {
        normalized_value: 'KRINC',
      }),
    ],
  }),
  f('port_of_discharge', 'HAMBURG', 0.95, 'DOC-002', 1, [72, 272, 240, 290], {
    normalized_value: 'DEHAM',
  }),
  f('place_of_delivery', 'HAMBURG CY', 0.89, 'DOC-001', 1, [72, 294, 248, 312]),
  f('vessel_voyage', 'HMM ALGECIRAS / 2608E', 0.86, 'DOC-001', 1, [300, 228, 540, 246]),

  // ── 화물 ──
  f('marks_and_numbers', 'NWH-2608\\nHAMBURG\\nC/NO. 1-480', 0.82, 'DOC-004', 1, [64, 180, 300, 240]),
  f('no_of_packages', '480 CARTONS', 0.94, 'DOC-004', 1, [64, 250, 220, 268]),
  f('description_of_goods', 'PRECISION MACHINE PARTS', 0.9, 'DOC-003', 1, [64, 208, 340, 226]),
  f('hs_code', '8471.30', 0.87, 'DOC-003', 1, [400, 208, 520, 226]),
  f('gross_weight', '12,480 KGS', 0.93, 'DOC-004', 2, [64, 320, 200, 338], {
    normalized_value: '12480 KGM',
  }),
  // ⚠ 필수 확인: 저해상도 스캔
  f('measurement', '38.5 CBM', 0.58, 'DOC-004', 2, [220, 320, 340, 338], {
    normalized_value: '38.5 MTQ',
  }),

  // ── 컨테이너 ──
  f('container_no', 'MSKU 123456 5', 0.79, 'DOC-001', 2, [64, 400, 224, 418], {
    normalized_value: 'MSKU1234565',
  }),
  // ⚠ 미검출
  f('seal_no', null, 0, null, null, null, { extractor: 'ocr+llm' }),

  // ── 조건 · 발행 ──
  f('freight_terms', 'FREIGHT PREPAID', 0.96, 'DOC-002', 1, [400, 320, 580, 338]),
  f('incoterms', 'FOB BUSAN', 0.84, 'DOC-003', 1, [400, 250, 540, 268]),
  f('no_of_original_bl', 'THREE (3)', 0.91, 'DOC-002', 1, [400, 294, 540, 312]),
  f('shipped_on_board_date', '2026-07-14', 0.95, 'DOC-001', 1, [400, 430, 540, 448], {
    extractor: 'rule',
  }),
  // ⚠ 미검출
  f('place_and_date_of_issue', null, 0, null, null, null),
];

// ─────────────────────────────────────────────
// 교정 제안 3건 (§5.2)
// ─────────────────────────────────────────────

export const mockSuggestions: Suggestion[] = [
  {
    suggestion_id: 'SGT-001',
    field: 'port_of_discharge',
    as_is: 'HAMBURG',
    to_be: 'DEHAM (Hamburg)',
    authority: 'UN/LOCODE',
    glossary_term_id: 'LOC-DEHAM',
    confidence: 0.97,
    scope: [
      { doc_id: 'DOC-001', field: 'port_of_discharge' },
      { doc_id: 'DOC-002', field: 'port_of_discharge' },
      { doc_id: 'DOC-003', field: 'destination' },
    ],
  },
  {
    suggestion_id: 'SGT-002',
    field: 'gross_weight',
    as_is: 'KGS',
    to_be: 'KGM',
    authority: 'UN/ECE Rec 20',
    glossary_term_id: 'UOM-KGM',
    confidence: 0.99,
    scope: [
      { doc_id: 'DOC-001', field: 'gross_weight' },
      { doc_id: 'DOC-004', field: 'gross_weight' },
    ],
  },
  {
    suggestion_id: 'SGT-003',
    field: 'container_no',
    as_is: 'MSKU 123456 5',
    to_be: 'MSKU1234565',
    authority: 'ISO 6346',
    glossary_term_id: 'CTR-FORMAT',
    confidence: 1.0,
    scope: [{ doc_id: 'DOC-001', field: 'container_no' }],
  },
];

// ─────────────────────────────────────────────
// 판정 5건 — Critical 3 · Warning 1 · Info 1
// 룰 ID는 기획안 §5.3 카탈로그 기준
// ─────────────────────────────────────────────

export const mockVerdicts: Verdict[] = [
  {
    verdict_id: 'VD-001',
    rule_id: 'R-UCP-14C',
    target_fields: ['shipped_on_board_date'],
    result: 'VIOLATION',
    severity: 'Critical',
    message: '본선적재일로부터 21일을 초과하여 제출될 예정입니다 (적재 2026-07-14, 경과 29일).',
    action_hint: '제출 기한이 이미 지났습니다. 개설은행에 조건 변경(amendment)을 요청하거나 추심 방식 전환을 검토하세요.',
    evidence: {
      clause_text: 'UCP600 14(c) — 서류는 선적일 후 21일보다 늦게 제시되어서는 안 된다.',
    },
    judged_at: '2026-08-12T01:30:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
  {
    verdict_id: 'VD-002',
    rule_id: 'R-LC-44EF',
    target_fields: ['port_of_loading'],
    result: 'VIOLATION',
    severity: 'Critical',
    message: 'L/C가 지정한 선적항(KRPUS)과 서류상 값이 일치하지 않는 후보가 존재합니다.',
    action_hint: 'SI의 INCHEON 표기와 L/C의 BUSAN 중 실제 선적항을 확인하고 필드를 확정하세요.',
    evidence: {
      clause_text: 'MT700 :44E: Port of Loading — KRPUS BUSAN',
    },
    judged_at: '2026-08-12T01:30:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
  {
    verdict_id: 'VD-003',
    rule_id: 'R-XREF-QTY',
    target_fields: ['no_of_packages'],
    result: 'DEFERRED',
    severity: 'Critical',
    // ⚠ 판정 메시지에는 영문 필드명 대신 한글 표시명(FIELD_LABEL)을 씁니다.
    //   화면은 한글 라벨로 통일했는데 메시지만 measurement처럼 영문이 섞이면
    //   같은 필드가 두 이름으로 보입니다.
    //   실제 API가 붙으면 이 문자열은 백엔드가 만들어 내려주므로 같은 문제가
    //   다시 생깁니다 — BE_판정메시지_필드표기.md 참고.
    message: '포장 수량 교차 검사가 보류되었습니다. 용적 필드가 필수 확인 상태입니다.',
    action_hint: '용적 값을 확인하면 검사가 재개됩니다.',
    evidence: {
      clause_text: '서류 간 정합성 — B/L·포장명세서·송장의 포장 수량 합계 일치',
    },
    judged_at: '2026-08-12T01:30:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
  {
    verdict_id: 'VD-004',
    rule_id: 'R-FMT-CTR',
    target_fields: ['container_no'],
    result: 'VIOLATION',
    severity: 'Warning',
    message: '컨테이너 번호 표기가 ISO 6346 형식과 다릅니다 (공백 포함).',
    action_hint: '교정 제안을 승인하면 MSKU1234565로 정규화됩니다.',
    evidence: {
      clause_text: 'ISO 6346 — 소유자 코드 4자리 + 일련번호 6자리 + 체크디지트 1자리, 구분자 없음',
    },
    judged_at: '2026-08-12T01:30:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
  {
    verdict_id: 'VD-005',
    rule_id: 'R-UCP-30A',
    target_fields: ['incoterms'],
    result: 'VIOLATION',
    severity: 'Info',
    message: 'Incoterms 표기에 규칙 버전이 병기되지 않았습니다.',
    action_hint: 'FOB Busan (Incoterms 2020) 형식으로 보완하는 것을 권장합니다.',
    evidence: {
      clause_text: 'Incoterms 2020 — 규칙명과 장소를 병기한다.',
    },
    judged_at: '2026-08-12T01:30:00Z',
    rule_version: 'RC-2026.08.1',
    model_version: null,
  },
];

// ─────────────────────────────────────────────
// 하자 확률 예측 (§5.3 계층 B)
// ─────────────────────────────────────────────

export const mockPrediction: DefectPrediction = {
  probability: 0.78,
  top_factors: [
    { factor: '제출 기한 초과 (UCP600 14c)', contribution: 0.31 },
    { factor: '선적항 값 충돌', contribution: 0.19 },
    { factor: '필수 확인 필드 잔여', contribution: 0.11 },
    { factor: 'L/C 유효기일까지 24일', contribution: 0.09 },
    { factor: '컨테이너 번호 형식 오류', contribution: 0.05 },
  ],
  deferred_count: 1,
};

// ─────────────────────────────────────────────
// F5 정정 영향분석 — S8 ImpactPanel용 (§5.5)
//
// 축소 구현이라 실제 제약 그래프 탐색은 없고, "port_of_loading을 고치면
// 이 항목들을 다시 봐야 한다"는 결과값만 고정 mock으로 둡니다. mockVerdicts의
// VD-002(port_of_loading L/C 충돌)·VD-003(no_of_packages 교차검사 보류)과
// 같은 필드를 가리키게 해서, S4에서 본 판정과 S8의 영향 목록이 서로
// 이어지는 것처럼 보이게 했습니다.
//
// 이번 기간 렌더 대상은 제약 3종(EQ·SUM·REF)뿐이라 그 세 개만 만들었습니다.
// 깊이 2 원칙: 직접 영향(indirect: false) 2건 + 깊이 초과라 접어서 건수만
// 보여줄 간접 영향(indirect: true) 1건.
// ─────────────────────────────────────────────

export const mockImpactItems: ImpactItem[] = [
  {
    affected_doc: 'DOC-001',
    affected_field: 'port_of_loading',
    action: 'SI(선적지시서)의 선적항 표기를 확정값과 같게 다시 맞춰야 합니다.',
    party: '포워더',
    urgency: 'Critical',
    requires_recheck: true,
    rule_id: 'R-LC-44EF',
    constraint_type: 'REF',
    indirect: false,
  },
  {
    affected_doc: 'DOC-002',
    affected_field: 'port_of_loading',
    action: 'L/C 44E 지정 선적항(KRPUS)과 값이 같은지 재대사가 필요합니다.',
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
    action: '포장 수량 교차 검사(DEFERRED)가 선적항 확정 이후 재개됩니다.',
    party: '화주',
    urgency: 'Warning',
    requires_recheck: true,
    rule_id: 'R-XREF-QTY',
    constraint_type: 'SUM',
    indirect: true,
  },
];

export const mockImpactResult: ImpactResult = {
  items: mockImpactItems,
  indirect_count: mockImpactItems.filter((item) => item.indirect).length,
  // 아직 REVIEWING 단계(제출 전)라 재발행이 아니라 초안 수정으로 충분함
  reissue_path: 'DRAFT_EDIT',
  requires_amendment: false,
};

// ─────────────────────────────────────────────
// 조립된 초안 (S3 진입 시 로드되는 형태)
// ─────────────────────────────────────────────

export const mockDraft: ShipmentDraft = {
  shipment: mockShipment,
  documents: mockDocuments,
  fields: mockFields,
  suggestions: mockSuggestions,
};

// ─────────────────────────────────────────────
// F6 현실 대조 이벤트 5건 — S5 타임라인 · S6 경보 센터용 (§5.6)
//
// 수출신고 수리 → 게이트 반입 → 본선적재 → 출항 → 도착 예정 순서의
// 타임라인입니다. 전부 shipment_id는 mockShipment 것과 같습니다.
//
// ⚠ 모순 사례(EVT-003): 서류(mockFields의 container_no)는 컨테이너
//   1대(MSKU1234565)만 기재하는데, 실제 본선적재 이벤트는 quantity: 2로
//   컨테이너가 2대 실린 것으로 기록되어 있습니다. F6이 잡아내야 하는
//   서류·현실 불일치 사례입니다.
// ─────────────────────────────────────────────

export const mockRealityEvents: RealityEvent[] = [
  {
    event_id: 'EVT-001',
    shipment_id: mockShipment.shipment_id,
    source: 'UNIPASS',
    source_event_code: 'EXPORT-ACCEPT',
    event_type: '수출신고 수리',
    occurred_at: '2026-07-12T05:40:00Z',
    recorded_at: '2026-07-12T05:41:00Z',
    location: 'KRPUS',
    quantity: null,
    container_no: null,
    trust_grade: 'A',
    precision: 'DATETIME',
  },
  {
    event_id: 'EVT-002',
    shipment_id: mockShipment.shipment_id,
    source: 'DCSA',
    source_event_code: 'GTIN',
    event_type: '컨테이너 게이트 반입',
    occurred_at: '2026-07-13T14:20:00Z',
    recorded_at: '2026-07-13T14:25:00Z',
    location: 'KRPUS',
    quantity: 1,
    container_no: 'MSKU1234565',
    trust_grade: 'A',
    precision: 'DATETIME',
  },
  // ⚠ 모순 사례 — quantity: 2가 서류상 컨테이너 1대(container_no 필드)와 다름
  {
    event_id: 'EVT-003',
    shipment_id: mockShipment.shipment_id,
    source: 'DCSA',
    source_event_code: 'LOAD',
    event_type: '본선적재 (Loaded on Board)',
    occurred_at: '2026-07-14T08:15:00Z',
    recorded_at: '2026-07-14T09:00:00Z',
    location: 'KRPUS',
    quantity: 2,
    container_no: 'MSKU1234565',
    trust_grade: 'A',
    precision: 'DATETIME',
  },
  {
    event_id: 'EVT-004',
    shipment_id: mockShipment.shipment_id,
    source: 'DCSA',
    source_event_code: 'DEPA',
    event_type: '선박 출항 (Vessel Departure)',
    occurred_at: '2026-07-15T22:00:00Z',
    recorded_at: '2026-07-15T22:10:00Z',
    location: 'KRPUS',
    quantity: null,
    container_no: null,
    trust_grade: 'A',
    precision: 'DATETIME',
  },
  // 아직 일어나지 않은 예측 이벤트라 trust_grade가 A보다 낮고, 날짜만 의미가 있습니다
  {
    event_id: 'EVT-005',
    shipment_id: mockShipment.shipment_id,
    source: 'DCSA',
    source_event_code: 'ARRI',
    event_type: '도착 예정 (Estimated Arrival)',
    occurred_at: '2026-08-20T00:00:00Z',
    recorded_at: '2026-08-13T03:00:00Z',
    location: 'DEHAM',
    quantity: null,
    container_no: null,
    trust_grade: 'B',
    precision: 'DATE',
  },
];

// ─────────────────────────────────────────────
// F6 모순 경보 2건 — S6 경보 센터용. mockRealityEvents와 연결됨 (§5.6)
// ─────────────────────────────────────────────

export const mockAlerts: Alert[] = [
  {
    alert_id: 'ALT-001',
    shipment_id: mockShipment.shipment_id,
    severity: 'Critical',
    message:
      '실제 본선적재 컨테이너가 2대인데 서류에는 1대(MSKU1234565)만 기재되어 있습니다.',
    bl_no: mockShipment.bl_no ?? '',
    document_event_ids: ['container_no'],
    // 게이트 반입(1대 확인) + 본선적재(2대 기록) — 둘을 같이 봐야 불일치가 보임
    reality_event_ids: ['EVT-002', 'EVT-003'],
    acknowledged: false,
    created_at: '2026-07-14T09:05:00Z',
  },
  {
    alert_id: 'ALT-002',
    shipment_id: mockShipment.shipment_id,
    severity: 'Warning',
    message: 'SI의 선적항 기재(INCHEON)가 실제 수출신고·본선적재 위치(BUSAN)와 다릅니다.',
    bl_no: mockShipment.bl_no ?? '',
    document_event_ids: ['port_of_loading'],
    reality_event_ids: ['EVT-001', 'EVT-003'],
    // 이미 mockFields에서 conflict_flag로 알려진 충돌이라, 담당자가 인지는 하고 있는 상태로 설정
    acknowledged: true,
    created_at: '2026-07-14T09:10:00Z',
  },
];

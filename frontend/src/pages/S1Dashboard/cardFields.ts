/**
 * ShipmentCard가 FieldValue[] 에서 값을 꺼낼 때 쓰는 헬퍼.
 *
 * 카드는 필드를 이름으로 찾아 씁니다(shipper, port_of_loading 등). 그런데
 * "값이 없다"에는 두 가지가 섞여 있어서 화면에서 구분해야 합니다:
 *
 *   · 아직 추출되지 않음(NOT_FOUND) → 근거가 없으니 값을 지어내면 안 됨
 *   · 추출됐지만 확인이 필요함(ADVISORY·REQUIRED) → 값은 보여주되 그대로 믿지 말 것
 *
 * 그래서 등급 판정은 shared/shipmentStats의 effectiveGradeOf 하나로만 하고
 * (규약 §2.4 / CLAUDE.md 5번), 카드는 여기서 돌려주는 결과만 그립니다.
 */

import { CONFIDENCE } from '../../constants/domain';
import { effectiveGradeOf, type EditedValues } from '../../shared/shipmentStats';
import type { ConfidenceGrade, FieldValue } from '../../types/domain';

/**
 * S1에는 편집 상태가 없어서 빈 객체를 씁니다.
 *
 * 그래도 toConfidenceGrade를 직접 부르지 않고 effectiveGradeOf를 거치는 이유:
 * M-2("사람이 고친 값을 어떤 등급으로 볼 것인가") 규칙이 바뀌면 S3만 따라가고
 * S1은 옛 규칙에 남는 일을 막기 위해서입니다. 지금은 결과가 같지만, 규칙이
 * 한 곳에만 있어야 어긋나지 않습니다.
 */
const NO_EDITS: EditedValues = {};

/** 이 필드가 지금 갖는 신뢰도 등급 */
export function gradeOf(fields: FieldValue[], fieldName: string): ConfidenceGrade | null {
  const field = findField(fields, fieldName);
  return field === undefined ? null : effectiveGradeOf(field, NO_EDITS);
}

/** 근거가 없어 값을 못 보여줄 때 쓰는 문구. CONFIDENCE에 정의된 것을 그대로 씁니다 */
export const NO_SOURCE_LABEL = CONFIDENCE.NOT_FOUND.label;

function findField(fields: FieldValue[], fieldName: string): FieldValue | undefined {
  return fields.find((field) => field.field_name === fieldName);
}

/**
 * 그 필드의 표시값. 없거나 근거가 없으면 null —
 * 화면에서 null을 받으면 NO_SOURCE_LABEL을 회색으로 보여줍니다.
 */
export function valueOf(fields: FieldValue[], fieldName: string): string | null {
  const field = findField(fields, fieldName);
  if (field === undefined) return null;
  if (effectiveGradeOf(field, NO_EDITS) === 'NOT_FOUND') return null;
  return field.value;
}

/**
 * 정규화된 코드값(예: port_of_loading의 KRPUS). 없으면 null.
 *
 * 카드 항로 띠는 UN/LOCODE 코드를 크게, 원문 표기(BUSAN)를 작게 보여주므로
 * 둘을 따로 꺼낼 수 있어야 합니다.
 */
export function normalizedOf(fields: FieldValue[], fieldName: string): string | null {
  const field = findField(fields, fieldName);
  if (field === undefined) return null;
  if (effectiveGradeOf(field, NO_EDITS) === 'NOT_FOUND') return null;
  return field.normalized_value;
}

/** 이 필드가 지금 "필수 확인"이라 검증을 막고 있는지 */
export function isBlocking(fields: FieldValue[], fieldName: string): boolean {
  const grade = gradeOf(fields, fieldName);
  return grade === null ? false : CONFIDENCE[grade].blocksVerify;
}

/**
 * 값 두 개를 " · "로 잇습니다 (예: "480 CARTONS · 12,480 KGS").
 * 둘 다 없으면 null을 돌려줘서 호출한 쪽이 "출처 없음"을 그리게 합니다.
 */
export function joinValues(...values: (string | null)[]): string | null {
  const present = values.filter((value): value is string => value !== null && value !== '');
  return present.length === 0 ? null : present.join(' · ');
}

/**
 * 기준일까지 남은 일수. 지났으면 음수.
 *
 * 날짜만 비교하려고 양쪽을 자정으로 맞춥니다 — 안 그러면 "오늘"인데도 시각
 * 차이 때문에 0이 아닌 값이 나옵니다.
 */
export function daysUntil(isoDate: string, today: Date): number {
  const target = new Date(isoDate);
  target.setHours(0, 0, 0, 0);
  const base = new Date(today);
  base.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - base.getTime()) / 86_400_000);
}

/** 근거 서류 수 — 필드들이 실제로 가리키는 서류 개수를 셉니다 (추정 아님) */
export function countSourceDocuments(fields: FieldValue[]): number {
  const docIds = new Set(
    fields
      .filter((field) => field.source_doc_id !== null && field.bbox !== null)
      .map((field) => field.source_doc_id),
  );
  return docIds.size;
}

/**
 * 카드 상단·하단에 쓰는 짧은 날짜 형식 (예: 08-12 10:30).
 *
 * toLocaleString('ko-KR')은 "08. 12. 10:30"처럼 점을 붙여서 카드에 넣으면
 * 지저분합니다. 카드에서는 연도가 필요 없고 자리도 좁아서 직접 조립합니다.
 */
export function formatShortDateTime(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 날짜만 짧게 (예: 07-14). 항로 띠의 "07-14 적재"에 씁니다 */
export function formatShortDate(iso: string): string {
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

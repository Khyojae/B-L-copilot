import { effectiveGrade } from '../S3Draft/fieldEditing';
import { SHIPMENT_STATUS } from '../../constants/domain';
import type { FieldValue, Shipment, ShipmentStats, Verdict } from '../../types/domain';

// ─────────────────────────────────────────────
// S1 대시보드 카드가 보여주는 값들을 mock 데이터에서 실제로 계산하는
// 순수 함수 모음. 여기 있는 숫자·문구는 Claude Design 시안의 예시를 베낀
// 게 아니라 shipment.fixture.ts의 fields/verdicts/prediction에서 매번
// 새로 계산됩니다.
// ─────────────────────────────────────────────

function daysUntil(dateStr: string, now: Date): number {
  const target = new Date(`${dateStr}T00:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export interface DDayLabel {
  text: string;
  overdue: boolean;
}

/** L/C 유효기일까지 실제 일수 차이. 지난 경우 "N일 경과"로 표시 (규약: 추정 없이 실제 날짜 계산만) */
export function getDDayLabel(expiryDate: string | null, now: Date = new Date()): DDayLabel | null {
  if (expiryDate === null) return null;
  const diff = daysUntil(expiryDate, now);
  if (diff > 0) return { text: `D-${diff}`, overdue: false };
  if (diff === 0) return { text: '오늘 만료', overdue: true };
  return { text: `${-diff}일 경과`, overdue: true };
}

/** L/C 유효기일이 threshold일 이내(이미 지난 것 포함)로 임박했는지 — S1 필터용 */
export function isDueSoon(shipment: Shipment, thresholdDays = 20, now: Date = new Date()): boolean {
  if (shipment.lc_expiry_date === null) return false;
  return daysUntil(shipment.lc_expiry_date, now) <= thresholdDays;
}

export interface RouteLine {
  route: string;
  detail: string;
}

/** 선적항·양하항·선사·항차 필드에서 구간 표시 문자열 구성. 값이 없으면(부킹 전 등) 그 상태를 그대로 문구로 */
export function getRouteLine(fields: FieldValue[]): RouteLine {
  const valueOf = (name: string) => fields.find((field) => field.field_name === name)?.value ?? null;
  const loading = valueOf('port_of_loading');
  const discharge = valueOf('port_of_discharge');
  const carrier = valueOf('carrier');
  const vessel = valueOf('vessel_voyage');

  const route =
    loading !== null && discharge !== null
      ? `${loading} → ${discharge}`
      : loading !== null
        ? `${loading} → 양하항 미정`
        : '구간 미정';

  const detail =
    carrier !== null
      ? [carrier, vessel].filter((value): value is string => value !== null).join(' · ')
      : '선사·항차 미정 (부킹 전)';

  return { route, detail };
}

/** 지금 "필수 확인" 등급인 필드 이름만 뽑음. effectiveGrade는 S3Draft/fieldEditing의 것을 그대로 재사용
 *  (대시보드에는 사용자가 그 자리에서 고친 값이 없으므로 editedValues는 항상 빈 객체) */
export function getRequiredFieldNames(fields: FieldValue[]): string[] {
  return fields.filter((field) => effectiveGrade(field, {}) === 'REQUIRED').map((field) => field.field_name);
}

export interface VerdictCounts {
  critical: number;
  warning: number;
  info: number;
}

/** 심각도별 건수. S4 VerdictSummary와 같은 방식으로 result와 무관하게 severity만 셈(일관성 유지) */
export function getVerdictCounts(verdicts: Verdict[]): VerdictCounts {
  return {
    critical: verdicts.filter((v) => v.severity === 'Critical').length,
    warning: verdicts.filter((v) => v.severity === 'Warning').length,
    info: verdicts.filter((v) => v.severity === 'Info').length,
  };
}

/** "위반 있음" 필터용 — Critical이 하나라도 있으면 위반 있음으로 침 */
export function hasViolation(stats: ShipmentStats): boolean {
  return getVerdictCounts(stats.verdicts).critical > 0;
}

/**
 * 카드 우측 "다음 할 일" 문구. 시안 문장을 그대로 쓰지 않고, 상태·필수확인
 * 건수·Critical 건수 조합으로 직접 규칙을 짰습니다 (constants/domain.ts의
 * canTransitionToVerified와 같은 스타일의 순수 함수).
 */
export function getNextAction(shipment: Shipment, stats: ShipmentStats): string {
  const requiredCount = getRequiredFieldNames(stats.fields).length;
  const { critical } = getVerdictCounts(stats.verdicts);

  if (!SHIPMENT_STATUS[shipment.status].editable) {
    return critical > 0
      ? '개설은행 심사 결과를 기다리는 중입니다. 초안 수정으로는 되돌릴 수 없습니다.'
      : '제출 완료된 선적입니다. 판정 기록에서 상세 내역을 확인하세요.';
  }
  if (stats.fields.length === 0) {
    return '아직 추출된 필드가 없습니다. 서류를 업로드하세요.';
  }
  if (requiredCount > 0) {
    return `필수 확인 ${requiredCount}건을 확정해야 검증을 실행할 수 있습니다.`;
  }
  if (stats.prediction === null) {
    return '필수 확인 필드가 모두 채워졌습니다. 검증을 실행하세요.';
  }
  if (critical > 0) {
    return `위반 ${critical}건이 남아 있습니다. 검증 결과에서 확인하세요.`;
  }
  return '위반 0건입니다. 리포트를 확인하고 제출을 준비하세요.';
}

/**
 * 대시보드 헤더의 "OO 기준" 안내용 — 전체 선적 판정들 중 가장 최근 judged_at.
 * "지금 이 순간" 같은 라이브 타임스탬프를 지어내지 않고, 실제로 마지막 판정이
 * 언제 있었는지를 그대로 계산합니다. 판정이 하나도 없으면 null(표시 안 함).
 */
export function getLatestJudgedAt(statsById: Record<string, ShipmentStats>): string | null {
  const timestamps = Object.values(statsById).flatMap((stats) => stats.verdicts.map((v) => v.judged_at));
  if (timestamps.length === 0) return null;
  return timestamps.reduce((latest, ts) => (ts > latest ? ts : latest));
}

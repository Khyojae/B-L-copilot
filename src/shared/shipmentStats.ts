/**
 * 선적 파생값 집계 — 여러 화면이 같은 숫자를 쓰도록 계산식을 한곳에 모읍니다.
 *
 * 전에는 심각도별 건수를 S1 카드(CardVerdictBand)와 S4 요약(VerdictSummary)이
 * 각각 따로 세고 있었습니다. 규칙이 바뀌면 한쪽만 고쳐질 위험이 있어서,
 * "몇 건인가"를 묻는 계산은 전부 이 파일로 옮겼습니다.
 *
 * 위치가 src/shared 인 이유: README의 디렉토리 규약에서 공통 유틸 자리입니다.
 * 화면(pages)이 shared를 가져다 쓰고, 그 반대 방향은 없습니다.
 */

import { CONFIDENCE, SEVERITY, toConfidenceGrade } from '../constants/domain';
import type { ConfidenceGrade, FieldValue, Severity, Verdict } from '../types/domain';

/** 필드별로 사용자가 고친 값 (필드 이름 → 새 값) */
export type EditedValues = Record<string, string | null>;

/** 원본 값에서 바뀌었는지 (직접 수정이든 교정 제안 승인이든) */
export function isEditedField(field: FieldValue, editedValues: EditedValues): boolean {
  return field.field_name in editedValues && editedValues[field.field_name] !== field.value;
}

/**
 * 지금 화면에서 이 필드가 갖는 신뢰도 등급.
 *
 * ⚠ M-2 미결: 직접 고친 값·승인한 제안값은 일단 무조건 "확정"으로 칩니다
 *   (원래 등급이 "필수 확인"이었어도). 이게 맞는 규칙인지 팀 확정 대기 중 —
 *   CLAUDE.md M-2 참고.
 */
export function effectiveGradeOf(field: FieldValue, editedValues: EditedValues): ConfidenceGrade {
  return isEditedField(field, editedValues) ? 'CONFIRMED' : toConfidenceGrade(field);
}

/** 등급별 필드 건수. 화면에 안 나오는 등급도 0으로 채워 돌려줍니다 */
export function countFieldsByGrade(
  fields: FieldValue[],
  editedValues: EditedValues = {},
): Record<ConfidenceGrade, number> {
  const counts: Record<ConfidenceGrade, number> = {
    CONFIRMED: 0,
    ADVISORY: 0,
    REQUIRED: 0,
    NOT_FOUND: 0,
  };
  for (const field of fields) {
    counts[effectiveGradeOf(field, editedValues)] += 1;
  }
  return counts;
}

/** 지금 "필수 확인" 상태라 검증을 막는 필드가 몇 건인지 */
export function countRequiredFields(
  fields: FieldValue[],
  editedValues: EditedValues = {},
): number {
  return fields.filter((field) => CONFIDENCE[effectiveGradeOf(field, editedValues)].blocksVerify)
    .length;
}

export interface VerdictCounts {
  /** 심각도별 건수 — 판정 보류(DEFERRED)는 빠져 있습니다 */
  bySeverity: Record<Severity, number>;
  /** 판정 보류 건수 — 심각도와 겹치지 않게 따로 셉니다 */
  deferred: number;
  /** 전체 판정 수 = 심각도 합계 + deferred */
  total: number;
}

/**
 * 판정 건수 집계.
 *
 * ⚠ 판정 보류(result: 'DEFERRED')는 심각도 집계에서 뺍니다.
 *   보류는 "아직 판정하지 못했다"는 뜻이라, 심각도가 Critical로 붙어 있어도
 *   "위반 3건"에 넣으면 확정된 위반처럼 읽힙니다. 실제 mockVerdicts의 VD-003이
 *   이 경우입니다 — severity는 Critical이지만 measurement 필드가 필수 확인이라
 *   교차 검사를 못 돌린 상태입니다.
 *
 *   그래서 위반 2 · 주의 1 · 참고 1 · 판정 보류 1 (합계 5)로 셉니다.
 */
export function summarizeVerdicts(verdicts: Verdict[]): VerdictCounts {
  const bySeverity: Record<Severity, number> = { Critical: 0, Warning: 0, Info: 0 };
  let deferred = 0;

  for (const verdict of verdicts) {
    if (verdict.result === 'DEFERRED') {
      deferred += 1;
      continue;
    }
    bySeverity[verdict.severity] += 1;
  }

  return { bySeverity, deferred, total: verdicts.length };
}

/** 심각도를 정렬 순서(위반 → 주의 → 참고)대로 나열 */
export const SEVERITIES_IN_ORDER = (Object.keys(SEVERITY) as Severity[]).sort(
  (a, b) => SEVERITY[a].order - SEVERITY[b].order,
);

/**
 * 심각도 집계에서 가장 심각한 등급. 판정 보류만 있거나 판정이 없으면 null.
 * S1 카드의 하자 확률 막대 색을 정하는 데 씁니다.
 */
export function worstSeverity(verdicts: Verdict[]): Severity | null {
  const { bySeverity } = summarizeVerdicts(verdicts);
  return SEVERITIES_IN_ORDER.find((severity) => bySeverity[severity] > 0) ?? null;
}

/** 충돌이 해소된 필드 (필드 이름 → 사용자가 고른 후보의 값) */
export type ResolvedConflicts = Record<string, string>;

/**
 * 값 충돌 필드를 "사용자가 고른 후보"로 바꿔 돌려줍니다.
 *
 * ⚠ M-2 관련 임시안 — 후보 선택은 직접 입력과 다르게 취급합니다.
 *
 *   직접 입력은 사람이 새 값을 써넣는 것이라 effectiveGradeOf가 확정으로
 *   올립니다. 반면 후보 선택은 "이미 원문에서 읽어낸 두 값 중 어느 쪽이
 *   맞는지 고르는" 행동입니다. 고른다고 해서 원문의 인식 품질이 좋아지는
 *   것은 아니므로, 등급은 그 후보가 원래 갖고 있던 신뢰도를 그대로 따릅니다.
 *
 *   - BUSAN(신용장, 0.90)을 고르면 → 확정
 *   - INCHEON(선적요청서, 0.71)을 고르면 → 확인 권고
 *
 *   낮은 쪽을 골랐는데 확정으로 올라가면 시스템이 위험을 감추게 됩니다.
 *
 *   충돌 자체는 해소되므로 conflict_flag는 내리고 candidates도 비웁니다.
 *   이 규칙도 팀 확정 전 임시안입니다 — M1_M2_팀확정요청.md 참고.
 */
export function resolveConflicts(
  fields: FieldValue[],
  resolved: ResolvedConflicts,
): FieldValue[] {
  return fields.map((field) => {
    const chosenValue = resolved[field.field_name];
    if (chosenValue === undefined) return field;

    const candidate = (field.candidates ?? []).find((option) => option.value === chosenValue);
    if (candidate === undefined) return field;

    // 고른 후보의 값·근거·신뢰도를 그대로 승계합니다. 충돌만 해소된 상태라
    // 등급 계산(toConfidenceGrade)이 candidate의 confidence를 보게 됩니다.
    return {
      field_name: field.field_name,
      value: candidate.value,
      normalized_value: candidate.normalized_value,
      confidence: candidate.confidence,
      source_doc_id: candidate.source_doc_id,
      page: candidate.page,
      bbox: candidate.bbox,
      extractor: candidate.extractor,
      conflict_flag: false,
      // 후보 목록은 그대로 둡니다. 선택을 되돌릴 때(그리고 다른 후보로 바꿀 때)
      // 필요하고, 등급 계산은 conflict_flag만 보므로 남아 있어도 영향이 없습니다.
      candidates: field.candidates,
    };
  });
}

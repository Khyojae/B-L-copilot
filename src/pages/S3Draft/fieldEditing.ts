import { CONFIDENCE, toConfidenceGrade } from '../../constants/domain';
import type { ConfidenceGrade, FieldValue } from '../../types/domain';

// ─────────────────────────────────────────────
// FieldRow 인라인 편집(직접 타이핑)과 SuggestionCard 제안 승인이 공유하는
// "이 필드, 지금 화면에 뭘 보여줘야 하나" 로직. VerifyBar도 "검증 실행"
// 버튼을 막을지 말지 정하려면 똑같은 계산(필수 확인 몇 건 남았나)이
// 필요해서, FieldForm 하나에만 있으면 안 되고 여기로 모아뒀습니다.
// ─────────────────────────────────────────────

/** 이 필드에 지금 화면에 보여줄 값. 고친 적 있으면 고친 값, 없으면 원본 값 */
export function displayValueOf(
  field: FieldValue,
  editedValues: Record<string, string | null>,
): string | null {
  return field.field_name in editedValues ? editedValues[field.field_name] : field.value;
}

/** 원본 값에서 바뀌었는지 (FieldRow 직접 수정이든 SuggestionCard 승인이든 상관없이) */
export function isEditedField(
  field: FieldValue,
  editedValues: Record<string, string | null>,
): boolean {
  return field.field_name in editedValues && editedValues[field.field_name] !== field.value;
}

/**
 * ⚠ M-2 미결: 직접 고친 값·승인한 제안값은 일단 무조건 "확정"으로 칩니다
 *   (원래 등급이 "필수 확인"이었어도). 이게 맞는 규칙인지 팀 확정 대기 중 —
 *   CLAUDE.md M-2 참고.
 */
export function effectiveGrade(
  field: FieldValue,
  editedValues: Record<string, string | null>,
): ConfidenceGrade {
  return isEditedField(field, editedValues) ? 'CONFIRMED' : toConfidenceGrade(field);
}

/** 지금 "필수 확인" 상태라 검증을 막는 필드가 몇 건인지 */
export function countRequiredFields(
  fields: FieldValue[],
  editedValues: Record<string, string | null>,
): number {
  return fields.filter((field) => CONFIDENCE[effectiveGrade(field, editedValues)].blocksVerify)
    .length;
}

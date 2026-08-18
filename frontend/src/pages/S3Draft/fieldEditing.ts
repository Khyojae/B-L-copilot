import type { FieldValue } from '../../types/domain';
import type { EditedValues } from '../../shared/shipmentStats';
import { effectiveGradeOf, isEditedField } from '../../shared/shipmentStats';

// ─────────────────────────────────────────────
// FieldRow 인라인 편집(직접 타이핑)과 SuggestionCard 제안 승인이 공유하는
// "이 필드, 지금 화면에 뭘 보여줘야 하나" 로직.
//
// 건수 집계(필수 확인 몇 건, 등급별 몇 건)는 S1·S4도 같은 값을 써야 해서
// src/shared/shipmentStats.ts로 옮겼습니다. 여기에는 표시용 로직만 남깁니다.
// ─────────────────────────────────────────────

/** 이 필드에 지금 화면에 보여줄 값. 고친 적 있으면 고친 값, 없으면 원본 값 */
export function displayValueOf(field: FieldValue, editedValues: EditedValues): string | null {
  return field.field_name in editedValues ? editedValues[field.field_name] : field.value;
}

// 아래 둘은 이 폴더 안에서 쓰던 이름을 그대로 유지하기 위한 재수출입니다.
// 계산 자체는 shared에 한 벌만 있습니다.
export { effectiveGradeOf as effectiveGrade, isEditedField };

import { useState } from 'react';
import { mockFields } from '../../mocks/shipment.fixture';
import { CONFIDENCE, toConfidenceGrade } from '../../constants/domain';
import type { FieldValue } from '../../types/domain';
import { FieldRow } from './FieldRow';

interface FieldFormProps {
  /** 지금 문서 뷰어에서 하이라이트되고 있는 필드 이름 */
  focusedFieldName?: string | null;
  /** 행을 클릭했을 때 그 필드를 부모(S3Draft)에 알려줌 */
  onFieldFocus?: (field: FieldValue) => void;
}

export function FieldForm({ focusedFieldName = null, onFieldFocus }: FieldFormProps) {
  // 필드별로 사용자가 고친 값. 아직 안 고친 필드는 여기 안 들어있고, 그때는 field.value를 그대로 보여줌.
  // FieldRow 안에 있던 상태를 여기로 끌어올린 이유: "필수 확인" 건수(아래 requiredCount)를
  // 계산하려면 모든 필드의 수정 여부를 한곳에서 알아야 하는데, 각 FieldRow가 따로
  // state를 들고 있으면 옆에 있는 FieldForm은 그 값을 알 방법이 없기 때문입니다.
  const [editedValues, setEditedValues] = useState<Record<string, string | null>>({});
  // 지금 인라인 입력창이 열려 있는 필드 이름. 한 번에 한 행만 편집 상태가 될 수 있음
  const [editingFieldName, setEditingFieldName] = useState<string | null>(null);
  // 편집 중인 입력창에 지금 타이핑된 텍스트
  const [draft, setDraft] = useState('');

  function displayValueOf(field: FieldValue): string | null {
    return field.field_name in editedValues ? editedValues[field.field_name] : field.value;
  }

  function isEditedField(field: FieldValue): boolean {
    return field.field_name in editedValues && editedValues[field.field_name] !== field.value;
  }

  function startEditing(field: FieldValue) {
    setDraft(displayValueOf(field) ?? '');
    setEditingFieldName(field.field_name);
  }

  function commitEdit(field: FieldValue) {
    const trimmed = draft.trim();
    setEditedValues((prev) => ({ ...prev, [field.field_name]: trimmed === '' ? null : trimmed }));
    setEditingFieldName(null);
  }

  function cancelEdit() {
    setEditingFieldName(null);
  }

  // ⚠ M-2 미결: 직접 고친 필드는 사람이 이미 확인한 것으로 보고 "확정" 등급으로
  //   쳐서 건수에서 뺍니다 (FieldRow가 배지를 그릴 때 쓰는 규칙과 동일 — 등급
  //   문구와 이 숫자가 항상 같이 움직여야 함). 팀 확정 대기 중 — CLAUDE.md M-2 참고.
  const requiredCount = mockFields.filter((field) => {
    const grade = isEditedField(field) ? 'CONFIRMED' : toConfidenceGrade(field);
    return CONFIDENCE[grade].blocksVerify;
  }).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
      <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)' }}>
        필수 확인 {requiredCount}건
      </p>

      {mockFields.map((field) => (
        <FieldRow
          key={field.field_name}
          field={field}
          displayValue={displayValueOf(field)}
          isEdited={isEditedField(field)}
          isEditing={editingFieldName === field.field_name}
          draft={draft}
          onDraftChange={setDraft}
          onStartEdit={() => startEditing(field)}
          onCommitEdit={() => commitEdit(field)}
          onCancelEdit={cancelEdit}
          isFocused={field.field_name === focusedFieldName}
          onClick={onFieldFocus ? () => onFieldFocus(field) : undefined}
        />
      ))}
    </div>
  );
}

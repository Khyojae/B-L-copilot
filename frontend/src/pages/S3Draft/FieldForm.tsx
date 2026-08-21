import { useState } from 'react';
import type { FieldValue } from '../../types/domain';
import { FieldRow } from './FieldRow';
import { countRequiredFields, displayValueOf, isEditedField } from './fieldEditing';

interface FieldFormProps {
  /**
   * 보여줄 필드 목록. 예전에는 mockFields를 직접 가져다 썼지만, 선적마다 필드가
   * 달라지면서 S3Draft가 URL의 :id로 찾아 넘겨주는 방식으로 바꿨습니다.
   */
  fields: FieldValue[];
  /** 지금 문서 뷰어에서 하이라이트되고 있는 필드 이름 */
  focusedFieldName?: string | null;
  /** 행을 클릭했을 때 그 필드를 부모(S3Draft)에 알려줌 */
  onFieldFocus?: (field: FieldValue) => void;
  /**
   * 필드별로 사용자가 고친 값. 아직 안 고친 필드는 여기 안 들어있고, 그때는
   * field.value를 그대로 보여줌. S3Draft가 들고 있다가 넘겨줍니다 — 교정 제안
   * (SuggestionCard) 승인도 여기 같은 값을 고치기 때문에, FieldForm 혼자만
   * 알고 있으면 안 되고 둘의 부모인 S3Draft가 공유해야 합니다.
   */
  editedValues: Record<string, string | null>;
  /** 필드 하나의 값을 고쳤을 때 (인라인 편집 확정 시) S3Draft에 알려줌 */
  onFieldEdit: (fieldName: string, value: string | null) => void;
}

export function FieldForm({
  fields,
  focusedFieldName = null,
  onFieldFocus,
  editedValues,
  onFieldEdit,
}: FieldFormProps) {
  // 지금 인라인 입력창이 열려 있는 필드 이름. 한 번에 한 행만 편집 상태가 될 수 있음.
  // (이건 "입력창이 열려 있나"라는 화면 전용 상태라서 S3Draft까지 끌어올릴 필요는 없음)
  const [editingFieldName, setEditingFieldName] = useState<string | null>(null);
  // 편집 중인 입력창에 지금 타이핑된 텍스트
  const [draft, setDraft] = useState('');

  function startEditing(field: FieldValue) {
    setDraft(displayValueOf(field, editedValues) ?? '');
    setEditingFieldName(field.field_name);
  }

  function commitEdit(field: FieldValue) {
    const trimmed = draft.trim();
    onFieldEdit(field.field_name, trimmed === '' ? null : trimmed);
    setEditingFieldName(null);
  }

  function cancelEdit() {
    setEditingFieldName(null);
  }

  const requiredCount = countRequiredFields(fields, editedValues);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
      <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)' }}>
        필수 확인 {requiredCount}건
      </p>

      {fields.map((field) => (
        <FieldRow
          key={field.field_name}
          field={field}
          displayValue={displayValueOf(field, editedValues)}
          isEdited={isEditedField(field, editedValues)}
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

import { useState } from 'react';
import { FieldForm } from './FieldForm';
import { DocumentViewer } from './DocumentViewer';
import { SuggestionCard } from './SuggestionCard';
import { VerifyBar } from './VerifyBar';
import { mockSuggestions } from '../../mocks/shipment.fixture';
import type { FieldValue, Suggestion } from '../../types/domain';

export function S3Draft() {
  // 지금 문서 뷰어에서 하이라이트할 필드. FieldRow를 클릭하면 여기로 들어옴
  const [focusedField, setFocusedField] = useState<FieldValue | null>(null);

  // 필드별로 사용자가 고친 값 (필드 이름 → 새 값). FieldRow에서 직접 타이핑해서
  // 고치는 것과 SuggestionCard에서 교정 제안을 승인하는 것, 둘 다 결국 "이 필드
  // 값을 이걸로 바꾼다"는 같은 동작이라서 여기 하나의 상태로 합쳐서 관리합니다.
  const [editedValues, setEditedValues] = useState<Record<string, string | null>>({});

  function handleFieldEdit(fieldName: string, value: string | null) {
    setEditedValues((prev) => ({ ...prev, [fieldName]: value }));
  }

  function handleSuggestionAccept(suggestion: Suggestion, applyToAllInScope: boolean) {
    setEditedValues((prev) => {
      // suggestion.field는 항상 바꾼다. applyToAllInScope가 켜져 있으면
      // scope에 있는 다른 필드들도 같은 값으로 같이 바꾼다 (일괄 적용)
      const next = { ...prev, [suggestion.field]: suggestion.to_be };
      if (applyToAllInScope) {
        for (const { field } of suggestion.scope) {
          next[field] = suggestion.to_be;
        }
      }
      return next;
    });
  }

  function handleSuggestionReject(suggestion: Suggestion, reason: string) {
    // 거절은 필드 값을 바꾸지 않습니다 — 지금은 사유만 기록(콘솔)
    console.log('[SuggestionCard] 거절:', suggestion.suggestion_id, { reason });
  }

  return (
    <div style={{ padding: 32 }}>
      <h1>초안 편집기</h1>

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        <DocumentViewer focusedField={focusedField ?? undefined} />
        <div style={{ flex: 1 }}>
          <FieldForm
            focusedFieldName={focusedField?.field_name ?? null}
            onFieldFocus={setFocusedField}
            editedValues={editedValues}
            onFieldEdit={handleFieldEdit}
          />

          <h2 style={{ textAlign: 'left', padding: '0 16px' }}>교정 제안</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 16px' }}>
            {mockSuggestions.map((suggestion) => (
              <SuggestionCard
                key={suggestion.suggestion_id}
                suggestion={suggestion}
                onAccept={handleSuggestionAccept}
                onReject={handleSuggestionReject}
              />
            ))}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 24 }}>
        <VerifyBar editedValues={editedValues} />
      </div>
    </div>
  );
}

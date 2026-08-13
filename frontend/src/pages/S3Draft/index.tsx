import { useState } from 'react';
import { FieldForm } from './FieldForm';
import { DocumentViewer } from './DocumentViewer';
import type { FieldValue } from '../../types/domain';

export function S3Draft() {
  // 지금 문서 뷰어에서 하이라이트할 필드. FieldRow를 클릭하면 여기로 들어옴
  const [focusedField, setFocusedField] = useState<FieldValue | null>(null);

  return (
    <div style={{ padding: 32 }}>
      <h1>초안 편집기</h1>

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        <DocumentViewer focusedField={focusedField ?? undefined} />
        <div style={{ flex: 1 }}>
          <FieldForm focusedFieldName={focusedField?.field_name ?? null} onFieldFocus={setFocusedField} />
        </div>
      </div>
    </div>
  );
}

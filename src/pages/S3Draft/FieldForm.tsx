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
  const requiredCount = mockFields.filter(
    (field) => CONFIDENCE[toConfidenceGrade(field)].blocksVerify,
  ).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
      <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)' }}>
        필수 확인 {requiredCount}건
      </p>

      {mockFields.map((field) => (
        <FieldRow
          key={field.field_name}
          field={field}
          isFocused={field.field_name === focusedFieldName}
          onClick={onFieldFocus ? () => onFieldFocus(field) : undefined}
        />
      ))}
    </div>
  );
}

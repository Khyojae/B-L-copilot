import { mockFields } from '../../mocks/shipment.fixture';
import { CONFIDENCE, toConfidenceGrade } from '../../constants/domain';
import { FieldRow } from './FieldRow';

export function FieldForm() {
  const requiredCount = mockFields.filter(
    (field) => CONFIDENCE[toConfidenceGrade(field)].blocksVerify,
  ).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 16 }}>
      <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)' }}>
        필수 확인 {requiredCount}건
      </p>

      {mockFields.map((field) => (
        <FieldRow key={field.field_name} field={field} />
      ))}
    </div>
  );
}

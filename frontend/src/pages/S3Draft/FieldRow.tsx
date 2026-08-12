import { AlertCircle, AlertTriangle, HelpCircle, MinusCircle } from 'lucide-react';
import type { FieldValue } from '../../types/domain';
import { CONFIDENCE, toConfidenceGrade } from '../../constants/domain';

/** CONFIDENCE.icon 문자열(예: 'help-circle')을 실제 아이콘 컴포넌트로 연결 */
const ICON_BY_NAME = {
  'help-circle': HelpCircle,
  'alert-circle': AlertCircle,
  'minus-circle': MinusCircle,
} as const;

interface FieldRowProps {
  field: FieldValue;
}

export function FieldRow({ field }: FieldRowProps) {
  const grade = toConfidenceGrade(field);
  const meta = CONFIDENCE[grade];
  const Icon = meta.icon !== null ? ICON_BY_NAME[meta.icon as keyof typeof ICON_BY_NAME] : null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        borderRadius: 6,
        backgroundColor: meta.bgVar !== null ? `var(${meta.bgVar})` : 'transparent',
        border: field.conflict_flag
          ? '1px solid var(--severity-critical)'
          : '1px solid transparent',
      }}
    >
      <span style={{ flex: '0 0 180px', fontSize: 13, color: 'var(--text-muted)' }}>
        {field.field_name}
      </span>

      <span style={{ flex: 1, textAlign: 'left' }}>{field.value ?? '출처 없음'}</span>

      {field.conflict_flag && (
        <AlertTriangle size={14} color="var(--severity-critical)" aria-hidden="true" />
      )}

      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 12,
          color: 'var(--text-muted)',
        }}
      >
        {Icon !== null && <Icon size={14} aria-hidden="true" />}
        {meta.label}
      </span>
    </div>
  );
}

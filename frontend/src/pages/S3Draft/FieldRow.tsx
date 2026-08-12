import { useState } from 'react';
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

  // 화면에서만 반영되는 값 — 서버 저장은 아직 없음
  const [displayValue, setDisplayValue] = useState(field.value);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(field.value ?? '');
  const isEdited = displayValue !== field.value;

  function startEditing() {
    setDraft(displayValue ?? '');
    setIsEditing(true);
  }

  function commitEdit() {
    const trimmed = draft.trim();
    setDisplayValue(trimmed === '' ? null : trimmed);
    setIsEditing(false);
  }

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

      {isEditing ? (
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commitEdit}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commitEdit();
            if (event.key === 'Escape') setIsEditing(false);
          }}
          autoFocus
          style={{
            flex: 1,
            font: 'inherit',
            color: 'inherit',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: '2px 6px',
          }}
        />
      ) : (
        <span onClick={startEditing} style={{ flex: 1, textAlign: 'left', cursor: 'text' }}>
          {displayValue ?? '출처 없음'}
        </span>
      )}

      {isEdited && (
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)' }}>수정됨</span>
      )}

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

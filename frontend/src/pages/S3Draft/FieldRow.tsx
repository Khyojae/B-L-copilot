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
  /** 지금 화면에 보여줄 값 (수정한 적 있으면 수정한 값, 없으면 원본 값) — FieldForm이 계산해서 내려줌 */
  displayValue: string | null;
  /** 원본 값에서 바뀌었는지 — FieldForm이 계산해서 내려줌 */
  isEdited: boolean;
  /** 지금 이 행이 인라인 입력창을 보여주고 있는지 */
  isEditing: boolean;
  /** 입력창에 지금 타이핑 중인 텍스트 (isEditing일 때만 의미 있음) */
  draft: string;
  onDraftChange: (value: string) => void;
  onStartEdit: () => void;
  onCommitEdit: () => void;
  onCancelEdit: () => void;
  /** 이 행이 지금 문서 뷰어에서 하이라이트되고 있는 필드인지 */
  isFocused?: boolean;
  /** 행을 클릭했을 때 (문서 뷰어에서 이 필드를 하이라이트하기 위해 부모에게 알려줌) */
  onClick?: () => void;
}

export function FieldRow({
  field,
  displayValue,
  isEdited,
  isEditing,
  draft,
  onDraftChange,
  onStartEdit,
  onCommitEdit,
  onCancelEdit,
  isFocused = false,
  onClick,
}: FieldRowProps) {
  // ⚠ M-2 미결: 사람이 직접 타이핑으로 고친 값은 일단 이미 확인된 것으로 보고
  //   "확정"으로 취급합니다 (원래 등급이 "필수 확인"이었어도 수정하는 순간 요약
  //   건수에서 빠짐). 이게 맞는 규칙인지 팀 확정 대기 중 — CLAUDE.md M-2 참고.
  const grade = isEdited ? 'CONFIRMED' : toConfidenceGrade(field);
  const meta = CONFIDENCE[grade];
  const Icon = meta.icon !== null ? ICON_BY_NAME[meta.icon as keyof typeof ICON_BY_NAME] : null;

  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        borderRadius: 6,
        cursor: onClick ? 'pointer' : undefined,
        backgroundColor: meta.bgVar !== null ? `var(${meta.bgVar})` : 'transparent',
        border: field.conflict_flag
          ? '1px solid var(--severity-critical)'
          : '1px solid transparent',
        boxShadow: isFocused ? 'inset 0 0 0 1.5px var(--accent)' : 'none',
      }}
    >
      <span style={{ flex: '0 0 180px', fontSize: 13, color: 'var(--text-muted)' }}>
        {field.field_name}
      </span>

      {isEditing ? (
        <input
          type="text"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onBlur={onCommitEdit}
          onKeyDown={(event) => {
            if (event.key === 'Enter') onCommitEdit();
            if (event.key === 'Escape') onCancelEdit();
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
        <span onClick={onStartEdit} style={{ flex: 1, textAlign: 'left', cursor: 'text' }}>
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

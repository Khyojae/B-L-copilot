import { AlertTriangle } from 'lucide-react';
import type { FieldValue } from '../../types/domain';
import {
  CONFIDENCE,
  UNSETTLED_LABEL,
  labelOfField,
  toConfidenceGrade,
} from '../../constants/domain';
import { GradeBadge } from './GradeBadge';

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

/**
 * 필드 한 줄 — [한글 라벨 / 값 / 등급 뱃지] 3단 배치.
 *
 * 라벨은 constants/domain.ts의 FIELD_LABEL에서 옵니다. 영문 식별자
 * (port_of_loading)는 작게 함께 보여줍니다 — 화면은 한글로 읽고, 개발·문의할
 * 때는 식별자가 필요하기 때문입니다.
 */
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
  // 충돌이 아직 안 풀린 필드는 value에 후보 하나가 들어 있어도 확정값이
  // 아닙니다. 그대로 쓰면 "정해졌다"로 읽혀서 아래 후보 목록과 어긋납니다.
  const isUnsettled = field.conflict_flag && !isEdited;
  const isMissing = displayValue === null;

  return (
    <div
      onClick={onClick}
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(120px, 180px) 1fr auto',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: '14px 18px',
        cursor: onClick ? 'pointer' : undefined,
        backgroundColor: meta.bgVar !== null ? `var(${meta.bgVar})` : 'transparent',
        boxShadow: isFocused ? 'inset 0 0 0 1.5px var(--brand-primary)' : 'none',
      }}
    >
      {/* 한글 라벨만 보여줍니다 — FIELD_LABEL을 만든 목적이 영문 식별자를
          화면에서 치우는 것이었습니다. 식별자가 필요하면 개발자 도구에서
          FIELD_LABEL 매핑을 보면 됩니다 */}
      <span
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: 'var(--text-primary)',
          wordBreak: 'keep-all',
          minWidth: 0,
        }}
      >
        {labelOfField(field.field_name)}
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
            font: 'inherit',
            fontSize: 14,
            color: 'inherit',
            border: '1px solid var(--border-default)',
            borderRadius: 4,
            padding: '4px 8px',
            minWidth: 0,
          }}
        />
      ) : (
        <span
          onClick={onStartEdit}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
            minWidth: 0,
            fontSize: 14.5,
            fontWeight: 600,
            textAlign: 'left',
            cursor: 'text',
            color: isMissing || isUnsettled ? 'var(--text-muted)' : 'var(--text-primary)',
            wordBreak: 'keep-all',
            overflowWrap: 'break-word',
          }}
        >
          {isUnsettled ? UNSETTLED_LABEL : (displayValue ?? meta.label)}
          {/* 정규화 표기는 값이 바뀐 게 아니라 표시 단위만 다른 것이라 따로 밝힙니다.
              충돌 중일 때는 후보마다 정규화값이 달라서 여기에 안 씁니다 */}
          {!isEdited && !isUnsettled && field.normalized_value !== null && field.normalized_value !== field.value && (
            <span style={{ fontSize: 11.5, fontWeight: 500, color: 'var(--text-muted)' }}>
              표시 단위 {field.normalized_value} · 값 변경 아님
            </span>
          )}
          {isEdited && (
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--brand-primary)' }}>수정됨</span>
          )}
        </span>
      )}

      <GradeBadge grade={grade} />

      {field.conflict_flag && (
        <AlertTriangle
          size={14}
          color="var(--severity-critical)"
          aria-hidden="true"
          style={{ gridColumn: '3', justifySelf: 'end' }}
        />
      )}
    </div>
  );
}


import type { FieldValue } from '../../types/domain';

interface CandidateChooserProps {
  field: FieldValue;
  /** 후보를 골랐을 때 — 값 확정은 부모(S3Draft)가 합니다 */
  onChoose: (value: string) => void;
  /** 판정에서 온 수정 가이드. 없으면 안내 줄을 그리지 않습니다 */
  actionHint: string | null;
  /** 그 가이드를 낸 룰 id (근거 표시용) */
  ruleId: string | null;
}

/**
 * 값 충돌 필드의 후보 선택.
 *
 * ⚠ 자동 반영 금지 (CLAUDE.md 6번): 후보를 눌러도 값이 바로 바뀌지 않고,
 *   부모가 editedValues에 넣어야 반영됩니다. 여기서는 "무엇을 고를 수 있는지"와
 *   "왜 골라야 하는지"만 보여줍니다.
 *
 * 후보는 field.candidates에 실제로 들어 있는 것만 그립니다 — 지어내지 않습니다.
 */
export function CandidateChooser({ field, onChoose, actionHint, ruleId }: CandidateChooserProps) {
  const candidates = field.candidates ?? [];
  if (candidates.length === 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        padding: '16px 18px',
        borderTop: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
      }}
    >
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
        후보 {candidates.length}건 — 하나를 확정하세요
      </span>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {candidates.map((candidate) => (
          <button
            key={`${candidate.source_doc_id}-${candidate.value}`}
            type="button"
            onClick={() => candidate.value !== null && onChoose(candidate.value)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              padding: '10px 13px',
              border: '1px solid var(--border-default)',
              borderRadius: 6,
              backgroundColor: 'var(--bg)',
              textAlign: 'left',
              flexWrap: 'wrap',
            }}
          >
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
              {candidate.value}
            </span>
            {candidate.normalized_value !== null && (
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {candidate.normalized_value}
              </span>
            )}
            <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
              {candidate.source_doc_id} · {candidate.page}p · 신뢰도{' '}
              {Math.round(candidate.confidence * 100)}%
            </span>
          </button>
        ))}
      </div>

      {actionHint !== null && (
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 'var(--space-2)',
            paddingTop: 'var(--space-2)',
            borderTop: '1px solid var(--border-default)',
          }}
        >
          {ruleId !== null && (
            <span
              style={{
                flexShrink: 0,
                padding: '2px 6px',
                fontSize: 11,
                fontWeight: 600,
                color: 'var(--severity-critical)',
                border: '1px solid var(--severity-critical)',
                borderRadius: 4,
              }}
            >
              {ruleId}
            </span>
          )}
          <span style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--text-primary)', wordBreak: 'keep-all' }}>
            {actionHint}
          </span>
        </div>
      )}
    </div>
  );
}

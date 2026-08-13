import { useState } from 'react';
import type { RejectReason, Suggestion } from '../../types/domain';
import { REJECT_REASON_LABEL } from '../../constants/domain';

interface SuggestionCardProps {
  suggestion: Suggestion;
  /**
   * "승인" 버튼을 눌렀을 때만 호출됩니다.
   * applyToAllInScope는 "전체 적용" 체크박스 상태 — 실제로 값을 바꾸는 건
   * 이 콜백을 받는 부모(또는 그 위)의 몫이고, 이 컴포넌트는 값을 직접 바꾸지 않습니다.
   */
  onAccept: (suggestion: Suggestion, applyToAllInScope: boolean) => void;
  /** 거절 사유를 골랐을 때 호출됩니다 */
  onReject: (suggestion: Suggestion, reason: RejectReason) => void;
}

type Status = 'idle' | 'accepted' | 'rejected';

/**
 * F2 표준 용어 교정 제안 카드.
 *
 * ⚠ 규약 §2.5 자동 반영 금지 — 이 컴포넌트는 어떤 경우에도 필드 값을 직접
 * 바꾸지 않습니다. 사용자가 "승인" 버튼을 눌러야만 onAccept가 호출되고,
 * 실제로 값을 반영하는 것은 그 콜백을 받는 쪽의 책임입니다.
 */
export function SuggestionCard({ suggestion, onAccept, onReject }: SuggestionCardProps) {
  // 아직 결정 안 함 / 승인함 / 거절함 — 세 가지뿐이라 boolean 두 개 대신 하나의 상태로 관리
  const [status, setStatus] = useState<Status>('idle');
  const [showRejectReasons, setShowRejectReasons] = useState(false);
  const [rejectedReason, setRejectedReason] = useState<RejectReason | null>(null);
  // "전체 적용" 체크박스. scope가 2곳 이상일 때만 화면에 보이고 의미를 가짐
  const [applyToAllInScope, setApplyToAllInScope] = useState(false);

  const hasMultipleScope = suggestion.scope.length >= 2;
  // 아직 승인도 거절도 안 했고, 거절 사유를 고르는 중도 아닐 때만 "결정 대기" 화면을 보여줌
  const isDeciding = status === 'idle' && !showRejectReasons;

  function handleAccept() {
    onAccept(suggestion, applyToAllInScope);
    setStatus('accepted');
  }

  function handleRejectClick() {
    setShowRejectReasons(true);
  }

  function handleSelectReason(reason: RejectReason) {
    onReject(suggestion, reason);
    setRejectedReason(reason);
    setShowRejectReasons(false);
    setStatus('rejected');
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 16,
        border: '1px solid var(--border)',
        borderRadius: 8,
        backgroundColor: 'var(--card-bg)',
        textAlign: 'left',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{suggestion.field}</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          신뢰도 {Math.round(suggestion.confidence * 100)}%
        </span>
      </div>

      <p style={{ margin: 0 }}>
        <span style={{ textDecoration: 'line-through', color: 'var(--text-muted)' }}>
          {suggestion.as_is}
        </span>
        {' → '}
        <strong>{suggestion.to_be}</strong>
      </p>

      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>출처: {suggestion.authority}</span>

      {hasMultipleScope && isDeciding && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
            {suggestion.scope.length}곳에 동일하게 나타납니다
          </p>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={applyToAllInScope}
              onChange={(event) => setApplyToAllInScope(event.target.checked)}
            />
            전체 적용
          </label>
        </div>
      )}

      {isDeciding && (
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" onClick={handleAccept}>
            승인
          </button>
          <button type="button" onClick={handleRejectClick}>
            거절
          </button>
        </div>
      )}

      {showRejectReasons && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>거절 사유를 선택하세요</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.entries(REJECT_REASON_LABEL).map(([reason, label]) => (
              <button
                key={reason}
                type="button"
                onClick={() => handleSelectReason(reason as RejectReason)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {status === 'accepted' && (
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>
          ✓ 적용됨
          {applyToAllInScope && hasMultipleScope ? ` · ${suggestion.scope.length}곳 전체` : ''}
        </span>
      )}

      {status === 'rejected' && rejectedReason !== null && (
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>
          거절됨 · {REJECT_REASON_LABEL[rejectedReason]}
        </span>
      )}
    </div>
  );
}

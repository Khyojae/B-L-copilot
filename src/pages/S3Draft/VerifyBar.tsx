import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { mockFields, mockPrediction, mockVerdicts } from '../../mocks/shipment.fixture';
import { canTransitionToVerified } from '../../constants/domain';
import { countRequiredFields } from './fieldEditing';

interface VerifyBarProps {
  /** FieldForm·SuggestionCard와 공유하는 "필드별 수정값" — 필수 확인 건수 계산에 필요 */
  editedValues: Record<string, string | null>;
}

/**
 * S3 초안 편집기의 "검증 실행" 버튼 + 리스크 요약.
 *
 * ⚠ M-1 미결: "검증 실행" 버튼의 활성/비활성 조건이 아직 팀 확정 전입니다.
 *   여기서 쓰는 규칙(`canTransitionToVerified`)은 잠정 제안일 뿐이고, 팀
 *   확정 결과에 따라 바뀔 수 있습니다. 자세한 내용은 CLAUDE.md M-1 참고.
 *   확정 전까지는 이 컴포넌트를 실제 상태 전이(DRAFT → VERIFIED)에 연결하지
 *   않습니다 — "검증 실행"·"강제 실행" 모두 지금은 콘솔 로그만 남깁니다.
 */
export function VerifyBar({ editedValues }: VerifyBarProps) {
  const [showOverrideForm, setShowOverrideForm] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideRecorded, setOverrideRecorded] = useState<string | null>(null);

  const requiredCount = countRequiredFields(mockFields, editedValues);
  // 판정(Verdict)은 아직 안 만들어서(S4에서 다룸) 여기선 mock 판정 중
  // "미해결" Critical만 셉니다. DEFERRED는 필수 확인 필드 쪽에서 이미
  // 세고 있는 문제라 여기서 또 세면 같은 문제를 두 번 반영하게 됩니다.
  const unresolvedCriticalCount = mockVerdicts.filter(
    (verdict) => verdict.severity === 'Critical' && verdict.result === 'VIOLATION',
  ).length;

  const gate = canTransitionToVerified({
    requiredFieldCount: requiredCount,
    unresolvedCriticalCount,
  });

  function handleVerifyClick() {
    console.log('[VerifyBar] 검증 실행 클릭');
  }

  function handleOverrideSubmit() {
    const trimmed = overrideReason.trim();
    if (trimmed === '') return;
    console.log('[VerifyBar] 강제 실행 사유 기록:', trimmed);
    setOverrideRecorded(trimmed);
    setShowOverrideForm(false);
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        padding: 'var(--space-3)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
        textAlign: 'left',
      }}
    >
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <AlertTriangle size={14} color="var(--severity-warning)" aria-hidden="true" />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          M-1 미결 — 버튼 규칙은 팀 확정 전 임시안입니다
        </span>
      </div>

      <div>
        <p style={{ margin: '0 0 4px', fontSize: 13, color: 'var(--text-muted)' }}>리스크 요약</p>
        <p style={{ margin: 0 }}>
          예상 하자 확률 <strong>{Math.round(mockPrediction.probability * 100)}%</strong>
          {mockPrediction.deferred_count > 0 && (
            <span style={{ color: 'var(--text-muted)' }}>
              {' '}
              (판정 보류 {mockPrediction.deferred_count}건 제외)
            </span>
          )}
        </p>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--text-muted)' }}>
          {mockPrediction.top_factors.map((factor) => (
            <li key={factor.factor}>
              {factor.factor} ({Math.round(factor.contribution * 100)}%)
            </li>
          ))}
        </ul>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <button type="button" className="btn-primary" disabled={!gate.allowed} onClick={handleVerifyClick}>
          검증 실행
        </button>

        {!gate.allowed &&
          gate.blockers.map((blocker) => (
            <p key={blocker} style={{ margin: 0, fontSize: 13, color: 'var(--severity-critical)' }}>
              {blocker}
            </p>
          ))}
      </div>

      {!gate.allowed && gate.overridable && overrideRecorded === null && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {!showOverrideForm ? (
            <button type="button" className="btn-secondary" onClick={() => setShowOverrideForm(true)}>
              사유 기록 후 강제 실행
            </button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                강제 실행 사유를 입력하세요
              </span>
              <input
                type="text"
                value={overrideReason}
                onChange={(event) => setOverrideReason(event.target.value)}
                autoFocus
                style={{
                  font: 'inherit',
                  color: 'inherit',
                  border: '1px solid var(--border-default)',
                  borderRadius: 4,
                  padding: '4px 8px',
                }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="btn-primary" onClick={handleOverrideSubmit}>
                  확인
                </button>
                <button type="button" className="btn-secondary" onClick={() => setShowOverrideForm(false)}>
                  취소
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {overrideRecorded !== null && (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--brand-primary)' }}>
          사유 기록됨: {overrideRecorded}
        </p>
      )}
    </div>
  );
}

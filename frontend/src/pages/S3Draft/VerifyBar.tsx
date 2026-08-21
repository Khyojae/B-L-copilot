import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { SEVERITY, VERDICT_RESULT_LABEL, canTransitionToVerified } from '../../constants/domain';
import type { DefectPrediction, FieldValue, Verdict } from '../../types/domain';
import {
  SEVERITIES_IN_ORDER,
  countRequiredFields,
  summarizeVerdicts,
  worstSeverity,
} from '../../shared/shipmentStats';

interface VerifyBarProps {
  /** 이 선적의 필드 — 필수 확인 건수를 셀 대상 */
  fields: FieldValue[];
  /** 이 선적의 판정 — 미해결 Critical 건수를 셀 대상. 검증 전이면 빈 배열 */
  verdicts: Verdict[];
  /** 이 선적의 하자 확률. 아직 검증 전이면 null이라 요약을 못 그립니다 */
  prediction: DefectPrediction | null;
  /** FieldForm·SuggestionCard와 공유하는 "필드별 수정값" */
  editedValues: Record<string, string | null>;
}

/**
 * S3 초안 편집기 하단의 검증 바 — 리스크 요약 + "검증 실행".
 *
 * 이 화면의 핵심 동작이라 S3Draft가 화면 아래에 sticky로 붙입니다. 그래서
 * 세로로 쌓지 않고 가로 한 줄로 눕혔습니다 — 세로 카드는 본문을 너무 많이
 * 가립니다. 하자 확률 기여 요인은 확률 숫자를 눌러 접었다 펼 수 있습니다 —
 * 78%의 근거라 빼지 않되, 항상 펼쳐두지도 않습니다.
 *
 * ⚠ M-1 미결: "검증 실행" 버튼의 활성/비활성 조건이 아직 팀 확정 전입니다.
 *   여기서 쓰는 규칙(canTransitionToVerified)은 잠정 제안일 뿐입니다.
 *   확정 전까지 실제 상태 전이에 연결하지 않습니다 — 콘솔 로그만 남깁니다.
 */
export function VerifyBar({ fields, verdicts, prediction, editedValues }: VerifyBarProps) {
  const [showOverrideForm, setShowOverrideForm] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideRecorded, setOverrideRecorded] = useState<string | null>(null);
  // 하자 확률 기여 요인은 접어둡니다 — 78%라는 숫자의 근거라 꼭 볼 수 있어야
  // 하지만, 하단 고정 바에 항상 펼쳐두면 본문을 너무 많이 가립니다.
  const [showFactors, setShowFactors] = useState(false);

  const requiredCount = countRequiredFields(fields, editedValues);
  const verdictCounts = summarizeVerdicts(verdicts);

  // 미해결 Critical만 셉니다. 판정 보류는 필수 확인 필드 쪽에서 이미 세고 있는
  // 문제라 여기서 또 세면 같은 문제를 두 번 반영하게 됩니다.
  const unresolvedCriticalCount = verdicts.filter(
    (verdict) => verdict.severity === 'Critical' && verdict.result === 'VIOLATION',
  ).length;

  const gate = canTransitionToVerified({
    requiredFieldCount: requiredCount,
    unresolvedCriticalCount,
  });

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
        alignItems: 'center',
        gap: 'var(--space-4)',
        flexWrap: 'wrap',
        padding: 'var(--space-3)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
        textAlign: 'left',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={13} color="var(--severity-warning)" aria-hidden="true" />
          <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
            M-1 미결 — 버튼 규칙은 팀 확정 전 임시안입니다
          </span>
        </span>

        {prediction === null ? (
          // 검증 전에는 0%로 채우지 않습니다 — 0%는 "안전하다"는 근거 없는 주장 (§2.4)
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            아직 검증을 실행하지 않아 하자 확률이 없습니다.
          </span>
        ) : (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-3)',
              flexWrap: 'wrap',
            }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 7 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>
                하자 확률
              </span>
              <button
                type="button"
                onClick={() => setShowFactors((open) => !open)}
                title="이 확률이 어떻게 나왔는지 보기"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: 0,
                  border: 'none',
                  background: 'none',
                  fontSize: 26,
                  fontWeight: 700,
                  lineHeight: 1,
                  color: `var(${SEVERITY[worstSeverity(verdicts) ?? 'Info'].colorVar})`,
                }}
              >
                {Math.round(prediction.probability * 100)}%
                {showFactors ? (
                  <ChevronDown size={16} aria-hidden="true" />
                ) : (
                  <ChevronRight size={16} aria-hidden="true" />
                )}
              </button>
              {prediction.deferred_count > 0 && (
                <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                  판정 보류 {prediction.deferred_count}건 제외
                </span>
              )}
            </span>

            {/* 판정 건수 — 집계는 shared/shipmentStats가 맡아 S1·S4와 항상 같습니다 */}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              {SEVERITIES_IN_ORDER.map((severity) => (
                <Pill
                  key={severity}
                  label={`${SEVERITY[severity].label} ${verdictCounts.bySeverity[severity]}`}
                  colorVar={SEVERITY[severity].colorVar}
                  bgVar={SEVERITY[severity].bgVar}
                />
              ))}
              {verdictCounts.deferred > 0 && (
                <Pill
                  label={`${VERDICT_RESULT_LABEL.DEFERRED} ${verdictCounts.deferred}`}
                  colorVar="--text-secondary"
                  bgVar={null}
                />
              )}
            </span>
          </div>
        )}

        {/* 하자 확률의 근거 — SHAP 기여도 상위 요인. AI 판정을 설명하는
            자리라 빼지 않고, 접었다 펼 수 있게 뒀습니다 (§5.3 계층 B) */}
        {showFactors && prediction !== null && (
          <ul
            style={{
              margin: '4px 0 0',
              paddingLeft: 18,
              fontSize: 12.5,
              lineHeight: 1.6,
              color: 'var(--text-secondary)',
            }}
          >
            {prediction.top_factors.map((factor) => (
              <li key={factor.factor}>
                {factor.factor}{' '}
                <strong style={{ color: 'var(--text-primary)' }}>
                  {Math.round(factor.contribution * 100)}%
                </strong>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
        {/* 차단 사유를 한 줄로 잇습니다 — 세로로 쌓으면 하단 고정 바가
            그만큼 두꺼워져서 본문을 더 가립니다 */}
        {!gate.allowed && (
          <span style={{ fontSize: 12.5, color: 'var(--severity-critical)', textAlign: 'right' }}>
            {gate.blockers.join(' · ')}
          </span>
        )}

        {overrideRecorded !== null && (
          <span style={{ fontSize: 12.5, color: 'var(--brand-primary)' }}>
            사유 기록됨: {overrideRecorded}
          </span>
        )}

        {showOverrideForm ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <input
              type="text"
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder="강제 실행 사유"
              autoFocus
              style={{
                font: 'inherit',
                fontSize: 13,
                color: 'inherit',
                border: '1px solid var(--border-default)',
                borderRadius: 4,
                padding: '6px 8px',
              }}
            />
            <button type="button" className="btn-primary" onClick={handleOverrideSubmit}>
              확인
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setShowOverrideForm(false)}
            >
              취소
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {!gate.allowed && gate.overridable && overrideRecorded === null && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowOverrideForm(true)}
              >
                사유 기록 후 강제 실행
              </button>
            )}
            <button
              type="button"
              className="btn-primary"
              disabled={!gate.allowed}
              onClick={() => console.log('[VerifyBar] 검증 실행 클릭')}
              style={{ padding: '10px 22px', fontSize: 14, fontWeight: 700 }}
            >
              검증 실행
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** 건수 알약 — 색·글자를 함께 씁니다 (규약 §6.2) */
function Pill({
  label,
  colorVar,
  bgVar,
}: {
  label: string;
  colorVar: string;
  bgVar: string | null;
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px 10px',
        borderRadius: 999,
        fontSize: 12.5,
        fontWeight: 700,
        color: `var(${colorVar})`,
        backgroundColor: bgVar !== null ? `var(${bgVar})` : 'transparent',
        border: `1px solid var(${bgVar !== null ? colorVar : '--border-default'})`,
      }}
    >
      {label}
    </span>
  );
}

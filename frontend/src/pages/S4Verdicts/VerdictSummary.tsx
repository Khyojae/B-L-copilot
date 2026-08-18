import type { Verdict } from '../../types/domain';
import { SEVERITY, VERDICT_RESULT_LABEL } from '../../constants/domain';
import { SEVERITIES_IN_ORDER, summarizeVerdicts } from '../../shared/shipmentStats';

interface VerdictSummaryProps {
  verdicts: Verdict[];
}

/**
 * 심각도 순서(위반 → 주의 → 참고)대로 건수를 센 문자열. 0건이어도 표시합니다.
 *
 * 판정 보류는 심각도 뒤에 따로 붙입니다 — 보류는 "아직 판정하지 못했다"는
 * 뜻이라 위반 건수에 섞으면 확정된 위반처럼 읽힙니다. 집계 규칙 자체는
 * shared/shipmentStats가 갖고 있어서 S1 카드·S3 편집기와 항상 같은 숫자입니다.
 */
function toSummaryText(verdicts: Verdict[]): string {
  const { bySeverity, deferred } = summarizeVerdicts(verdicts);

  const parts = SEVERITIES_IN_ORDER.map(
    (severity) => `${SEVERITY[severity].label} ${bySeverity[severity]}건`,
  );

  if (deferred > 0) {
    parts.push(`${VERDICT_RESULT_LABEL.DEFERRED} ${deferred}건`);
  }

  return parts.join(' · ');
}

export function VerdictSummary({ verdicts }: VerdictSummaryProps) {
  return (
    <p
      style={{
        margin: 0,
        padding: 'var(--space-3)',
        fontSize: 20,
        fontWeight: 700,
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--brand-primary-light)',
      }}
    >
      {toSummaryText(verdicts)}
    </p>
  );
}

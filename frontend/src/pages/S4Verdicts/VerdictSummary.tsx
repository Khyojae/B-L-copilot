import type { Severity, Verdict } from '../../types/domain';
import { SEVERITY } from '../../constants/domain';

interface VerdictSummaryProps {
  verdicts: Verdict[];
}

/** 심각도 순서(위반 → 주의 → 참고)대로 건수를 센 문자열을 만듦. 0건이어도 표시함 */
function toSummaryText(verdicts: Verdict[]): string {
  const severities = (Object.keys(SEVERITY) as Severity[]).sort(
    (a, b) => SEVERITY[a].order - SEVERITY[b].order,
  );

  return severities
    .map((severity) => {
      const count = verdicts.filter((v) => v.severity === severity).length;
      return `${SEVERITY[severity].label} ${count}건`;
    })
    .join(' · ');
}

export function VerdictSummary({ verdicts }: VerdictSummaryProps) {
  return (
    <p style={{ margin: '0 0 8px', fontWeight: 600 }}>{toSummaryText(verdicts)}</p>
  );
}

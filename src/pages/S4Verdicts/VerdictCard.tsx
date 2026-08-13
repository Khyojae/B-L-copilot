import type { Verdict } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';
import { SEVERITY } from '../../constants/domain';

interface VerdictCardProps {
  verdict: Verdict;
}

export function VerdictCard({ verdict }: VerdictCardProps) {
  const meta = SEVERITY[verdict.severity];

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 'var(--space-3)',
        borderTop: '1px solid var(--border-default)',
        borderRight: '1px solid var(--border-default)',
        borderBottom: '1px solid var(--border-default)',
        borderLeft: `4px solid var(${meta.colorVar})`,
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: `var(${meta.bgVar})`,
        textAlign: 'left',
      }}
    >
      <SeverityBadge severity={verdict.severity} />

      <p style={{ margin: 0 }}>{verdict.message}</p>

      {verdict.action_hint !== null && (
        <p style={{ margin: 0, color: 'var(--text)' }}>{verdict.action_hint}</p>
      )}

      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{verdict.rule_id}</span>
    </div>
  );
}

import type { Verdict } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';

interface VerdictCardProps {
  verdict: Verdict;
}

export function VerdictCard({ verdict }: VerdictCardProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 'var(--space-3)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
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

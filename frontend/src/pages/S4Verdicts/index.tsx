import { VerdictCard } from './VerdictCard';
import { VerdictSummary } from './VerdictSummary';
import { mockVerdicts } from '../../mocks/shipment.fixture';
import { bySeverity } from '../../constants/domain';

export function S4Verdicts() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 16 }}>
      <VerdictSummary verdicts={mockVerdicts} />
      {[...mockVerdicts].sort(bySeverity).map((verdict) => (
        <VerdictCard key={verdict.verdict_id} verdict={verdict} />
      ))}
    </div>
  );
}

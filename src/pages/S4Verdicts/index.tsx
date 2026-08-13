import { VerdictCard } from './VerdictCard';
import { VerdictSummary } from './VerdictSummary';
import { PageContainer } from '../../components/PageContainer';
import { mockVerdicts } from '../../mocks/shipment.fixture';
import { bySeverity } from '../../constants/domain';

export function S4Verdicts() {
  return (
    <PageContainer>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <VerdictSummary verdicts={mockVerdicts} />
        {[...mockVerdicts].sort(bySeverity).map((verdict) => (
          <VerdictCard key={verdict.verdict_id} verdict={verdict} />
        ))}
      </div>
    </PageContainer>
  );
}

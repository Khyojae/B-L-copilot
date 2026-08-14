import { Link } from 'react-router-dom';
import { VerdictCard } from './VerdictCard';
import { VerdictSummary } from './VerdictSummary';
import { PageContainer } from '../../components/PageContainer';
import { mockShipment, mockVerdicts } from '../../mocks/shipment.fixture';
import { bySeverity } from '../../constants/domain';

export function S4Verdicts() {
  return (
    <PageContainer narrow>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Link to={`/shipments/${mockShipment.shipment_id}/report`} className="btn btn-primary">
            리포트 생성
          </Link>
        </div>

        <VerdictSummary verdicts={mockVerdicts} />
        {[...mockVerdicts].sort(bySeverity).map((verdict) => (
          <VerdictCard key={verdict.verdict_id} verdict={verdict} />
        ))}
      </div>
    </PageContainer>
  );
}

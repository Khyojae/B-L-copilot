import { Link } from 'react-router-dom';
import { mockShipments } from '../../mocks/shipment.fixture';
import { PageContainer } from '../../components/PageContainer';
import { EmptyState } from '../../components/EmptyState';
import { ShipmentCard } from './ShipmentCard';

// 실제 목록 API가 붙으면 이 배열이 그 응답으로 바뀌고, shipments.length === 0인
// 날이 실제로 올 수 있습니다.
const shipments = mockShipments;

export function S1Dashboard() {
  return (
    <PageContainer narrow>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <h1 style={{ margin: 0 }}>B/L Copilot</h1>
        <Link to="/shipments/new">+ 새 선적</Link>
      </div>

      {shipments.length === 0 ? (
        <EmptyState message="아직 선적이 없습니다" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {shipments.map((shipment) => (
            <ShipmentCard key={shipment.shipment_id} shipment={shipment} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}

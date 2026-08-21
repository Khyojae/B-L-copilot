import { Plus } from 'lucide-react';
import { Link } from 'react-router-dom';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import { mockShipments } from '../../mocks/shipment.fixture';
import { findShipmentData } from '../../mocks/shipmentData';
import { ShipmentCard } from './ShipmentCard';

export function S1Dashboard() {
  // 카드가 판정·필드까지 보여주므로 Shipment만으로는 부족합니다. 목록 순서는
  // mockShipments가 정하고, 각 건의 내용은 묶음에서 찾아옵니다.
  // findShipmentData가 null을 주는 건 목록에만 있고 묶음엔 없는 경우인데,
  // 지금은 없습니다 — 나중에 어긋나면 그 카드만 조용히 빠지게 해뒀습니다.
  const items = mockShipments
    .map((shipment) => findShipmentData(shipment.shipment_id))
    .filter((data): data is NonNullable<typeof data> => data !== null);

  // D-day 계산 기준 시각을 한 번만 만들어 모든 카드에 같은 "지금"을 넘깁니다.
  // 카드마다 new Date()를 부르면 자정 전후로 카드끼리 D-day가 하루 어긋납니다.
  const now = new Date();

  return (
    <PageContainer narrow>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 'var(--space-4)',
          marginBottom: 'var(--space-3)',
          textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <h1
            style={{
              margin: 0,
              fontSize: 25,
              fontWeight: 600,
              lineHeight: 1.2,
              letterSpacing: '-0.6px',
              color: 'var(--brand-primary)',
            }}
          >
            선적
          </h1>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            최근 수정순 {items.length}건
          </span>
        </div>

        <Link to="/shipments/new" className="btn btn-primary" style={{ gap: 5, fontWeight: 600 }}>
          <Plus size={14} aria-hidden="true" />새 선적
        </Link>
      </div>

      {items.length === 0 ? (
        <EmptyState message="아직 등록된 선적이 없습니다. 서류를 올려 첫 선적을 만들어보세요." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {items.map((data) => (
            <ShipmentCard key={data.shipment.shipment_id} data={data} now={now} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}

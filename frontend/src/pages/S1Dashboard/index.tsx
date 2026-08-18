import { Link, useSearchParams } from 'react-router-dom';
import { mockShipments, mockShipmentStatsById, mockAlerts } from '../../mocks/shipment.fixture';
import { PageContainer } from '../../components/PageContainer';
import { EmptyState } from '../../components/EmptyState';
import { ShipmentCard } from './ShipmentCard';
import { FilterTabs, matchesFilter, readActiveFilter } from './FilterTabs';
import { getLatestJudgedAt } from './shipmentStats';

// 실제 목록 API가 붙으면 이 배열이 그 응답으로 바뀌고, shipments.length === 0인
// 날이 실제로 올 수 있습니다.
const shipments = mockShipments;

export function S1Dashboard() {
  const [searchParams] = useSearchParams();
  const activeFilter = readActiveFilter(searchParams);
  const filteredShipments = shipments.filter((shipment) =>
    matchesFilter(activeFilter, shipment, mockShipmentStatsById[shipment.shipment_id]),
  );

  const unacknowledgedAlertCount = mockAlerts.filter((alert) => !alert.acknowledged).length;
  const latestJudgedAt = getLatestJudgedAt(mockShipmentStatsById);

  return (
    <PageContainer>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, textAlign: 'left' }}>
          <h1 style={{ margin: 0, fontSize: 36 }}>선적 {shipments.length}건</h1>
          {latestJudgedAt !== null && (
            <span
              style={{ fontSize: 13, color: 'var(--text-muted)' }}
              title="판정·하자확률은 각 선적의 마지막 검증 실행 시점 값입니다. 검증하지 않은 선적은 확률을 추정하지 않습니다."
            >
              마지막 판정 {new Date(latestJudgedAt).toLocaleString('ko-KR')} 기준 ⓘ
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {unacknowledgedAlertCount > 0 && (
            <Link to="/alerts" style={{ fontSize: 13, color: 'var(--severity-critical)', fontWeight: 600 }}>
              미확인 경보 {unacknowledgedAlertCount}건
            </Link>
          )}
          <Link to="/shipments/new">+ 새 선적</Link>
        </div>
      </div>

      {shipments.length === 0 ? (
        <EmptyState message="아직 선적이 없습니다" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <FilterTabs shipments={shipments} statsById={mockShipmentStatsById} />

          {filteredShipments.length === 0 ? (
            <EmptyState message="이 조건에 맞는 선적이 없습니다" />
          ) : (
            filteredShipments.map((shipment) => (
              <ShipmentCard
                key={shipment.shipment_id}
                shipment={shipment}
                stats={mockShipmentStatsById[shipment.shipment_id]}
              />
            ))
          )}
        </div>
      )}
    </PageContainer>
  );
}

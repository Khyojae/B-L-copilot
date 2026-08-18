import { PauseCircle } from 'lucide-react';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import { StatusBadge } from '../../components/StatusBadge';
import { bySeverity } from '../../constants/domain';
import type { ShipmentMockData } from '../../mocks/shipmentData';
import { useShipmentList } from '../../shared/shipmentStore';
import type { Alert } from '../../types/domain';
import { AlertCard } from './AlertCard';
import { DeferredCard } from './DeferredCard';

/** 미확인(acknowledged: false)이 먼저, 그 안에서는 심각도 순(위반 → 주의 → 참고) */
function byUnacknowledgedThenSeverity(a: Alert, b: Alert): number {
  if (a.acknowledged !== b.acknowledged) return a.acknowledged ? 1 : -1;
  return bySeverity(a, b);
}

/**
 * S6 경보 센터 — 서류와 실제 운송 기록이 어긋난 건을 전 선적에서 모아 봅니다.
 *
 * 전역 화면이라 상단에 선적 하나를 고정하지 않습니다. 대신 선적별 그룹 헤더를
 * 반복해서, 어느 선적의 경보인지 카드 위에서 바로 읽히게 합니다. 탭도 두지
 * 않습니다 — 탭은 "하나를 고르면 나머지는 안 보인다"는 뜻인데, 경보 센터는
 * 여러 선적을 한눈에 훑는 자리입니다.
 */
export function S6Alerts() {
  // 목록 순서는 S1과 같은 mockShipments를 따릅니다 — 두 화면의 선적 순서가
  // 다르면 같은 데이터인데 다른 목록처럼 보입니다.
  const groups = useShipmentList().map((data) => ({
      data,
      alerts: [...data.alerts].sort(byUnacknowledgedThenSeverity),
      // 판정 보류는 아래 별도 구역에서 다룹니다
      deferred: data.verdicts.filter((verdict) => verdict.result === 'DEFERRED'),
  }));

  const withAlerts = groups.filter((group) => group.alerts.length > 0);
  const withDeferred = groups.filter((group) => group.deferred.length > 0);
  const unacknowledged = withAlerts
    .flatMap((group) => group.alerts)
    .filter((alert) => !alert.acknowledged).length;

  return (
    <PageContainer narrow>
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 'var(--space-2)',
          flexWrap: 'wrap',
          marginBottom: 'var(--space-3)',
          textAlign: 'left',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22 }}>경보 센터</h1>
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: 'keep-all' }}>
          서류와 실제 운송 기록이 어긋난 건 — 미확인 먼저, 그 안에서 심각도 순
        </span>
        <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />
        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)' }}>
          미확인 {unacknowledged}건
        </span>
      </header>

      {withAlerts.length === 0 ? (
        // 어댑터가 아직 안 붙은 것과 "정말 어긋난 게 없는 것"은 다르지만, 어느
        // 쪽이든 경보를 지어내지는 않습니다 (§5.6)
        <EmptyState message="지금 올라온 경보가 없습니다." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {withAlerts.map(({ data, alerts }) => (
            // 헤더와 카드들을 한 덩어리로 붙입니다 (index.css의 .alert-group)
            <section key={data.shipment.shipment_id} className="alert-group">
              <ShipmentGroupHeader data={data} count={`경보 ${alerts.length}건`} />
              {alerts.map((alert) => (
                <AlertCard
                  key={alert.alert_id}
                  alert={alert}
                  fields={data.fields}
                  realityEvents={data.realityEvents}
                  suggestions={data.suggestions}
                />
              ))}
            </section>
          ))}
        </div>
      )}

      {withDeferred.length > 0 && (
        <section style={{ marginTop: 'var(--space-6)', textAlign: 'left' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              flexWrap: 'wrap',
              marginBottom: 'var(--space-2)',
            }}
          >
            <PauseCircle size={16} color="var(--text-muted)" aria-hidden="true" />
            <h2 style={{ margin: 0, fontSize: 15 }}>
              판정 보류 {withDeferred.reduce((sum, group) => sum + group.deferred.length, 0)}건
            </h2>
            <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: 'keep-all' }}>
              — 아직 판단이 끝나지 않았습니다
            </span>
          </div>

          {/* 위 경보 목록과 달리 선적별 그룹 헤더를 반복하지 않습니다. 선적이
              한 건뿐일 때 같은 줄("HLCUBUS2608001 · 검토 중 · L/C …")이 두 번
              나왔습니다. 어느 선적인지는 카드가 B/L 번호로 밝힙니다.
              선적이 여러 건이 되면 묶는 방식을 다시 봅니다. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {withDeferred.flatMap(({ data, deferred }) =>
              deferred.map((verdict) => (
                <DeferredCard
                  key={verdict.verdict_id}
                  verdict={verdict}
                  fields={data.fields}
                  shipment={data.shipment}
                />
              )),
            )}
          </div>
        </section>
      )}
    </PageContainer>
  );
}

/** 선적별 그룹 헤더 — B/L 번호 · 상태 뱃지 · L/C 번호 */
function ShipmentGroupHeader({ data, count }: { data: ShipmentMockData; count: string }) {
  const { shipment } = data;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        flexWrap: 'wrap',
        padding: '12px 18px',
        border: '1px solid var(--border-default)',
        // 모서리는 .alert-group이 정합니다 — 여기서 인라인으로 주면 첫/마지막
        // 카드만 깎는 규칙을 덮어버립니다
        backgroundColor: 'var(--bg-card)',
      }}
    >
      {shipment.bl_no !== null ? (
        <strong style={{ fontSize: 15.5, letterSpacing: '-0.2px' }}>{shipment.bl_no}</strong>
      ) : (
        <span style={{ fontSize: 15, color: 'var(--text-muted)', fontStyle: 'italic' }}>
          B/L 번호 미발급
        </span>
      )}
      <StatusBadge status={shipment.status} />
      <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        L/C {shipment.lc_no ?? '-'}
      </span>
      <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{count}</span>
    </div>
  );
}

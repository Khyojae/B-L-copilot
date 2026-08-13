import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { mockAlerts, mockRealityEvents, mockShipment } from '../../mocks/shipment.fixture';
import { StatusBadge } from '../../components/StatusBadge';
import { SeverityBadge } from '../../components/SeverityBadge';
import type { RealityEvent } from '../../types/domain';

/** RealityEvent.precision을 지킴 — DATE면 시각을 표시하지 않음 (§5.6) */
function formatEventTime(event: RealityEvent): string {
  const date = new Date(event.occurred_at);
  return event.precision === 'DATE' ? date.toLocaleDateString('ko-KR') : date.toLocaleString('ko-KR');
}

export function S5Timeline() {
  // 화면전이_정의.md: "경보 카드 클릭 → /shipments/:id?event=<event_id> →
  // 타임라인에서 해당 마커로 스크롤". 이 페이지가 그 "스크롤"을 담당함
  const [searchParams] = useSearchParams();
  const highlightedEventId = searchParams.get('event');
  const highlightedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (highlightedEventId !== null) {
      highlightedRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [highlightedEventId]);

  const shipmentAlerts = mockAlerts.filter(
    (alert) => alert.shipment_id === mockShipment.shipment_id,
  );
  const sortedEvents = [...mockRealityEvents].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
  );

  return (
    <div style={{ padding: 32, textAlign: 'left' }}>
      <h1 style={{ textAlign: 'left' }}>선적 상세</h1>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 16,
          border: '1px solid var(--border)',
          borderRadius: 8,
          backgroundColor: 'var(--card-bg)',
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <strong>{mockShipment.bl_no ?? '-'}</strong>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            L/C {mockShipment.lc_no ?? '-'} · 화물관리번호 {mockShipment.cargo_control_no ?? '-'}
          </span>
          {mockShipment.lc_expiry_date !== null && (
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              L/C 유효기일 {mockShipment.lc_expiry_date}
            </span>
          )}
        </div>
        <StatusBadge status={mockShipment.status} />
      </div>

      {shipmentAlerts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ margin: '0 0 8px', fontWeight: 600 }}>경보 {shipmentAlerts.length}건</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {shipmentAlerts.map((alert) => (
              <div
                key={alert.alert_id}
                style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}
              >
                <SeverityBadge severity={alert.severity} />
                <span>{alert.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <h2 style={{ textAlign: 'left' }}>타임라인</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sortedEvents.map((event) => {
          const isHighlighted = event.event_id === highlightedEventId;
          return (
            <div
              key={event.event_id}
              ref={isHighlighted ? highlightedRef : undefined}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
                padding: 12,
                border: isHighlighted ? '1.5px solid var(--accent)' : '1px solid var(--border)',
                borderRadius: 8,
                backgroundColor: isHighlighted ? 'var(--accent-bg)' : 'var(--card-bg)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong>{event.event_type}</strong>
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                  {formatEventTime(event)}
                </span>
              </div>
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                출처 {event.source} · 신뢰등급 {event.trust_grade}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

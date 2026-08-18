import { useEffect, useRef } from 'react';
import { FileQuestion, SatelliteDish } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';
import { findShipmentData } from '../../mocks/shipmentData';
import { StatusBadge } from '../../components/StatusBadge';
import { SeverityBadge } from '../../components/SeverityBadge';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import type { RealityEvent } from '../../types/domain';

/** RealityEvent.precision을 지킴 — DATE면 시각을 표시하지 않음 (§5.6) */
function formatEventTime(event: RealityEvent): string {
  const date = new Date(event.occurred_at);
  return event.precision === 'DATE' ? date.toLocaleDateString('ko-KR') : date.toLocaleString('ko-KR');
}

export function S5Timeline() {
  const { id } = useParams();
  const data = findShipmentData(id);

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

  // 훅(useSearchParams·useRef·useEffect)을 전부 부른 다음에 "선적 없음"을
  // 처리합니다 — 훅 위에서 return하면 호출 순서가 깨져 React가 에러를 냅니다
  if (data === null) {
    return (
      <PageContainer narrow>
        <EmptyState icon={FileQuestion} message={`선적 ${id ?? ''}을(를) 찾을 수 없습니다.`} />
      </PageContainer>
    );
  }

  const { shipment, realityEvents, alerts } = data;
  const sortedEvents = [...realityEvents].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
  );

  return (
    <PageContainer narrow>
      <div style={{ textAlign: 'left' }}>
        <h1 style={{ textAlign: 'left' }}>선적 상세</h1>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: 'var(--space-3)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-card)',
            backgroundColor: 'var(--bg-card)',
            marginBottom: 16,
          }}
        >
          {/* 항목·순서를 S3 초안 편집기와 맞췄습니다 — B/L · 상태 · L/C · 선적ID.
              타임라인은 기한을 같이 봐야 해서 화물관리번호·L/C 유효기일만
              아랫줄에 덧붙입니다 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                flexWrap: 'wrap',
              }}
            >
              {shipment.bl_no !== null ? (
                <strong style={{ fontSize: 18, letterSpacing: '-0.2px' }}>{shipment.bl_no}</strong>
              ) : (
                <span style={{ fontSize: 16, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                  B/L 번호 미발급
                </span>
              )}
              <StatusBadge status={shipment.status} />
              <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                L/C {shipment.lc_no ?? '-'}
              </span>
              <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                {shipment.shipment_id}
              </span>
            </div>
            <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
              화물관리번호 {shipment.cargo_control_no ?? '-'}
              {shipment.lc_expiry_date !== null && ` · L/C 유효기일 ${shipment.lc_expiry_date}`}
            </span>
          </div>
        </div>

        {alerts.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ margin: '0 0 8px', fontWeight: 600 }}>경보 {alerts.length}건</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {alerts.map((alert) => (
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
        {sortedEvents.length === 0 ? (
          // 픽스처에 이 선적의 이벤트가 없습니다. 이벤트를 지어내지 않고 없다고
          // 씁니다. 다만 §5.6이 "데이터 없음을 정상으로 판단하지 않는다"고 정해둔
          // 만큼, "이상 없음"이 아니라 "아직 안 들어왔다"로 읽히게 문구를 잡았습니다.
          // (어댑터 연결 상태 표시(AdapterStatus)는 아직 안 만들었습니다)
          <EmptyState icon={SatelliteDish} message="아직 현실 대조 데이터가 없습니다." />
        ) : (
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
                  border: isHighlighted
                    ? '1.5px solid var(--brand-primary)'
                    : '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-card)',
                  boxShadow: 'var(--shadow-card)',
                  backgroundColor: isHighlighted ? 'var(--brand-primary-light)' : 'var(--bg-card)',
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
        )}
      </div>
    </PageContainer>
  );
}

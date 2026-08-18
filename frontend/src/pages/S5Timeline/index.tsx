import { useEffect, useRef } from 'react';
import { FileQuestion, SatelliteDish } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { findShipmentData } from '../../mocks/shipmentData';
import { ShipmentHeader } from '../../components/ShipmentHeader';
import { SeverityBadge } from '../../components/SeverityBadge';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import type { Alert, RealityEvent } from '../../types/domain';

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

  // 이 이벤트를 근거로 삼는 경보 찾기 — 타임라인 위에 "경보 근거" 표식을 답니다.
  // 경보 내용 자체(근거 대조·이동)는 S6가 맡습니다. 두 화면이 같은 경보를
  // 나란히 보여주면 어느 쪽이 본체인지 알 수 없어서, 여기서는 표식만 둡니다.
  const alertsOfEvent = (eventId: string): Alert[] =>
    alerts.filter((alert) => alert.reality_event_ids.includes(eventId));

  // ?event=<id>로 들어오면 그 이벤트만이 아니라, 그 이벤트를 근거로 쓰는
  // 경보의 근거 이벤트를 전부 강조합니다.
  //
  // 화면전이_정의.md §S6→S5: "경보는 서류측·현실측 근거 이벤트를 각각 1건 이상
  // 보유하므로, 타임라인에서 두 지점을 연결해 보여준다". 하나만 강조하면 무엇과
  // 무엇이 어긋났는지가 안 보입니다. ?event= 규칙은 그대로 두고(문서 수정 불필요)
  // S5가 나머지 근거를 스스로 찾습니다.
  const highlightedEventIds = new Set<string>();
  if (highlightedEventId !== null) {
    highlightedEventIds.add(highlightedEventId);
    for (const alert of alertsOfEvent(highlightedEventId)) {
      for (const eventId of alert.reality_event_ids) highlightedEventIds.add(eventId);
    }
  }
  const sortedEvents = [...realityEvents].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
  );

  return (
    <PageContainer narrow>
      <div style={{ textAlign: 'left' }}>
        <h1 style={{ textAlign: 'left' }}>선적 상세</h1>

        <ShipmentHeader shipment={shipment} boxed>
          <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            화물관리번호 {shipment.cargo_control_no ?? '-'}
            {shipment.lc_expiry_date !== null && ` · L/C 유효기일 ${shipment.lc_expiry_date}`}
          </span>
        </ShipmentHeader>

        <div style={{ height: 16 }} />

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
            const isHighlighted = highlightedEventIds.has(event.event_id);
            // 스크롤은 URL이 직접 가리킨 이벤트로만 갑니다
            const isScrollTarget = event.event_id === highlightedEventId;
            const eventAlerts = alertsOfEvent(event.event_id);
            return (
              <div
                key={event.event_id}
                ref={isScrollTarget ? highlightedRef : undefined}
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

                {eventAlerts.length > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-2)',
                      flexWrap: 'wrap',
                      paddingTop: 6,
                      borderTop: '1px solid var(--border-default)',
                    }}
                  >
                    {eventAlerts.map((alert) => (
                      <SeverityBadge key={alert.alert_id} severity={alert.severity} />
                    ))}
                    <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                      경보 {eventAlerts.length}건의 근거
                    </span>
                    <Link to="/alerts" style={{ fontSize: 12.5 }}>
                      경보 센터에서 보기
                    </Link>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        )}
      </div>
    </PageContainer>
  );
}

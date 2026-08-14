import { Link } from 'react-router-dom';
import type { Alert } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';
import { SEVERITY } from '../../constants/domain';

interface AlertCardProps {
  alert: Alert;
}

export function AlertCard({ alert }: AlertCardProps) {
  // 화면전이_정의.md: "경보 카드 클릭 → /shipments/:id?event=<event_id> →
  // 타임라인에서 해당 마커로 스크롤". reality_event_ids는 여러 건일 수 있지만
  // 이동 경로는 하나만 받으므로, 가장 핵심 근거인 첫 번째 현실 이벤트로 이동합니다.
  const primaryEventId = alert.reality_event_ids[0];
  const meta = SEVERITY[alert.severity];

  return (
    <Link
      to={`/shipments/${alert.shipment_id}?event=${primaryEventId}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 'var(--space-3)',
        borderTop: '1px solid var(--border-default)',
        borderRight: '1px solid var(--border-default)',
        borderBottom: '1px solid var(--border-default)',
        borderLeft: `4px solid var(${meta.colorVar})`,
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
        textAlign: 'left',
        textDecoration: 'none',
        color: 'inherit',
        opacity: alert.acknowledged ? 0.7 : 1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SeverityBadge severity={alert.severity} />
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: alert.acknowledged ? 'var(--text-muted)' : 'var(--brand-primary)',
          }}
        >
          {alert.acknowledged ? '확인됨' : '미확인'}
        </span>
      </div>

      <strong>{alert.bl_no}</strong>
      <span style={{ color: 'var(--text)' }}>{alert.message}</span>
    </Link>
  );
}

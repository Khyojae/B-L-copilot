import { Link } from 'react-router-dom';
import type { Shipment } from '../../types/domain';
import { StatusBadge } from '../../components/StatusBadge';

interface ShipmentCardProps {
  shipment: Shipment;
}

export function ShipmentCard({ shipment }: ShipmentCardProps) {
  return (
    <Link
      to={`/shipments/${shipment.shipment_id}/verdicts`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 'var(--space-3)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
        textAlign: 'left',
        textDecoration: 'none',
        color: 'inherit',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <strong>{shipment.bl_no ?? '-'}</strong>
        <StatusBadge status={shipment.status} />
      </div>

      <span style={{ color: 'var(--text)' }}>L/C {shipment.lc_no ?? '-'}</span>

      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        마지막 수정: {new Date(shipment.updated_at).toLocaleString('ko-KR')}
      </span>
    </Link>
  );
}

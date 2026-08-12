import type { ShipmentStatus } from '../types/domain';
import { SHIPMENT_STATUS } from '../constants/domain';

interface StatusBadgeProps {
  status: ShipmentStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const meta = SHIPMENT_STATUS[status];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 600,
        color: `var(${meta.colorVar})`,
        border: `1px solid var(${meta.colorVar})`,
      }}
    >
      {meta.label}
    </span>
  );
}

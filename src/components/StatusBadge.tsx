import type { ShipmentStatus } from '../types/domain';
import { SHIPMENT_STATUS } from '../constants/domain';

interface StatusBadgeProps {
  status: ShipmentStatus;
}

/**
 * 선적 상태 뱃지.
 *
 * 테두리만 두르던 것을 배경까지 채우는 방식으로 바꿨습니다 — 카드 목록에서
 * 상태가 한눈에 안 들어온다는 지적이 있었고, 옅은 테두리보다 채운 알약이
 * 훨씬 빨리 읽힙니다. 색은 SHIPMENT_STATUS의 colorVar를 그대로 씁니다.
 *
 * 글자는 흰색 고정입니다. 상태 6색이 전부 중간~진한 채도라 흰 글자로 대비가
 * 확보되고, 다크모드에서도 상태색이 더 밝아지므로 그대로 성립합니다.
 */
export function StatusBadge({ status }: StatusBadgeProps) {
  const meta = SHIPMENT_STATUS[status];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        flexShrink: 0,
        padding: '3px 9px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 1.4,
        whiteSpace: 'nowrap',
        color: '#fff',
        backgroundColor: `var(${meta.colorVar})`,
      }}
    >
      {meta.label}
    </span>
  );
}

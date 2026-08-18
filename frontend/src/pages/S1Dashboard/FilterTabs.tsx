import { useSearchParams } from 'react-router-dom';
import type { Shipment, ShipmentStats } from '../../types/domain';
import { hasViolation, isDueSoon } from './shipmentStats';

export type DashboardFilter = 'ALL' | 'VIOLATION' | 'DUE_SOON';

const FILTER_LABEL: Record<DashboardFilter, string> = {
  ALL: '전체',
  VIOLATION: '위반 있음',
  DUE_SOON: '기한 임박',
};

const FILTER_ORDER: DashboardFilter[] = ['ALL', 'VIOLATION', 'DUE_SOON'];

/** 화면전이_정의.md §6에 이미 있는 "?status= | S1 | 목록 필터" 파라미터를 그대로
 *  씀 — 값만 ShipmentStatus 하나가 아니라 이 세 카테고리로 넓혀서 씀 */
export function matchesFilter(filter: DashboardFilter, shipment: Shipment, stats: ShipmentStats): boolean {
  if (filter === 'VIOLATION') return hasViolation(stats);
  if (filter === 'DUE_SOON') return isDueSoon(shipment);
  return true;
}

export function readActiveFilter(searchParams: URLSearchParams): DashboardFilter {
  const raw = searchParams.get('status');
  return raw === 'VIOLATION' || raw === 'DUE_SOON' ? raw : 'ALL';
}

interface FilterTabsProps {
  shipments: Shipment[];
  statsById: Record<string, ShipmentStats>;
}

export function FilterTabs({ shipments, statsById }: FilterTabsProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const active = readActiveFilter(searchParams);

  const counts: Record<DashboardFilter, number> = {
    ALL: shipments.length,
    VIOLATION: shipments.filter((s) => matchesFilter('VIOLATION', s, statsById[s.shipment_id])).length,
    DUE_SOON: shipments.filter((s) => matchesFilter('DUE_SOON', s, statsById[s.shipment_id])).length,
  };

  function selectFilter(filter: DashboardFilter) {
    const next = new URLSearchParams(searchParams);
    if (filter === 'ALL') {
      next.delete('status');
    } else {
      next.set('status', filter);
    }
    setSearchParams(next);
  }

  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {FILTER_ORDER.map((filter) => {
        const isActive = filter === active;
        return (
          <button
            key={filter}
            type="button"
            onClick={() => selectFilter(filter)}
            style={{
              padding: '6px 12px',
              borderRadius: 999,
              fontSize: 12.5,
              fontWeight: isActive ? 600 : 500,
              border: `1px solid ${isActive ? 'var(--brand-primary)' : 'var(--border-default)'}`,
              color: isActive ? 'var(--brand-primary)' : 'var(--text-secondary)',
              backgroundColor: isActive ? 'var(--brand-primary-light)' : 'var(--bg-card)',
            }}
          >
            {FILTER_LABEL[filter]} {counts[filter]}
          </button>
        );
      })}
    </div>
  );
}

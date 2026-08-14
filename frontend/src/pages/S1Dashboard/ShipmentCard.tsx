import { Link } from 'react-router-dom';
import type { Shipment } from '../../types/domain';
import { StatusBadge } from '../../components/StatusBadge';

interface ShipmentCardProps {
  shipment: Shipment;
}

export function ShipmentCard({ shipment }: ShipmentCardProps) {
  return (
    <div
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
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {shipment.bl_no !== null ? (
          <strong>{shipment.bl_no}</strong>
        ) : (
          // B/L 번호는 서류 추출 후에 채워지는 값이라, DRAFT 단계엔 없는 게
          // 정상입니다. "-"로 두면 빈 값(오류)처럼 보여서 이유를 문구로 밝힘
          <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>B/L 번호 미발급</span>
        )}
        <StatusBadge status={shipment.status} />
      </div>

      <span style={{ color: 'var(--text)' }}>L/C {shipment.lc_no ?? '-'}</span>

      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        마지막 수정: {new Date(shipment.updated_at).toLocaleString('ko-KR')}
      </span>

      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        <Link to={`/shipments/${shipment.shipment_id}/draft`} className="btn btn-secondary" style={{ flex: 1 }}>
          초안 편집
        </Link>
        <Link
          to={`/shipments/${shipment.shipment_id}/verdicts`}
          className="btn btn-secondary"
          style={{ flex: 1 }}
        >
          검증 결과 보기
        </Link>
      </div>
    </div>
  );
}

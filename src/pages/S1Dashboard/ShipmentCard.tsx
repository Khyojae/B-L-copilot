import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Severity, Shipment, ShipmentStats } from '../../types/domain';
import { StatusBadge } from '../../components/StatusBadge';
import { SeverityBadge } from '../../components/SeverityBadge';
import { SEVERITY } from '../../constants/domain';
import {
  getDDayLabel,
  getNextAction,
  getRequiredFieldNames,
  getRouteLine,
  getVerdictCounts,
} from './shipmentStats';

interface ShipmentCardProps {
  shipment: Shipment;
  stats: ShipmentStats;
}

interface CardAction {
  label: string;
  to: string;
}

/** 상태별 CTA 버튼 — 첫 번째가 항상 주요 동작(채워진 버튼) */
function getActions(shipment: Shipment, stats: ShipmentStats): CardAction[] {
  const id = shipment.shipment_id;
  switch (shipment.status) {
    case 'DRAFT':
      return [
        // ⚠ 지금 코드에는 "기존 선적에 서류를 추가"하는 라우트가 따로 없어서,
        // 일단 새 업로드 화면으로 보냅니다. 완전히 맞는 흐름은 아님 — 실제
        // "이 선적에 서류 추가" 경로가 생기면 여기를 바꿔야 합니다.
        { label: '서류 업로드', to: '/shipments/new' },
        { label: '초안 편집', to: `/shipments/${id}/draft` },
      ];
    case 'VERIFIED':
      return [
        { label: '리포트 보기', to: `/shipments/${id}/report` },
        { label: `검증 결과 ${stats.verdicts.length}건`, to: `/shipments/${id}/verdicts` },
      ];
    case 'REVIEWING':
      return [
        { label: '초안 편집', to: `/shipments/${id}/draft` },
        { label: `검증 결과 ${stats.verdicts.length}건`, to: `/shipments/${id}/verdicts` },
      ];
    default: // SUBMITTED · MONITORING · CLOSED — 편집 불가
      return [{ label: '판정 기록 보기', to: `/shipments/${id}` }];
  }
}

function probabilityColor(probability: number): string {
  if (probability >= 0.5) return 'var(--severity-critical)';
  if (probability >= 0.2) return 'var(--severity-warning)';
  return 'var(--status-verified)';
}

const statCellStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: 'var(--space-3)',
  borderLeft: '1px solid var(--border-default)',
};

function StatCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={statCellStyle}>
      <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-muted)' }}>{label}</span>
      {children}
    </div>
  );
}

function VerdictCountPill({ severity, count }: { severity: Severity; count: number }) {
  const meta = SEVERITY[severity];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <SeverityBadge severity={severity} />
      <span style={{ fontSize: 12.5, fontWeight: 700, color: `var(${meta.colorVar})` }}>{count}</span>
    </span>
  );
}

export function ShipmentCard({ shipment, stats }: ShipmentCardProps) {
  const route = getRouteLine(stats.fields);
  const requiredNames = getRequiredFieldNames(stats.fields);
  const counts = getVerdictCounts(stats.verdicts);
  const dday = getDDayLabel(shipment.lc_expiry_date);
  const nextAction = getNextAction(shipment, stats);
  const actions = getActions(shipment, stats);

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 260px',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg-card)',
        overflow: 'hidden',
      }}
    >
      <div style={{ padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          {shipment.bl_no !== null ? (
            <strong style={{ fontSize: 17 }}>{shipment.bl_no}</strong>
          ) : (
            <span style={{ fontSize: 17, color: 'var(--text-muted)', fontStyle: 'italic' }}>
              B/L 번호 미발급
            </span>
          )}
          <StatusBadge status={shipment.status} />
          <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>L/C {shipment.lc_no ?? '-'}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, fontSize: 13 }}>
          <span style={{ fontWeight: 600 }}>{route.route}</span>
          <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>{route.detail}</span>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '0.8fr 1.7fr 1.15fr 1fr',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            backgroundColor: 'var(--bg-page)',
          }}
        >
          <div style={{ ...statCellStyle, borderLeft: 'none' }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-muted)' }}>하자 확률</span>
            {stats.prediction === null ? (
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-muted)' }}>검증 전</span>
            ) : (
              <span style={{ fontSize: 30, fontWeight: 700, lineHeight: 1, color: probabilityColor(stats.prediction.probability) }}>
                {Math.round(stats.prediction.probability * 100)}%
              </span>
            )}
          </div>

          <StatCell label="판정">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              <VerdictCountPill severity="Critical" count={counts.critical} />
              <VerdictCountPill severity="Warning" count={counts.warning} />
              <VerdictCountPill severity="Info" count={counts.info} />
            </div>
          </StatCell>

          <StatCell label="필수 확인">
            {requiredNames.length === 0 ? (
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--status-verified)' }}>없음</span>
            ) : (
              <>
                <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--severity-critical)' }}>
                  {requiredNames.length}건 남음
                </span>
                <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{requiredNames.join(' · ')}</span>
              </>
            )}
          </StatCell>

          <StatCell label="L/C 유효기일">
            {dday === null ? (
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-muted)' }}>-</span>
            ) : (
              <>
                <span
                  style={{
                    fontSize: 16,
                    fontWeight: 700,
                    color: dday.overdue ? 'var(--severity-critical)' : 'var(--text-primary)',
                  }}
                >
                  {dday.text}
                </span>
                <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{shipment.lc_expiry_date}</span>
              </>
            )}
          </StatCell>
        </div>
      </div>

      <div
        style={{
          borderLeft: '1px solid var(--border-default)',
          backgroundColor: 'var(--brand-primary-light)',
          padding: 'var(--space-3)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          gap: 20,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-muted)' }}>다음 할 일</span>
          <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.45 }}>{nextAction}</p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {actions.map((action, index) => (
            <Link
              key={action.to + action.label}
              to={action.to}
              className={index === 0 ? 'btn btn-primary' : 'btn btn-secondary'}
            >
              {action.label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

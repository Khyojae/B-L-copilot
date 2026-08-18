import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Verdict } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';
import { SEVERITY, labelOfField } from '../../constants/domain';

interface VerdictCardProps {
  verdict: Verdict;
  /** [해당 필드로 이동] 링크를 만들 선적 id */
  shipmentId: string;
}

export function VerdictCard({ verdict, shipmentId }: VerdictCardProps) {
  const meta = SEVERITY[verdict.severity];
  const targetField = verdict.target_fields[0];

  return (
    <div
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
        backgroundColor: `var(${meta.bgVar})`,
        textAlign: 'left',
      }}
    >
      <SeverityBadge severity={verdict.severity} />

      <p style={{ margin: 0 }}>{verdict.message}</p>

      {verdict.action_hint !== null && (
        <p style={{ margin: 0, color: 'var(--text)' }}>{verdict.action_hint}</p>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          flexWrap: 'wrap',
          marginTop: 4,
        }}
      >
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{verdict.rule_id}</span>
        <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />

        {/* 화면전이_정의.md "S4 → S3": 판정 항목은 모두 [해당 필드로 이동]을
            가져야 합니다(표시율 목표 100%, §5.3). target_fields가 여러 개면
            첫 번째로 보냅니다 — 한 번에 한 필드만 포커스할 수 있어서입니다. */}
        {targetField !== undefined && (
          <Link
            to={`/shipments/${shipmentId}/draft?focus=${targetField}`}
            className="btn btn-secondary"
            style={{ gap: 5, padding: '5px 12px', fontSize: 13 }}
          >
            {labelOfField(targetField)} 고치러 가기
            <ArrowRight size={13} aria-hidden="true" />
          </Link>
        )}
      </div>
    </div>
  );
}

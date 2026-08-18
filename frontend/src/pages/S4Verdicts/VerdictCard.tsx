import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Verdict } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';
import { SEVERITY, VERDICT_RESULT_LABEL, labelOfField } from '../../constants/domain';

interface VerdictCardProps {
  verdict: Verdict;
  /** [해당 필드로 이동] 링크를 만들 선적 id */
  shipmentId: string;
}

export function VerdictCard({ verdict, shipmentId }: VerdictCardProps) {
  const targetField = verdict.target_fields[0];

  // ⚠ 판정 보류는 심각도를 그대로 보여주면 안 됩니다.
  //   VD-003처럼 severity가 Critical이어도 result가 DEFERRED면 "아직 판단하지
  //   못한" 상태입니다. 여기서 "위반" 뱃지를 달면, 같은 화면 위쪽 요약이
  //   "위반 2 · 판정 보류 1"이라고 세는 것과 정면으로 어긋납니다
  //   (요약 집계는 shared/shipmentStats의 summarizeVerdicts가 맡습니다).
  const isDeferred = verdict.result === 'DEFERRED';
  const meta = SEVERITY[verdict.severity];
  // 보류는 심각도 색을 쓰지 않고 중립 회색으로 — S6 판정 보류 카드와 같은 방식
  const accentVar = isDeferred ? '--text-muted' : meta.colorVar;

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
        borderLeft: `4px solid var(${accentVar})`,
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: isDeferred ? 'var(--bg-card)' : `var(${meta.bgVar})`,
        textAlign: 'left',
      }}
    >
      {isDeferred ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            alignSelf: 'flex-start',
            padding: '3px 9px',
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-secondary)',
            border: '1px solid var(--border-default)',
          }}
        >
          {VERDICT_RESULT_LABEL.DEFERRED}
        </span>
      ) : (
        <SeverityBadge severity={verdict.severity} />
      )}

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

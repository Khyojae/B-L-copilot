import { AlertCircle, AlertOctagon, AlertTriangle, CircleCheck, Info } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { Severity, Verdict } from '../../types/domain';
import { SEVERITY, bySeverity } from '../../constants/domain';

/** SEVERITY.icon 문자열을 실제 아이콘으로 연결 — SeverityBadge와 같은 방식 */
const ICON_BY_NAME: Record<string, LucideIcon> = {
  'alert-octagon': AlertOctagon,
  'alert-triangle': AlertTriangle,
  info: Info,
};

/** 심각도를 정렬 순서(위반 → 주의 → 참고)대로 나열 */
const SEVERITIES_IN_ORDER = (Object.keys(SEVERITY) as Severity[]).sort(
  (a, b) => SEVERITY[a].order - SEVERITY[b].order,
);

interface CardVerdictBandProps {
  verdicts: Verdict[];
  /** 지금 검증을 막고 있는 필수 확인 필드 수 */
  requiredFieldCount: number;
}

/**
 * 카드 안 판정 요약 띠 — 심각도별 건수 + 가장 심각한 판정 한 줄.
 *
 * 목록 화면에서 "이 선적을 지금 열어봐야 하나"를 판단하는 자리라, 건수만 세지
 * 않고 제일 심각한 판정의 문장을 하나 보여줍니다. 나머지는 S4에서 봅니다.
 */
export function CardVerdictBand({ verdicts, requiredFieldCount }: CardVerdictBandProps) {
  // 아직 검증 전. "위반 0건"으로 적으면 "검사했는데 깨끗하다"로 읽히므로
  // (S4에서 이미 같은 판단을 했습니다) 검증을 안 했다고 그대로 씁니다
  if (verdicts.length === 0) {
    return (
      <Band>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            fontSize: 12,
            color: 'var(--text-secondary)',
          }}
        >
          <AlertCircle size={13} color="var(--text-muted)" aria-hidden="true" />
          아직 검증을 실행하지 않았습니다
        </span>
        {requiredFieldCount > 0 && (
          <BlockingNote count={requiredFieldCount} />
        )}
      </Band>
    );
  }

  const topVerdict = [...verdicts].sort(bySeverity)[0];
  const topMeta = SEVERITY[topVerdict.severity];
  const TopIcon = ICON_BY_NAME[topMeta.icon] ?? Info;
  const criticalCount = verdicts.filter((verdict) => verdict.severity === 'Critical').length;

  return (
    <Band>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
        {/* Critical이 0건이면 "통과"임을 따로 밝힙니다 — 건수 0을 읽어내라고
            하지 않고 문장으로 알려주는 편이 오해가 적습니다 */}
        {criticalCount === 0 && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '2px 8px',
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--status-verified)',
              backgroundColor: 'var(--brand-primary-light)',
            }}
          >
            <CircleCheck size={13} aria-hidden="true" />
            위반 없음
          </span>
        )}

        {SEVERITIES_IN_ORDER.map((severity) => {
          const count = verdicts.filter((verdict) => verdict.severity === severity).length;
          if (count === 0) return null;
          return <SeverityCount key={severity} severity={severity} count={count} />;
        })}

        {requiredFieldCount > 0 && (
          <>
            <span
              style={{ width: 1, height: 14, backgroundColor: 'var(--border-default)' }}
              aria-hidden="true"
            />
            <BlockingNote count={requiredFieldCount} />
          </>
        )}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 7,
          fontSize: 13,
          lineHeight: 1.5,
          color: 'var(--text-primary)',
        }}
      >
        <TopIcon
          size={14}
          color={`var(${topMeta.colorVar})`}
          aria-hidden="true"
          style={{ flexShrink: 0, marginTop: 3 }}
        />
        <span>
          {topVerdict.message}{' '}
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{topVerdict.rule_id}</span>
        </span>
      </div>
    </Band>
  );
}

/** 심각도별 건수 알약 — 색·아이콘·글자를 함께 씁니다 (규약 §6.2) */
function SeverityCount({ severity, count }: { severity: Severity; count: number }) {
  const meta = SEVERITY[severity];
  const Icon = ICON_BY_NAME[meta.icon] ?? Info;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: `var(${meta.colorVar})`,
        backgroundColor: `var(${meta.bgVar})`,
      }}
    >
      <Icon size={13} aria-hidden="true" />
      {meta.label} {count}
    </span>
  );
}

function BlockingNote({ count }: { count: number }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: 12,
        color: 'var(--text-secondary)',
      }}
    >
      <AlertCircle size={13} color="var(--severity-warning)" aria-hidden="true" />
      필수 확인 필드 {count}건
    </span>
  );
}

function Band({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
        padding: '13px 18px',
        borderTop: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
      }}
    >
      {children}
    </div>
  );
}

import { AlertCircle, AlertOctagon, AlertTriangle, CircleCheck, Info, PauseCircle } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Severity, Verdict } from '../../types/domain';
import { SEVERITY, VERDICT_RESULT_LABEL, bySeverity } from '../../constants/domain';
import { SEVERITIES_IN_ORDER, summarizeVerdicts } from '../../shared/shipmentStats';

/** SEVERITY.icon 문자열을 실제 아이콘으로 연결 — SeverityBadge와 같은 방식 */
const ICON_BY_NAME: Record<string, LucideIcon> = {
  'alert-octagon': AlertOctagon,
  'alert-triangle': AlertTriangle,
  info: Info,
};

interface CardVerdictBandProps {
  verdicts: Verdict[];
  /** 지금 검증을 막고 있는 필수 확인 필드 수 */
  requiredFieldCount: number;
  /** 요약 줄에서 해당 화면으로 넘어가기 위한 선적 id */
  shipmentId: string;
}

/**
 * 카드 안 판정 요약 띠 — 심각도별 건수 + 가장 심각한 판정 한 줄.
 *
 * 목록 화면에서 "이 선적을 지금 열어봐야 하나"를 판단하는 자리라, 건수만 세지
 * 않고 제일 심각한 판정의 문장을 하나 보여줍니다. 나머지는 S4에서 봅니다.
 */
export function CardVerdictBand({
  verdicts,
  requiredFieldCount,
  shipmentId,
}: CardVerdictBandProps) {
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
          <BlockingNote count={requiredFieldCount} shipmentId={shipmentId} />
        )}
      </Band>
    );
  }

  const topVerdict = [...verdicts].sort(bySeverity)[0];
  const topMeta = SEVERITY[topVerdict.severity];
  const TopIcon = ICON_BY_NAME[topMeta.icon] ?? Info;
  // 집계는 shared/shipmentStats가 맡습니다 — S3·S4와 같은 숫자를 쓰기 위해서입니다.
  // 판정 보류는 심각도 건수에서 빠지고 따로 셉니다.
  const counts = summarizeVerdicts(verdicts);

  return (
    <Band>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
        {/* Critical이 0건이면 "통과"임을 따로 밝힙니다 — 건수 0을 읽어내라고
            하지 않고 문장으로 알려주는 편이 오해가 적습니다 */}
        {counts.bySeverity.Critical === 0 && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 10px',
              borderRadius: 999,
              fontSize: 13,
              fontWeight: 700,
              color: 'var(--status-verified)',
              border: '1px solid var(--status-verified)',
            }}
          >
            <CircleCheck size={14} aria-hidden="true" />
            위반 없음
          </span>
        )}

        {SEVERITIES_IN_ORDER.map((severity) => {
          const count = counts.bySeverity[severity];
          if (count === 0) return null;
          return <SeverityCount key={severity} severity={severity} count={count} />;
        })}

        {counts.deferred > 0 && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 10px',
              borderRadius: 999,
              fontSize: 13,
              fontWeight: 700,
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-default)',
            }}
          >
            <PauseCircle size={14} aria-hidden="true" />
            {VERDICT_RESULT_LABEL.DEFERRED} {counts.deferred}
          </span>
        )}

        {requiredFieldCount > 0 && (
          <>
            <span
              style={{ width: 1, height: 14, backgroundColor: 'var(--border-default)' }}
              aria-hidden="true"
            />
            <BlockingNote count={requiredFieldCount} shipmentId={shipmentId} />
          </>
        )}
      </div>

      {/* 가장 심각한 판정 한 줄 — 누르면 그 선적의 검증 결과(S4)로 갑니다 */}
      <Link
        to={`/shipments/${shipmentId}/verdicts`}
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
      </Link>
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
        padding: '3px 10px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 700,
        color: `var(${meta.colorVar})`,
        backgroundColor: `var(${meta.bgVar})`,
        // 배경이 10% 불투명도라 카드 배경(--bg-card) 위에서는 거의 안 보였습니다.
        // 같은 색 테두리를 얇게 둘러 알약의 윤곽을 살립니다.
        border: `1px solid var(${meta.colorVar})`,
      }}
    >
      <Icon size={14} aria-hidden="true" />
      {meta.label} {count}
    </span>
  );
}

/**
 * "필수 확인 필드 N건" — 누르면 그 선적의 초안 편집기로 갑니다.
 *
 * 필드 단위로 바로 가려면 ?field= 같은 URL 규칙이 필요한데, 화면전이_정의.md에
 * 정의된 게 없어서 선적 단위 링크까지만 겁니다. 필드 딥링크는 팀 합의 후 별건.
 */
function BlockingNote({ count, shipmentId }: { count: number; shipmentId: string }) {
  return (
    <Link
      to={`/shipments/${shipmentId}/draft`}
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
    </Link>
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

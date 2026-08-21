import { ArrowRight, Info } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Alert, FieldValue, RealityEvent, Suggestion } from '../../types/domain';
import { SeverityBadge } from '../../components/SeverityBadge';
import { GradeBadge } from '../../components/GradeBadge';
import { SEVERITY, UNSETTLED_LABEL, labelOfField } from '../../constants/domain';
import { effectiveGradeOf } from '../../shared/shipmentStats';
import { EvidenceColumns, EvidencePanel, formatEventTime } from './AlertParts';

interface AlertCardProps {
  alert: Alert;
  /** 이 선적의 필드 — 서류측 근거(원인 필드)의 현재 상태를 읽습니다 */
  fields: FieldValue[];
  /** 이 선적의 현실 대조 이벤트 — 현실측 근거를 찾습니다 */
  realityEvents: RealityEvent[];
  /** 이 선적의 교정 제안 — 원인 필드에 대기 중인 제안이 있는지 표시 */
  suggestions: Suggestion[];
}

/**
 * 경보 카드 하나 — 서류와 실제 운송 기록이 어긋난 건.
 *
 * 근거를 서류측·현실측 두 칸으로 나눠 보여줍니다. 어긋남을 판단하려면 양쪽을
 * 나란히 봐야 하는데, 한 줄로 이어 쓰면 무엇과 무엇이 다른지 읽어내기 어렵습니다.
 *
 * ⚠ "확인 처리" 버튼은 넣지 않았습니다. acknowledged를 바꿀 수단이 없어서
 *   눌러도 새로고침하면 원복됩니다. 상태는 확인됨/미확인 표시로만 둡니다.
 *
 * 카드 전체를 링크로 감싸지 않습니다 — 이동 경로가 둘(원인 필드 고치기 /
 * 타임라인 근거 보기)이라 카드를 누르면 어디로 갈지 알 수 없습니다.
 */
export function AlertCard({ alert, fields, realityEvents, suggestions }: AlertCardProps) {
  const meta = SEVERITY[alert.severity];
  // 서류측 근거는 FieldValue.field_name을 가리킵니다 (types/domain.ts §F6)
  const causeFieldName = alert.document_event_ids[0];
  const causeField = fields.find((field) => field.field_name === causeFieldName);
  const events = alert.reality_event_ids
    .map((id) => realityEvents.find((event) => event.event_id === id))
    .filter((event): event is RealityEvent => event !== undefined);

  return (
    <article
      style={{
        display: 'flex',
        border: '1px solid var(--border-default)',
        borderLeft: `5px solid var(${meta.colorVar})`,
        // 모서리는 .alert-group이 정합니다 (그룹 안에서만 쓰이는 카드입니다)
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg)',
        overflow: 'hidden',
        textAlign: 'left',
      }}
    >
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <SeverityBadge severity={alert.severity} />
            <AckBadge acknowledged={alert.acknowledged} />
            <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {new Date(alert.created_at).toLocaleString('ko-KR')} 발생
            </span>
          </div>

          <p
            style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 600,
              lineHeight: 1.55,
              color: 'var(--text-primary)',
              wordBreak: 'keep-all',
            }}
          >
            {alert.message}
          </p>
        </div>

        <EvidenceColumns>
          <EvidencePanel title="서류측 근거">
            {causeField === undefined ? (
              <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                이 선적에서 {causeFieldName} 필드를 찾지 못했습니다
              </span>
            ) : (
              <CauseField field={causeField} suggestions={suggestions} />
            )}
          </EvidencePanel>

          <EvidencePanel
            title={`현실측 근거 ${events.length}건`}
            tip={events
              .map((event) => `${event.event_id} (${event.source} · ${event.source_event_code})`)
              .join(' · ')}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {events.map((event) => (
                <div
                  key={event.event_id}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}
                >
                  {/* event_type은 fixture의 값을 그대로 씁니다 — 화면에서 임의로
                      줄이면 데이터와 표시가 달라집니다 */}
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {event.event_type}
                  </span>
                  <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                    {formatEventTime(event)}
                    {event.quantity !== null && ` · ${event.quantity}대`}
                    {event.location !== null && ` · ${event.location}`}
                  </span>
                </div>
              ))}
            </div>
          </EvidencePanel>
        </EvidenceColumns>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            flexWrap: 'wrap',
            padding: '13px 20px',
            borderTop: '1px solid var(--border-default)',
          }}
        >
          {/* 화면전이_정의.md §6의 ?focus= 규칙 — S3 진입 시 이 필드를 포커스합니다 */}
          {causeField !== undefined && (
            <Link
              to={`/shipments/${alert.shipment_id}/draft?focus=${causeField.field_name}`}
              className="btn btn-primary"
              style={{ gap: 5, padding: '8px 16px', fontSize: 13, fontWeight: 600 }}
            >
              {labelOfField(causeField.field_name)} 고치러 가기
              <ArrowRight size={13} aria-hidden="true" />
            </Link>
          )}
          <Link
            to={`/shipments/${alert.shipment_id}?event=${alert.reality_event_ids[0]}`}
            className="btn btn-secondary"
            style={{ padding: '8px 14px', fontSize: 13 }}
          >
            타임라인 근거 보기
          </Link>
        </div>
      </div>
    </article>
  );
}

/** 원인 필드의 지금 상태 — 등급 뱃지 + 값(충돌 중이면 "미확정") */
function CauseField({ field, suggestions }: { field: FieldValue; suggestions: Suggestion[] }) {
  const grade = effectiveGradeOf(field, {});
  const pending = suggestions.filter((suggestion) => suggestion.field === field.field_name).length;
  const candidateCount = field.candidates?.length ?? 0;

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-primary)' }}>
          {labelOfField(field.field_name)}
        </span>
        <GradeBadge grade={grade} size="sm" />
      </div>

      {field.conflict_flag ? (
        // 충돌이 안 풀린 필드는 value에 후보 하나가 들어 있어도 확정값이 아닙니다.
        // S3 FieldRow와 같은 방식으로 "미확정"이라고 씁니다 (두 화면이 어긋나지 않게).
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: 'keep-all' }}>
          {UNSETTLED_LABEL} — 후보 {candidateCount}건 중 아직 고르지 않았습니다
        </span>
      ) : (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-muted)' }}>현재값</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            {field.value ?? '-'}
          </span>
        </div>
      )}

      {pending > 0 && (
        <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>교정 제안 {pending}건 대기</span>
      )}
    </>
  );
}

/** 확인됨 / 미확인 — 표시만 하고 바꾸지 않습니다 */
function AckBadge({ acknowledged }: { acknowledged: boolean }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '3px 9px',
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: acknowledged ? 'var(--text-secondary)' : 'var(--brand-primary)',
        border: `1px solid ${acknowledged ? 'var(--border-default)' : 'var(--brand-primary)'}`,
        backgroundColor: acknowledged ? 'transparent' : 'var(--brand-primary-light)',
      }}
    >
      {!acknowledged && <Info size={12} aria-hidden="true" />}
      {acknowledged ? '확인됨' : '미확인'}
    </span>
  );
}


import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { FieldValue, Shipment, Verdict } from '../../types/domain';
import { GradeBadge } from '../../components/GradeBadge';
import { UNSETTLED_LABEL, VERDICT_RESULT_LABEL, labelOfField } from '../../constants/domain';
import { effectiveGradeOf } from '../../shared/shipmentStats';
import { EvidenceColumns, EvidencePanel, InfoTip } from './AlertParts';

interface DeferredCardProps {
  verdict: Verdict;
  fields: FieldValue[];
  /**
   * 어느 선적의 판정인지.
   *
   * 위 경보 목록처럼 선적별 그룹 헤더를 반복하지 않고, 카드에 B/L 번호만
   * 붙입니다 — 지금은 선적이 한 건뿐이라 같은 헤더가 두 번 나왔습니다.
   * 선적이 여러 건이 되면 그때 묶는 방식을 다시 봅니다.
   */
  shipment: Shipment;
}

/**
 * 판정 보류 카드 — 경보가 아니라 검증 판정에서 온 항목.
 *
 * 경보 목록과 섞지 않는 이유: 보류는 심각도가 정해진 게 아니라 아직 판단이
 * 끝나지 않은 상태입니다. 위반·주의 사이에 끼워 넣으면 "심각도가 매겨진 문제"로
 * 읽힙니다. 그래서 별도 구역에 중립 회색으로 둡니다.
 *
 * 현실측 근거가 없는 항목이라 타임라인(S5)이 아니라 검증 결과(S4)로 보냅니다.
 */
export function DeferredCard({ verdict, fields, shipment }: DeferredCardProps) {
  // 검사 대상 — 이 판정이 보려던 필드
  const targetName = verdict.target_fields[0];
  const targetField = fields.find((field) => field.field_name === targetName);

  // 보류 원인 — 아직 확인되지 않아 검사를 막고 있는 필드.
  //
  // ⚠ 임시 우회: Verdict에 "무엇 때문에 보류됐는가"를 담는 자리가 없어서,
  //   판정 메시지에 그 필드 이름이 들어 있는지로 찾습니다. 문구가 바뀌면
  //   원인 칸이 사라지는 취약한 방식입니다 — 실제로 메시지를 영문 필드명에서
  //   한글 라벨로 바꾸자마자 한 번 깨졌습니다.
  //   한글 라벨과 영문 식별자를 모두 확인해서 어느 쪽 표기든 잡히게 했지만,
  //   근본 해결은 백엔드가 원인 필드를 따로 내려주는 것입니다.
  //   → BE_판정메시지_필드표기.md 참고
  const blockingField = fields.find(
    (field) =>
      field.field_name !== targetName &&
      (verdict.message.includes(labelOfField(field.field_name)) ||
        verdict.message.includes(field.field_name)) &&
      effectiveGradeOf(field, {}) === 'REQUIRED',
  );

  return (
    <article
      style={{
        display: 'flex',
        border: '1px solid var(--border-default)',
        borderLeft: '5px solid var(--text-muted)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-card)',
        backgroundColor: 'var(--bg)',
        overflow: 'hidden',
        textAlign: 'left',
      }}
    >
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
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

            {/* 어느 선적인지 — 그룹 헤더를 반복하는 대신 여기에 붙입니다 */}
            {shipment.bl_no !== null ? (
              <strong style={{ fontSize: 13.5, letterSpacing: '-0.2px' }}>{shipment.bl_no}</strong>
            ) : (
              <span style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                B/L 번호 미발급
              </span>
            )}
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: 'var(--text-muted)',
              }}
            >
              경보가 아니라 검증 판정에서 온 항목
              <InfoTip
                text={`${verdict.rule_id} · ${verdict.evidence.clause_text} · 판정 ${new Date(
                  verdict.judged_at,
                ).toLocaleString('ko-KR')}`}
              />
            </span>
            <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {new Date(verdict.judged_at).toLocaleString('ko-KR')} 판정
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
            {verdict.message}
          </p>
        </div>

        <EvidenceColumns>
          <EvidencePanel title="검사 대상">
            {targetField === undefined ? (
              <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                대상 필드를 찾지 못했습니다
              </span>
            ) : (
              <>
                <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {labelOfField(targetField.field_name)}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {targetField.conflict_flag ? UNSETTLED_LABEL : targetField.value ?? '-'}
                </span>
              </>
            )}
          </EvidencePanel>

          {blockingField !== undefined && (
            <EvidencePanel title="보류 원인">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {labelOfField(blockingField.field_name)}
                </span>
                <GradeBadge grade={effectiveGradeOf(blockingField, {})} size="sm" />
              </div>
              {verdict.action_hint !== null && (
                <span
                  style={{ fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: 'keep-all' }}
                >
                  {verdict.action_hint}
                </span>
              )}
            </EvidencePanel>
          )}
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
          {blockingField !== undefined && (
            <Link
              to={`/shipments/${shipment.shipment_id}/draft?focus=${blockingField.field_name}`}
              className="btn btn-primary"
              style={{ gap: 5, padding: '8px 16px', fontSize: 13, fontWeight: 600 }}
            >
              {labelOfField(blockingField.field_name)} 고치러 가기
              <ArrowRight size={13} aria-hidden="true" />
            </Link>
          )}
          <Link
            to={`/shipments/${shipment.shipment_id}/verdicts`}
            className="btn btn-secondary"
            style={{ padding: '8px 14px', fontSize: 13 }}
          >
            보류된 판정 보기
          </Link>
          <div style={{ flex: 1, minWidth: 'var(--space-2)' }} />
          <span style={{ fontSize: 12, color: 'var(--text-muted)', wordBreak: 'keep-all' }}>
            현실측 근거가 없는 항목이라 타임라인이 아니라 검증 결과로 이동합니다
          </span>
        </div>
      </div>
    </article>
  );
}

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import type { ConfidenceGrade } from '../../types/domain';
import { CONFIDENCE } from '../../constants/domain';

/** 등급별 헤더 색 — FieldRow의 뱃지와 같은 규칙 */
const GRADE_COLOR_VAR: Record<ConfidenceGrade, string> = {
  CONFIRMED: '--status-verified',
  ADVISORY: '--severity-warning',
  REQUIRED: '--severity-critical',
  NOT_FOUND: '--text-muted',
};

interface FieldGroupProps {
  grade: ConfidenceGrade;
  count: number;
  /** 처음부터 펼쳐둘지. 필수 확인만 true입니다 */
  defaultOpen: boolean;
  children: ReactNode;
}

/**
 * 신뢰도 등급별 필드 묶음.
 *
 * 26개를 한 줄씩 평면으로 나열하면 지금 처리해야 할 2건이 확정 15건에 묻힙니다.
 * 그래서 등급별로 묶고, 검증을 막고 있는 "필수 확인"만 펼친 채로 시작합니다.
 * 나머지는 건수와 뜻만 보여주고 접어둡니다 — 뜻 문구(hint)는 CONFIDENCE 상수에
 * 이미 있는 것을 그대로 씁니다.
 */
export function FieldGroup({ grade, count, defaultOpen, children }: FieldGroupProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const meta = CONFIDENCE[grade];
  const colorVar = GRADE_COLOR_VAR[grade];
  const Chevron = isOpen ? ChevronDown : ChevronRight;

  // 건수가 0인 등급은 헤더도 만들지 않습니다 — "확인 권고 0건"은 정보가 아니라 잡음
  if (count === 0) return null;

  return (
    <section style={{ display: 'flex', flexDirection: 'column' }}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          width: '100%',
          padding: '13px 18px',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-card)',
          backgroundColor: 'var(--bg)',
          textAlign: 'left',
          flexWrap: 'wrap',
        }}
      >
        <Chevron size={15} color="var(--text-muted)" aria-hidden="true" />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: `var(${colorVar})` }}>
          {meta.label} {count}건
        </span>
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)', wordBreak: 'keep-all' }}>
          {meta.hint}
        </span>
      </button>

      {isOpen && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-2)',
            marginTop: 'var(--space-2)',
          }}
        >
          {children}
        </div>
      )}
    </section>
  );
}

/** 필드 하나를 감싸는 카드 — 왼쪽에 등급색 띠를 둡니다 */
export function FieldCard({ grade, children }: { grade: ConfidenceGrade; children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        backgroundColor: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      <span
        style={{ flex: '0 0 5px', backgroundColor: `var(${GRADE_COLOR_VAR[grade]})` }}
        aria-hidden="true"
      />
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {children}
      </div>
    </div>
  );
}

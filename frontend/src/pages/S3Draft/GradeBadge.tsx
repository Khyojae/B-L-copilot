import { AlertCircle, CheckCircle2, HelpCircle, MinusCircle } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ConfidenceGrade } from '../../types/domain';
import { CONFIDENCE } from '../../constants/domain';

/**
 * 등급 뱃지 색.
 *
 * 확정은 상태색(검증 완료)과 같은 초록, 확인 권고·필수 확인은 심각도 색을
 * 그대로 씁니다. 출처 없음은 잘못이 아니라 "아직 못 찾았다"는 뜻이라 경고색을
 * 주지 않고 중립 회색입니다 — CONFIDENCE의 bgVar 정책과 같은 이유입니다.
 */
export const GRADE_COLOR_VAR: Record<ConfidenceGrade, string> = {
  CONFIRMED: '--status-verified',
  ADVISORY: '--severity-warning',
  REQUIRED: '--severity-critical',
  NOT_FOUND: '--text-muted',
};

const GRADE_ICON: Record<ConfidenceGrade, LucideIcon> = {
  CONFIRMED: CheckCircle2,
  ADVISORY: HelpCircle,
  REQUIRED: AlertCircle,
  NOT_FOUND: MinusCircle,
};

/**
 * 신뢰도 등급 뱃지 — 화면에서는 숫자(0.64, 64%) 대신 이 등급만 씁니다.
 *
 * 소수점·백분율을 그대로 보여주면 "0.64가 좋은 건가 나쁜 건가"를 사용자가
 * 스스로 판정해야 합니다. 그 경계는 CONFIDENCE_THRESHOLD가 이미 정해두고
 * 있으므로 등급으로 옮겨서 보여줍니다. 색만으로 구분하지 않도록 아이콘과
 * 글자를 항상 함께 씁니다 (규약 §6.2).
 */
export function GradeBadge({ grade, size = 'md' }: { grade: ConfidenceGrade; size?: 'sm' | 'md' }) {
  const meta = CONFIDENCE[grade];
  const Icon = GRADE_ICON[grade];
  const isSmall = size === 'sm';

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        flexShrink: 0,
        padding: isSmall ? '2px 7px' : '3px 9px',
        borderRadius: 999,
        fontSize: isSmall ? 11 : 12,
        fontWeight: 600,
        whiteSpace: 'nowrap',
        color: `var(${GRADE_COLOR_VAR[grade]})`,
        border: `1px solid var(${GRADE_COLOR_VAR[grade]})`,
      }}
    >
      <Icon size={isSmall ? 11 : 13} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

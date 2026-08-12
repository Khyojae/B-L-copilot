import { AlertOctagon, AlertTriangle, Info } from 'lucide-react';
import type { Severity } from '../types/domain';
import { SEVERITY } from '../constants/domain';

/** SEVERITY.icon 문자열(예: 'alert-octagon')을 실제 아이콘 컴포넌트로 연결 */
const ICON_BY_NAME = {
  'alert-octagon': AlertOctagon,
  'alert-triangle': AlertTriangle,
  info: Info,
} as const;

interface SeverityBadgeProps {
  severity: Severity;
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const meta = SEVERITY[severity];
  const Icon = ICON_BY_NAME[meta.icon as keyof typeof ICON_BY_NAME];

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 13,
        fontWeight: 600,
        color: `var(${meta.colorVar})`,
        backgroundColor: `var(${meta.bgVar})`,
      }}
    >
      <Icon size={14} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

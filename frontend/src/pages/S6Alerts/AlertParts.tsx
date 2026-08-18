import type { ReactNode } from 'react';
import type { RealityEvent } from '../../types/domain';
import { InfoTip } from '../../components/InfoTip';

/**
 * 경보·판정 보류 카드가 같이 쓰는 조각들.
 *
 * 근거를 좌우 두 칸으로 보여주는 틀과, 룰 코드·문서 ID·이벤트 코드를 접어두는
 * ⓘ 툴팁입니다. 화면에는 사람이 읽을 값만 남기고, 식별자는 툴팁으로 넘깁니다.
 */

/** 근거 두 칸 배치. 좁은 화면에서는 자동으로 위아래로 쌓입니다 */
export function EvidenceColumns({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: 'var(--space-3)',
        padding: '16px 20px',
        borderTop: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
      }}
    >
      {children}
    </div>
  );
}

export function EvidencePanel({
  title,
  tip,
  children,
}: {
  title: string;
  /** 식별자처럼 화면에 안 보여도 되는 정보 — ⓘ에 접어둡니다 */
  tip?: string;
  children: ReactNode;
}) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 7, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            fontSize: 11.5,
            fontWeight: 700,
            letterSpacing: '0.02em',
            color: 'var(--text-secondary)',
          }}
        >
          {title}
        </span>
        {tip !== undefined && tip !== '' && <InfoTip text={tip} />}
      </div>
      {children}
    </section>
  );
}


/** RealityEvent.precision을 지킴 — DATE면 시각을 표시하지 않음 (§5.6) */
export function formatEventTime(event: RealityEvent): string {
  const date = new Date(event.occurred_at);
  return event.precision === 'DATE'
    ? date.toLocaleDateString('ko-KR')
    : date.toLocaleString('ko-KR');
}

// InfoTip은 S6·S8이 함께 쓰므로 src/components로 옮겼습니다.
// 이 폴더 안에서 쓰던 이름을 그대로 유지하기 위해 재수출합니다.
export { InfoTip };

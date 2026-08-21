import type { ReactNode } from 'react';
import type { Shipment } from '../types/domain';
import { StatusBadge } from './StatusBadge';

interface ShipmentHeaderProps {
  shipment: Shipment;
  /**
   * 카드 모양(테두리·그림자·연한 배경)으로 감쌀지.
   *
   * S5·S7처럼 화면 맨 위에 독립된 정보 상자로 놓을 때 켜고, S3처럼 제목 옆에
   * 붙여 쓸 때는 끕니다.
   */
  boxed?: boolean;
  /** 식별 줄 아래에 덧붙일 내용 — 화면마다 필요한 값이 달라서 밖에서 넘깁니다 */
  children?: ReactNode;
}

/**
 * "지금 어느 선적을 보고 있는가"를 밝히는 공통 헤더.
 *
 *   B/L 번호 · 상태 뱃지 · L/C 번호 · 선적 ID
 *
 * S3·S5·S7이 각자 같은 줄을 따로 그리고 있었습니다. 글자 크기·색·순서가 전부
 * 같은데 코드만 세 벌이라, 한 곳을 고치면 나머지 둘이 조용히 어긋납니다
 * (실제로 S5는 상태 뱃지가 오른쪽 끝에, S7은 "Cargo Control No."가 영문으로
 * 남아 있었습니다). 이 줄만 여기로 모읍니다.
 *
 * 화면마다 다른 뒷줄(화물관리번호·유효기일·조회 시각 등)은 children으로 받습니다 —
 * 억지로 하나의 규격에 밀어 넣으면 화면 성격에 안 맞는 값까지 따라옵니다.
 */
export function ShipmentHeader({ shipment, boxed = false, children }: ShipmentHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minWidth: 0,
        textAlign: 'left',
        ...(boxed
          ? {
              padding: 'var(--space-3)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-card)',
              boxShadow: 'var(--shadow-card)',
              backgroundColor: 'var(--bg-card)',
            }
          : null),
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          flexWrap: 'wrap',
        }}
      >
        {shipment.bl_no !== null ? (
          <strong style={{ fontSize: 18, letterSpacing: '-0.2px' }}>{shipment.bl_no}</strong>
        ) : (
          // B/L 번호는 발행 후에 생기는 값이라 초안 단계엔 없는 게 정상입니다.
          // "-"로 두면 오류처럼 보여서 이유를 문구로 밝힙니다.
          <span style={{ fontSize: 16, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            B/L 번호 미발급
          </span>
        )}
        <StatusBadge status={shipment.status} />
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
          L/C {shipment.lc_no ?? '-'}
        </span>
        <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{shipment.shipment_id}</span>
      </div>

      {children}
    </div>
  );
}

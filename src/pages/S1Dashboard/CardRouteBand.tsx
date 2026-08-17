import { Anchor, MapPin, Ship } from 'lucide-react';
import type { FieldValue } from '../../types/domain';
import { NO_SOURCE_LABEL, normalizedOf, valueOf } from './cardFields';

interface CardRouteBandProps {
  fields: FieldValue[];
  /** 본선적재일 — 있으면 출발지 밑에 "07-14 적재"로 붙습니다 */
  loadedOnBoard: string | null;
}

/**
 * 카드 안 항로 띠 — 출발항 ──배── 도착항.
 *
 * 값은 전부 fields에서 옵니다. 아직 안 채워진 값(부킹 전 초안 등)은
 * 지어내지 않고 "출처 없음"으로 두고, 그때는 가운데 선도 흐리게 해서
 * "아직 항로가 안 정해졌다"는 게 한눈에 보이게 했습니다.
 */
export function CardRouteBand({ fields, loadedOnBoard }: CardRouteBandProps) {
  const vessel = valueOf(fields, 'vessel_voyage');

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: '11px 18px',
        borderTop: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
      }}
    >
      <PortLabel
        code={normalizedOf(fields, 'port_of_loading')}
        name={valueOf(fields, 'port_of_loading')}
        note={loadedOnBoard !== null ? `${loadedOnBoard} 적재` : null}
      />

      <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
        <Anchor size={13} color="var(--brand-primary)" aria-hidden="true" />
        <Leg active={vessel !== null} />
        {vessel !== null ? (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--brand-primary)',
              whiteSpace: 'nowrap',
            }}
          >
            <Ship size={13} aria-hidden="true" />
            {vessel}
          </span>
        ) : (
          // 선박이 안 정해졌으면 배 아이콘을 띄우지 않습니다 — 아이콘만 있고
          // 이름이 없으면 "배정됐는데 이름을 못 읽은 것"처럼 보이기 때문입니다
          <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            선박 {NO_SOURCE_LABEL}
          </span>
        )}
        <Leg active={vessel !== null} />
        <MapPin size={13} color="var(--brand-primary)" aria-hidden="true" />
      </div>

      <PortLabel
        code={normalizedOf(fields, 'port_of_discharge')}
        name={valueOf(fields, 'port_of_discharge')}
        note={null}
        alignRight
      />
    </div>
  );
}

/** 항로 선 한 토막. 선박이 정해지기 전에는 흐리게 */
function Leg({ active }: { active: boolean }) {
  return (
    <span
      style={{
        flex: 1,
        minWidth: 8,
        height: active ? 2 : 1,
        backgroundColor: active ? 'var(--brand-primary-light)' : 'var(--border-default)',
      }}
    />
  );
}

function PortLabel({
  code,
  name,
  note,
  alignRight = false,
}: {
  code: string | null;
  name: string | null;
  note: string | null;
  alignRight?: boolean;
}) {
  // 코드(KRPUS)가 없으면 원문 표기(BUSAN)라도 크게 보여주고, 둘 다 없으면 출처 없음
  const primary = code ?? name;
  // 코드와 원문이 둘 다 있을 때만 아래에 원문을 덧붙입니다 (같은 값 두 번 표시 방지)
  const secondaryParts = [code !== null && name !== null ? name : null, note].filter(
    (part): part is string => part !== null,
  );

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        flexShrink: 0,
        textAlign: alignRight ? 'right' : 'left',
      }}
    >
      <span
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: primary !== null ? 'var(--brand-primary)' : 'var(--text-muted)',
        }}
      >
        {primary ?? NO_SOURCE_LABEL}
      </span>
      {secondaryParts.length > 0 && (
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {secondaryParts.join(' · ')}
        </span>
      )}
    </div>
  );
}

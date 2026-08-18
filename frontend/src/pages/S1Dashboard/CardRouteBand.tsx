import { Anchor, MapPin, Ship } from 'lucide-react';
import type { DefectPrediction, FieldValue, Severity, Verdict } from '../../types/domain';
import { SEVERITY } from '../../constants/domain';
import { worstSeverity } from '../../shared/shipmentStats';
import { NO_SOURCE_LABEL, normalizedOf, valueOf } from './cardFields';

interface CardRouteBandProps {
  fields: FieldValue[];
  /** 본선적재일 — 있으면 출발지 밑에 "07-14 적재"로 붙습니다 */
  loadedOnBoard: string | null;
  /** 검증 전이면 null — 그때는 막대를 그리지 않고 "검증 전"으로 둡니다 */
  prediction: DefectPrediction | null;
  /** 막대 색을 정하는 데 씁니다 (아래 barSeverity 주석 참고) */
  verdicts: Verdict[];
}

/**
 * 카드 요약 띠 — 왼쪽은 항로, 오른쪽은 하자 확률.
 *
 * 원래 항로만 있었는데 카드 폭(838px) 전체로 늘어나 선만 길게 뻗어 있었습니다.
 * 항로에 필요한 폭은 실제로 그리 넓지 않아서, 항로는 자기 크기만 쓰게 두고
 * 남는 자리를 이 카드에서 가장 중요한 값인 하자 확률이 채우도록 합쳤습니다.
 */
export function CardRouteBand({ fields, loadedOnBoard, prediction, verdicts }: CardRouteBandProps) {
  const vessel = valueOf(fields, 'vessel_voyage');

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-4)',
        padding: '12px 18px',
        borderTop: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
        flexWrap: 'wrap',
      }}
    >
      {/* 항로 — flex:1로 늘리지 않고, 최대 폭만 정해 필요한 만큼만 씁니다 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          flex: '1 1 380px',
          maxWidth: 520,
          minWidth: 0,
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

      <DefectProbability prediction={prediction} severity={worstSeverity(verdicts)} />
    </div>
  );
}

/** 이 카드에서 가장 크게 보여주는 값 — 숫자 + 색 막대 */
function DefectProbability({
  prediction,
  severity,
}: {
  prediction: DefectPrediction | null;
  severity: Severity | null;
}) {
  const colorVar = severity === null ? '--text-muted' : SEVERITY[severity].colorVar;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        flex: '0 0 auto',
        minWidth: 150,
        marginLeft: 'auto',
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.06em',
          color: 'var(--text-muted)',
        }}
      >
        하자 확률
      </span>

      {prediction === null ? (
        // 검증 전에는 0%로 채우지 않습니다 — 0%는 "안전하다"는 근거 없는
        // 주장이 됩니다 (규약 §2.4). 막대도 그리지 않습니다.
        <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-muted)' }}>검증 전</span>
      ) : (
        <>
          <span
            style={{
              fontSize: 28,
              fontWeight: 700,
              lineHeight: 1,
              letterSpacing: '-0.5px',
              color: `var(${colorVar})`,
            }}
          >
            {Math.round(prediction.probability * 100)}%
          </span>
          <span
            style={{
              display: 'block',
              width: '100%',
              height: 7,
              borderRadius: 999,
              overflow: 'hidden',
              backgroundColor: 'var(--border-default)',
            }}
          >
            <span
              style={{
                display: 'block',
                height: '100%',
                width: `${Math.round(prediction.probability * 100)}%`,
                borderRadius: 999,
                backgroundColor: `var(${colorVar})`,
              }}
            />
          </span>
          {prediction.deferred_count > 0 && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              판정 보류 {prediction.deferred_count}건 제외
            </span>
          )}
        </>
      )}
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
        backgroundColor: active ? 'var(--brand-primary)' : 'var(--border-default)',
        opacity: active ? 0.35 : 1,
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
          fontSize: 15,
          fontWeight: 700,
          letterSpacing: '-0.2px',
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

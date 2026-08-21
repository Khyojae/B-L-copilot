import { AlertCircle } from 'lucide-react';
import type { DefectPrediction, FieldValue, Shipment } from '../../types/domain';
import {
  NO_SOURCE_LABEL,
  countSourceDocuments,
  daysUntil,
  isBlocking,
  joinValues,
  normalizedOf,
  valueOf,
} from './cardFields';

interface CardFieldGridProps {
  shipment: Shipment;
  fields: FieldValue[];
  /** 검증 전이면 null — 그때는 확률 막대를 그리지 않습니다 */
  prediction: DefectPrediction | null;
  /** D-day 계산 기준 시각. 렌더 중에 new Date()를 부르지 않도록 부모가 넘겨줍니다 */
  now: Date;
}

/** 격자 한 칸의 내용 */
interface Cell {
  label: string;
  /** null이면 "출처 없음"을 회색으로 표시 */
  value: string | null;
  /** 값 뒤에 덧붙는 강조 문구 (예: D-20) */
  suffix?: { text: string; colorVar: string };
  /** 이 칸이 지금 검증을 막고 있는 필드인지 — 경고 아이콘을 붙입니다 */
  blocking?: boolean;
}

/**
 * 카드 안 필드 격자 — 선적을 식별하고 판단하는 데 필요한 값만 골라 4열로 보여줍니다.
 *
 * 26개 필드를 다 보여주는 건 S3 초안 편집기의 일이고, 여기서는 목록에서
 * 훑어볼 값만 추립니다. 값이 없는 칸은 비워두지 않고 "출처 없음"이라고
 * 적습니다 — 빈칸은 "값이 없다"인지 "화면이 덜 그려졌다"인지 구분이 안 되니까요.
 */
export function CardFieldGrid({ shipment, fields, prediction, now }: CardFieldGridProps) {
  const cells: Cell[] = [
    { label: 'L/C 번호', value: shipment.lc_no },
    { label: '화물관리번호', value: shipment.cargo_control_no },
    {
      label: '컨테이너',
      // 정규화값(MSKU1234565)을 먼저 씁니다 — 원문은 공백이 섞여 있을 수 있어서
      value: normalizedOf(fields, 'container_no') ?? valueOf(fields, 'container_no'),
      blocking: isBlocking(fields, 'container_no'),
    },
    {
      label: '화물',
      value: joinValues(valueOf(fields, 'no_of_packages'), valueOf(fields, 'gross_weight')),
    },
    {
      label: '조건',
      value: joinValues(valueOf(fields, 'incoterms'), valueOf(fields, 'freight_terms')),
    },
    lcExpiryCell(shipment, now),
    { label: '근거 서류', value: documentCountLabel(fields) },
    defectProbabilityCell(prediction),
  ];

  return (
    <div
      style={{
        display: 'grid',
        // 4열 고정이 아니라 최소 폭 기준으로 자동 줄바꿈 — 좁은 화면에서 2열,
        // 더 좁으면 1열로 알아서 접힙니다 (미디어쿼리 없이 처리)
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: 'var(--space-3)',
        padding: '14px 18px',
        borderTop: '1px solid var(--border-default)',
      }}
    >
      {cells.map((cell) => (
        <GridCell key={cell.label} cell={cell} />
      ))}
    </div>
  );
}

/** L/C 유효기일 + 남은 일수. 이미 지났으면 "기일 경과"로 바꿔 씁니다 */
function lcExpiryCell(shipment: Shipment, now: Date): Cell {
  if (shipment.lc_expiry_date === null) {
    return { label: 'L/C 유효기일', value: null };
  }

  const remaining = daysUntil(shipment.lc_expiry_date, now);

  return {
    label: 'L/C 유효기일',
    value: shipment.lc_expiry_date,
    suffix:
      remaining < 0
        ? { text: '기일 경과', colorVar: '--severity-critical' }
        : {
            text: `D-${remaining}`,
            // 7일 이하로 남으면 위반 색, 그 외에는 주의 색. 색만으로 구분하지
            // 않도록 "D-3" 같은 숫자를 항상 같이 보여줍니다 (규약 §6.2)
            colorVar: remaining <= 7 ? '--severity-critical' : '--severity-warning',
          },
  };
}

function documentCountLabel(fields: FieldValue[]): string | null {
  const count = countSourceDocuments(fields);
  return count === 0 ? null : `${count}건`;
}

/** 하자 확률 — 검증 전이면 막대 없이 "검증 전"으로 둡니다 (0%로 채우지 않음) */
function defectProbabilityCell(prediction: DefectPrediction | null): Cell {
  if (prediction === null) {
    return { label: '하자 확률', value: '검증 전' };
  }
  return {
    label: '하자 확률',
    value: `${Math.round(prediction.probability * 100)}%`,
  };
}

function GridCell({ cell }: { cell: Cell }) {
  const isMissing = cell.value === null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.06em',
          color: 'var(--text-muted)',
        }}
      >
        {cell.label}
      </span>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 13,
          lineHeight: 1.3,
          color: isMissing ? 'var(--text-muted)' : 'var(--text-primary)',
          wordBreak: 'break-all',
        }}
      >
        {cell.blocking === true && (
          <AlertCircle size={13} color="var(--severity-critical)" aria-hidden="true" />
        )}
        {cell.value ?? NO_SOURCE_LABEL}
        {cell.suffix !== undefined && (
          <strong style={{ color: `var(${cell.suffix.colorVar})` }}>{cell.suffix.text}</strong>
        )}
      </span>
    </div>
  );
}

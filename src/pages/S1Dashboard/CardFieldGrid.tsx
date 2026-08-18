import type { ConfidenceGrade, FieldValue, Shipment } from '../../types/domain';
import { GradeBadge } from '../S3Draft/GradeBadge';
import {
  NO_SOURCE_LABEL,
  countSourceDocuments,
  daysUntil,
  gradeOf,
  joinValues,
  normalizedOf,
  valueOf,
} from './cardFields';

interface CardFieldGridProps {
  shipment: Shipment;
  fields: FieldValue[];
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
  /**
   * 이 칸의 신뢰도 등급. 확정이 아니면 등급 뱃지를 붙입니다.
   *
   * 전에는 "검증을 막는가"만 보고 빨간 느낌표 아이콘 하나를 달았는데,
   * 아이콘만으로는 무슨 뜻인지 알 수 없어 색·아이콘에 텍스트를 병기하라는
   * 규약 §6.2에 어긋났습니다. S3와 같은 GradeBadge를 씁니다.
   */
  grade?: ConfidenceGrade | null;
}

/**
 * 카드 안 필드 격자 — 선적을 식별하고 판단하는 데 필요한 값만 골라 보여줍니다.
 *
 * 26개 필드를 다 보여주는 건 S3 초안 편집기의 일이고, 여기서는 목록에서
 * 훑어볼 값만 추립니다. 값이 없는 칸은 비워두지 않고 "출처 없음"이라고
 * 적습니다 — 빈칸은 "값이 없다"인지 "화면이 덜 그려졌다"인지 구분이 안 되니까요.
 *
 * 하자 확률은 여기 있다가 요약 띠(CardRouteBand)로 옮겼습니다. 다른 일곱 칸과
 * 같은 크기로 놓으니 카드에서 제일 중요한 값이 묻혔습니다.
 */
export function CardFieldGrid({ shipment, fields, now }: CardFieldGridProps) {
  const cells: Cell[] = [
    { label: 'L/C 번호', value: shipment.lc_no },
    { label: '화물관리번호', value: shipment.cargo_control_no },
    {
      label: '컨테이너',
      // 정규화값(MSKU1234565)을 먼저 씁니다 — 원문은 공백이 섞여 있을 수 있어서
      value: normalizedOf(fields, 'container_no') ?? valueOf(fields, 'container_no'),
      grade: gradeOf(fields, 'container_no'),
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
  ];

  return (
    <div
      style={{
        display: 'grid',
        // 4열 고정이 아니라 최소 폭 기준으로 자동 줄바꿈 — 좁은 화면에서 2열,
        // 더 좁으면 1열로 알아서 접힙니다 (미디어쿼리 없이 처리)
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 'var(--space-3)',
        padding: '16px 18px',
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

function GridCell({ cell }: { cell: Cell }) {
  const isMissing = cell.value === null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
      {/* 라벨은 작고 연하게 — 값보다 눈에 띄면 안 됩니다. 원래 라벨이 600
          굵기고 값이 400이라 위계가 거꾸로였습니다 */}
      <span
        style={{
          fontSize: 11,
          fontWeight: 500,
          letterSpacing: '0.04em',
          color: 'var(--text-muted)',
        }}
      >
        {cell.label}
      </span>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 4,
          fontSize: 14,
          fontWeight: 600,
          lineHeight: 1.35,
          color: isMissing ? 'var(--text-muted)' : 'var(--text-primary)',
          // break-all은 "FREIGHT PREPAID"를 단어 한가운데서 잘랐습니다.
          // keep-all + break-word면 띄어쓰기에서 먼저 줄을 바꾸고, 그래도 안
          // 들어가는 긴 식별자(LC26081200123)만 잘립니다.
          wordBreak: 'keep-all',
          overflowWrap: 'break-word',
        }}
      >
        {cell.value ?? NO_SOURCE_LABEL}
        {/* 확정이면 뱃지를 안 답니다 — 정상인 값에까지 표식을 붙이면 무엇이
            문제인지 오히려 안 보입니다 */}
        {cell.grade !== undefined && cell.grade !== null && cell.grade !== 'CONFIRMED' && (
          <GradeBadge grade={cell.grade} size="sm" />
        )}
        {cell.suffix !== undefined && (
          <strong style={{ color: `var(${cell.suffix.colorVar})` }}>{cell.suffix.text}</strong>
        )}
      </span>
    </div>
  );
}

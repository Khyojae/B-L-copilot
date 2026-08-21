import type { CSSProperties } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { SeverityBadge } from '../../components/SeverityBadge';
import { REISSUE_PATH_LABEL, labelOfField } from '../../constants/domain';
import { InfoTip } from '../../components/InfoTip';
import type { ResolvedConflicts } from '../../shared/shipmentStats';
import type { ConstraintType, ImpactItem, ImpactResult } from '../../types/domain';

/** 이번 기간 렌더 대상 제약 3종 (§10.1). 타입 자체는 6종 유지하되 나머지는 숨김 */
const RENDERED_CONSTRAINT_TYPES: ConstraintType[] = ['EQ', 'SUM', 'REF'];

// mock에서 "정정 영향"이 연결된 필드. 축소 구현이라 실제 제약 그래프 탐색은
// 없고, 이 필드가 수정됐을 때만 mockImpactResult를 보여줍니다.
const WATCHED_FIELD = 'port_of_loading';

interface ImpactPanelProps {
  /**
   * 이 선적의 영향분석 결과. 선적 상태에 따라 정정의 무게가 달라서
   * (초안이면 다시 쓰면 되지만, 제출됐으면 조건 변경·재발행까지 필요)
   * S3Draft가 URL의 :id로 찾아 넘겨줍니다.
   */
  impact: ImpactResult;
  /**
   * S3Draft가 들고 있는 "필드별 수정값" 상태 — 이 패널이 구독하는 유일한 입력.
   * 편집기 내부 상태(포커스된 필드, 인라인 입력창 열림 여부 등)에는 직접
   * 접근하지 않습니다. (화면전이_정의.md §S3↔S8: "ImpactPanel은 필드 변경
   * 이벤트만 구독한다. 편집기 내부 상태에 접근하지 않는다")
   */
  editedValues: Record<string, string | null>;
  /**
   * 값 충돌을 해소한 필드.
   *
   * ⚠ editedValues만 보면 안 됩니다. 후보 선택은 "값 수정"이 아니라 "충돌
   *   해소"로 따로 다루기로 하면서(M-2) resolvedConflicts로 빠졌는데, 이
   *   패널이 editedValues만 구독하고 있어서 후보를 골라도 영향분석이 열리지
   *   않았습니다. 사용자 입장에서는 값을 정했는데 패널이 반응을 안 한 셈입니다.
   */
  resolvedConflicts: ResolvedConflicts;
}

// 뷰어(480px 고정)+필드폼(가변)+패널을 한 flex 줄에 같이 넣으면 셋이 폭을
// 나눠 가지면서 필드폼이 눌려 줄바꿈이 심해집니다 (뷰어+패널 고정폭만 780px+
// 여백이라 1280px 콘텐츠 폭에서 필드폼에 남는 자리가 너무 좁아짐). 그래서
// 패널은 flex 줄에서 완전히 빼고, 화면 오른쪽에 떠 있는 고정(fixed) 패널로
// 둡니다 — 뷰어·필드폼은 패널이 열려도 원래 폭을 그대로 씁니다.
//
// top과 bottom을 둘 다 고정하면 내용이 짧을 때(아직 필드를 안 고친 빈
// 상태)도 카드가 화면 세로 전체로 늘어나서 텍스트 밑에 텅 빈 카드 영역이
// 남습니다. 그래서 bottom 대신 maxHeight를 써서 내용만큼만 커지게 하고,
// 내용이 길어지면 그때만 스크롤(overflowY)이 생기게 했습니다.
const panelBaseStyle: CSSProperties = {
  position: 'fixed',
  top: 'var(--space-5)',
  right: 'var(--space-3)',
  width: 320,
  maxHeight: 'calc(100vh - var(--space-5) - var(--space-4))',
  overflowY: 'auto',
  zIndex: 20,
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  padding: 'var(--space-3)',
  border: '1px solid var(--border-default)',
  borderRadius: 'var(--radius-card)',
  boxShadow: 'var(--shadow-card)',
  backgroundColor: 'var(--bg-card)',
  textAlign: 'left',
};

function ImpactItemCard({ item }: { item: ImpactItem }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: 'var(--space-2)',
        border: '1px solid var(--border-default)',
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: 'var(--text-muted)',
            border: '1px solid var(--border-default)',
            borderRadius: 4,
            padding: '1px 6px',
          }}
        >
          {item.constraint_type}
        </span>
        <SeverityBadge severity={item.urgency} />
      </div>

      <p style={{ margin: 0 }}>{item.action}</p>

      {/* 화면에는 사람이 읽을 값만 — 문서 ID·룰 코드는 ⓘ로 접습니다 (S6과 같은 방식) */}
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          flexWrap: 'wrap',
          fontSize: 12,
          color: 'var(--text-muted)',
        }}
      >
        {labelOfField(item.affected_field)} · 담당 {item.party}
        <InfoTip
          text={[item.affected_doc, item.rule_id, `제약 ${item.constraint_type}`]
            .filter((part): part is string => part !== null)
            .join(' · ')}
        />
      </span>
    </div>
  );
}

/**
 * S8 정정 영향분석 패널 — 축소 구현 (깊이 2, 제약 3종 EQ·SUM·REF만).
 *
 * 별도 화면이 아니라 S3 안의 사이드 패널입니다. 화면전이_정의.md §1에 따라
 * `?impact=1` URL 상태로 열림/닫힘을 관리하고(별도 라우트 없음), 이 컴포넌트가
 * 그 쿼리 파라미터를 직접 읽습니다 — 부모(S3Draft)가 열림 상태를 따로
 * 내려줄 필요가 없습니다.
 */
export function ImpactPanel({ impact, editedValues, resolvedConflicts }: ImpactPanelProps) {
  const [searchParams] = useSearchParams();
  const isOpen = searchParams.get('impact') === '1';

  if (!isOpen) return null;

  // 직접 입력이든 후보 선택이든 "이 필드 값이 정해졌다"는 점은 같습니다
  const chosenValue = resolvedConflicts[WATCHED_FIELD];
  const changedValue =
    WATCHED_FIELD in editedValues ? editedValues[WATCHED_FIELD] : chosenValue ?? null;
  const hasWatchedChange = WATCHED_FIELD in editedValues || chosenValue !== undefined;

  if (!hasWatchedChange) {
    return (
      <div style={panelBaseStyle}>
        <h2 style={{ margin: 0, fontSize: 16 }}>정정 영향분석</h2>
        <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
          아직 영향분석과 연결된 필드를 고치지 않았습니다. {labelOfField(WATCHED_FIELD)} 필드 값을
          정하면 여기에 영향 범위가 표시됩니다.
        </p>
      </div>
    );
  }

  const renderedItems = impact.items.filter((item) =>
    RENDERED_CONSTRAINT_TYPES.includes(item.constraint_type),
  );
  const directItems = renderedItems.filter((item) => !item.indirect);
  const indirectCount = impact.indirect_count;

  return (
    <div style={panelBaseStyle}>
      <h2 style={{ margin: 0, fontSize: 16 }}>정정 영향분석</h2>
      <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
        {labelOfField(WATCHED_FIELD)} 값을 "{changedValue ?? '(빈 값)'}"으로 정하면 아래 항목을
        다시 확인해야 합니다.
      </p>

      {directItems.map((item) => (
        <ImpactItemCard key={`${item.affected_doc}-${item.affected_field}-${item.constraint_type}`} item={item} />
      ))}

      {indirectCount > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: 'var(--space-2)',
            borderRadius: 6,
            // 신뢰도 등급과 무관한 안내인데 --confidence-not-found-bg를 빌려
            // 쓰고 있었습니다. 신뢰도 토큰 값이 바뀌면 이 박스도 같이 흔들려서,
            // 중립 배경 + 테두리로 바꿉니다 (패널 배경이 --bg-card라 대비가 남)
            backgroundColor: 'var(--bg)',
            border: '1px solid var(--border-default)',
          }}
        >
          <AlertTriangle size={14} color="var(--text-muted)" aria-hidden="true" />
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            간접 영향 {indirectCount}건 더 있음 (탐색 깊이 2 초과 — 건수만 표시)
          </span>
        </div>
      )}

      <div
        style={{
          fontSize: 12,
          color: 'var(--text-muted)',
          borderTop: '1px solid var(--border-default)',
          paddingTop: 8,
        }}
      >
        재발행 경로: {REISSUE_PATH_LABEL[impact.reissue_path]}
        {impact.requires_amendment && <span> · 조건 변경(amendment) 필요</span>}
      </div>
    </div>
  );
}

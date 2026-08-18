import { useState } from 'react';
import { FileQuestion } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';
import { FieldForm } from './FieldForm';
import { DocumentViewer, DISPLAY_SIZE } from './DocumentViewer';
import { VerifyBar } from './VerifyBar';
import { ImpactPanel } from './ImpactPanel';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import { findShipmentData } from '../../mocks/shipmentData';
import { StatusBadge } from '../../components/StatusBadge';
import { resolveConflicts, type ResolvedConflicts } from '../../shared/shipmentStats';
import type { FieldValue, Suggestion } from '../../types/domain';

export function S3Draft() {
  // S4·S7과 같은 방식 — URL(/shipments/:id/draft)의 :id로 이 선적의 묶음을 찾습니다
  const { id } = useParams();
  const data = findShipmentData(id);

  // S8 영향분석 패널의 열림/닫힘은 ImpactPanel 스스로 이 값을 읽어서 결정합니다
  // (화면전이_정의.md §1: "?impact=1" URL 상태). 여기서는 토글 버튼만 둡니다.
  const [searchParams, setSearchParams] = useSearchParams();
  const isImpactOpen = searchParams.get('impact') === '1';

  function toggleImpactPanel() {
    const next = new URLSearchParams(searchParams);
    if (isImpactOpen) {
      next.delete('impact');
    } else {
      next.set('impact', '1');
    }
    setSearchParams(next);
  }

  // 지금 문서 뷰어에서 하이라이트할 필드. FieldRow를 클릭하면 여기로 들어옴
  const [focusedField, setFocusedField] = useState<FieldValue | null>(null);

  // 필드별로 사용자가 고친 값 (필드 이름 → 새 값). FieldRow에서 직접 타이핑해서
  // 고치는 것과 SuggestionCard에서 교정 제안을 승인하는 것, 둘 다 결국 "이 필드
  // 값을 이걸로 바꾼다"는 같은 동작이라서 여기 하나의 상태로 합쳐서 관리합니다.
  const [editedValues, setEditedValues] = useState<Record<string, string | null>>({});

  // 값 충돌 필드에서 사용자가 고른 후보. editedValues와 따로 두는 이유는
  // "직접 새 값을 입력한 것"과 "이미 읽어낸 후보 중 고른 것"이 다른 행동이기
  // 때문입니다 — 후자는 원문의 인식 품질을 바꾸지 않으므로 등급도 그 후보의
  // 신뢰도를 그대로 따릅니다 (M1_M2_팀확정요청.md 참고).
  const [resolvedConflicts, setResolvedConflicts] = useState<ResolvedConflicts>({});

  function handleConflictResolve(fieldName: string, chosenValue: string) {
    setResolvedConflicts((prev) => ({ ...prev, [fieldName]: chosenValue }));
  }

  function handleConflictClear(fieldName: string) {
    // 키를 지워서 원래 충돌 상태(필수 확인)로 되돌립니다. 값을 되돌리는 게
    // 아니라 "아직 안 골랐다"로 되돌리는 것이라 원본 필드가 그대로 살아납니다.
    setResolvedConflicts((prev) => {
      const next = { ...prev };
      delete next[fieldName];
      return next;
    });
  }

  function handleFieldEdit(fieldName: string, value: string | null) {
    setEditedValues((prev) => ({ ...prev, [fieldName]: value }));
  }

  function handleSuggestionAccept(suggestion: Suggestion, applyToAllInScope: boolean) {
    setEditedValues((prev) => {
      // suggestion.field는 항상 바꾼다. applyToAllInScope가 켜져 있으면
      // scope에 있는 다른 필드들도 같은 값으로 같이 바꾼다 (일괄 적용)
      const next = { ...prev, [suggestion.field]: suggestion.to_be };
      if (applyToAllInScope) {
        for (const { field } of suggestion.scope) {
          next[field] = suggestion.to_be;
        }
      }
      return next;
    });
  }

  function handleSuggestionReject(suggestion: Suggestion, reason: string) {
    // 거절은 필드 값을 바꾸지 않습니다 — 지금은 사유만 기록(콘솔)
    console.log('[SuggestionCard] 거절:', suggestion.suggestion_id, { reason });
  }

  // ⚠ 이 자리보다 위에서 return하면 안 됩니다. useState·useSearchParams 같은
  // 훅은 화면을 다시 그릴 때마다 "항상 같은 순서로, 같은 개수만큼" 불려야 하는데,
  // 훅 호출 위에서 먼저 빠져나가면 그 규칙이 깨져서 React가 에러를 냅니다.
  // 그래서 훅을 전부 부른 다음에 "선적 없음" 처리를 합니다.
  if (data === null) {
    return (
      <PageContainer>
        <EmptyState icon={FileQuestion} message={`선적 ${id ?? ''}을(를) 찾을 수 없습니다.`} />
      </PageContainer>
    );
  }

  // 뷰어(480px 고정) + 필드폼 + 영향패널을 한 줄에 다 넣으면 콘텐츠 최대폭
  // (1280px)을 넘어서 필드폼이 심하게 눌려 줄바꿈됩니다. 페이지 폭 자체를
  // 늘리는 방법도 있지만, 그건 이 프로젝트가 화면마다 통일하기로 한 레이아웃
  // 폭 규칙을 이 화면만 깨는 셈이라 피했습니다. 대신 영향 패널을 보는
  // 동안에는 문서 뷰어를 잠깐 숨겨서 필드폼에 자리를 돌려줍니다 — 패널이
  // 화면에 고정(fixed)으로 뜨는 동안 밑에 깔린 내용과 겹치지 않도록, 그
  // 자리만큼(패널 폭 320px + ImpactPanel의 right 여백 16px + 약간의 틈)만큼
  // 본문 오른쪽에 미리 여백을 비워둡니다. 여백을 너무 넉넉하게 주면 패널이
  // 본문과 멀찍이 떨어져 보여서, 딱 붙지도 겹치지도 않을 만큼만 좁게 잡았습니다.
  const contentStyle = {
    paddingRight: isImpactOpen ? 344 : 0,
  };

  // 충돌이 해소된 필드는 고른 후보의 값·신뢰도로 갈아끼운 뒤 아래로 내려보냅니다.
  // 그래야 등급 계산·필수 확인 건수·검증 게이트가 전부 같은 필드를 보고 움직입니다.
  const fields = resolveConflicts(data.fields, resolvedConflicts);

  return (
    <PageContainer>
      <div style={contentStyle}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, textAlign: 'left' }}>
            <h1 style={{ margin: 0, fontSize: 22 }}>초안 편집기</h1>
            {/* 어느 선적을 보고 있는지 — 값은 전부 실제 선적 데이터에서 옵니다 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                flexWrap: 'wrap',
              }}
            >
              {data.shipment.bl_no !== null ? (
                <strong style={{ fontSize: 18, letterSpacing: '-0.2px' }}>
                  {data.shipment.bl_no}
                </strong>
              ) : (
                <span style={{ fontSize: 16, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                  B/L 번호 미발급
                </span>
              )}
              <StatusBadge status={data.shipment.status} />
              <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
                L/C {data.shipment.lc_no ?? '-'}
              </span>
              <span style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
                {data.shipment.shipment_id}
              </span>
            </div>
          </div>
          <button type="button" className="btn-secondary" onClick={toggleImpactPanel}>
            {isImpactOpen ? '영향 패널 닫기' : '영향 확인'}
          </button>
        </div>

        {/* 가로 배치(뷰어+필드폼)는 index.css의 .s3-content-row가 맡습니다 —
            1024px 이하에서는 미디어쿼리로 세로 쌓기로 바뀝니다. 인라인
            style로는 미디어쿼리를 못 써서 이 div만 className을 씁니다. */}
        <div className="s3-content-row">
          {isImpactOpen ? (
            // 뷰어 자리를 완전히 비워두면 "그냥 없어진 것"처럼 보여서, 실제
            // 뷰어 박스(DocumentViewer의 documentAreaStyle)와 같은 톤의 회색
            // 박스를 폭만 좁혀서 그대로 둡니다 — 높이는 뷰어와 맞춰서
            // "여기 뷰어 있었다"는 느낌을 유지합니다.
            <div
              style={{
                flexShrink: 0,
                width: 140,
                height: DISPLAY_SIZE.height,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 'var(--space-2)',
                textAlign: 'center',
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-card)',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
                영향 패널을 보는 동안 문서 미리보기를 숨겼습니다. 패널을 닫으면 다시 보입니다.
              </p>
            </div>
          ) : (
            <DocumentViewer focusedField={focusedField ?? undefined} documents={data.documents} />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <FieldForm
              fields={fields}
              suggestions={data.suggestions}
              verdicts={data.verdicts}
              focusedFieldName={focusedField?.field_name ?? null}
              onFieldFocus={setFocusedField}
              editedValues={editedValues}
              onFieldEdit={handleFieldEdit}
              onSuggestionAccept={handleSuggestionAccept}
              onSuggestionReject={handleSuggestionReject}
              resolvedConflicts={resolvedConflicts}
              onConflictResolve={handleConflictResolve}
              onConflictClear={handleConflictClear}
            />
          </div>
        </div>

        {/* 이 화면의 핵심 동작이라 스크롤과 무관하게 항상 보이도록 하단에
            고정합니다. sticky는 부모에 overflow가 없어야 동작하므로 여기서만
            감싸고, 겹치는 내용이 비쳐 보이지 않게 배경색을 채웁니다 */}
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            zIndex: 10,
            marginTop: 'var(--space-4)',
            paddingBottom: 'var(--space-3)',
            backgroundColor: 'var(--bg)',
          }}
        >
          <VerifyBar
            fields={fields}
            verdicts={data.verdicts}
            prediction={data.prediction}
            editedValues={editedValues}
          />
        </div>
      </div>

      <ImpactPanel impact={data.impact} editedValues={editedValues} />
    </PageContainer>
  );
}

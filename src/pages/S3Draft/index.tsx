import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FieldForm } from './FieldForm';
import { DocumentViewer } from './DocumentViewer';
import { SuggestionCard } from './SuggestionCard';
import { VerifyBar } from './VerifyBar';
import { ImpactPanel } from './ImpactPanel';
import { PageContainer } from '../../components/PageContainer';
import { mockSuggestions } from '../../mocks/shipment.fixture';
import type { FieldValue, Suggestion } from '../../types/domain';

export function S3Draft() {
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

  // 뷰어(480px 고정) + 필드폼 + 영향패널을 한 줄에 다 넣으면 콘텐츠 최대폭
  // (1280px)을 넘어서 필드폼이 심하게 눌려 줄바꿈됩니다. 페이지 폭 자체를
  // 늘리는 방법도 있지만, 그건 이 프로젝트가 화면마다 통일하기로 한 레이아웃
  // 폭 규칙을 이 화면만 깨는 셈이라 피했습니다. 대신 영향 패널을 보는
  // 동안에는 문서 뷰어를 잠깐 숨겨서 필드폼에 자리를 돌려줍니다 — 패널이
  // 화면에 고정(fixed)으로 뜨는 동안 밑에 깔린 내용과 겹치지 않도록, 그
  // 자리만큼(패널 폭 320px + 여백) 본문 오른쪽에 미리 여백을 비워둡니다.
  const contentStyle = {
    paddingRight: isImpactOpen ? 360 : 0,
  };

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
          <h1>초안 편집기</h1>
          <button type="button" className="btn-secondary" onClick={toggleImpactPanel}>
            {isImpactOpen ? '영향 패널 닫기' : '영향 확인'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
          {isImpactOpen ? (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: 'var(--text-muted)',
                width: 120,
                flexShrink: 0,
              }}
            >
              영향 패널을 보는 동안 문서 미리보기를 숨겼습니다. 패널을 닫으면 다시 보입니다.
            </p>
          ) : (
            <DocumentViewer focusedField={focusedField ?? undefined} />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <FieldForm
              focusedFieldName={focusedField?.field_name ?? null}
              onFieldFocus={setFocusedField}
              editedValues={editedValues}
              onFieldEdit={handleFieldEdit}
            />

            <h2 style={{ textAlign: 'left', padding: '0 16px' }}>교정 제안</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '0 16px' }}>
              {mockSuggestions.map((suggestion) => (
                <SuggestionCard
                  key={suggestion.suggestion_id}
                  suggestion={suggestion}
                  onAccept={handleSuggestionAccept}
                  onReject={handleSuggestionReject}
                />
              ))}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 24 }}>
          <VerifyBar editedValues={editedValues} />
        </div>
      </div>

      <ImpactPanel editedValues={editedValues} />
    </PageContainer>
  );
}

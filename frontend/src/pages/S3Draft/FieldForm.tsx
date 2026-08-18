import { useState } from 'react';
import type { ConfidenceGrade, FieldValue, Suggestion, Verdict } from '../../types/domain';
import { FieldRow } from './FieldRow';
import { FieldCard, FieldGroup } from './FieldGroup';
import { CandidateChooser } from './CandidateChooser';
import { SuggestionCard } from './SuggestionCard';
import { displayValueOf, isEditedField } from './fieldEditing';
import {
  effectiveGradeOf,
  type EditedValues,
  type ResolvedConflicts,
} from '../../shared/shipmentStats';
import { CONFIDENCE } from '../../constants/domain';

/** 화면에 보여줄 그룹 순서 — 지금 손봐야 하는 것부터 */
const GROUP_ORDER: ConfidenceGrade[] = ['REQUIRED', 'NOT_FOUND', 'ADVISORY', 'CONFIRMED'];

interface FieldFormProps {
  fields: FieldValue[];
  /** 이 선적의 교정 제안 — 해당 필드 카드 안쪽에 붙여서 보여줍니다 */
  suggestions: Suggestion[];
  /** 판정 — 필수 확인 필드의 수정 가이드(action_hint)를 찾는 데 씁니다 */
  verdicts: Verdict[];
  focusedFieldName?: string | null;
  onFieldFocus?: (field: FieldValue) => void;
  editedValues: EditedValues;
  onFieldEdit: (fieldName: string, value: string | null) => void;
  onSuggestionAccept: (suggestion: Suggestion, applyToAllInScope: boolean) => void;
  onSuggestionReject: (suggestion: Suggestion, reason: string) => void;
  /** 지금 충돌이 해소된 필드들 (필드 이름 → 고른 후보 값) */
  resolvedConflicts: ResolvedConflicts;
  /** 후보를 골랐을 때 — 값 수정이 아니라 충돌 해소로 따로 다룹니다 */
  onConflictResolve: (fieldName: string, chosenValue: string) => void;
}

/**
 * 추출 필드 목록 — 신뢰도 등급별로 묶어서 보여줍니다.
 *
 * 26개를 평면으로 나열하면 지금 처리해야 할 2건이 확정 15건에 묻혀서,
 * 등급별 그룹으로 접었습니다. 검증을 막고 있는 "필수 확인"만 펼친 채 시작합니다.
 *
 * 교정 제안은 별도 목록이 아니라 해당 필드 카드 안에 붙입니다 — "이 값을
 * 이렇게 고치라"는 제안은 그 필드 옆에 있어야 무엇을 고치는지 바로 보입니다.
 */
export function FieldForm({
  fields,
  suggestions,
  verdicts,
  focusedFieldName = null,
  onFieldFocus,
  editedValues,
  onFieldEdit,
  onSuggestionAccept,
  onSuggestionReject,
  resolvedConflicts,
  onConflictResolve,
}: FieldFormProps) {
  // 지금 인라인 입력창이 열려 있는 필드 이름. 한 번에 한 행만 편집 상태가 될 수 있음
  const [editingFieldName, setEditingFieldName] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

  function startEditing(field: FieldValue) {
    setDraft(displayValueOf(field, editedValues) ?? '');
    setEditingFieldName(field.field_name);
  }

  function commitEdit(field: FieldValue) {
    const trimmed = draft.trim();
    onFieldEdit(field.field_name, trimmed === '' ? null : trimmed);
    setEditingFieldName(null);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', padding: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 'var(--space-2)',
          flexWrap: 'wrap',
          textAlign: 'left',
        }}
      >
        <h2 style={{ margin: 0, fontSize: 15 }}>추출 필드</h2>
        {/* 총 건수만 둡니다. 등급별 건수는 아래 그룹 헤더에 이미 다 있고,
            전에 있던 "확인 필요 N" 칩은 그룹명 "확인 권고"와 헷갈리는 데다
            검증을 막지 않는 "출처 없음"까지 섞여 있어서 뺐습니다 */}
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{fields.length}건</span>
      </div>

      {GROUP_ORDER.map((grade) => {
        const groupFields = fields.filter(
          (field) => effectiveGradeOf(field, editedValues) === grade,
        );

        return (
          <FieldGroup
            key={grade}
            grade={grade}
            count={groupFields.length}
            // 검증을 막는 등급(필수 확인)만 펼친 채 시작합니다 — 상수를 따르므로
            // blocksVerify 규칙이 바뀌면 여기도 자동으로 따라갑니다
            defaultOpen={CONFIDENCE[grade].blocksVerify}
          >
            {groupFields.map((field) => (
              <FieldCard key={field.field_name} grade={grade}>
                <FieldRow
                  field={field}
                  displayValue={displayValueOf(field, editedValues)}
                  isEdited={isEditedField(field, editedValues)}
                  isEditing={editingFieldName === field.field_name}
                  draft={draft}
                  onDraftChange={setDraft}
                  onStartEdit={() => startEditing(field)}
                  onCommitEdit={() => commitEdit(field)}
                  onCancelEdit={() => setEditingFieldName(null)}
                  isFocused={field.field_name === focusedFieldName}
                  onClick={onFieldFocus ? () => onFieldFocus(field) : undefined}
                />

                {field.conflict_flag && (
                  <CandidateChooser
                    field={field}
                    onChoose={(value) => onConflictResolve(field.field_name, value)}
                    chosenValue={resolvedConflicts[field.field_name] ?? null}
                    {...hintForField(verdicts, field.field_name)}
                  />
                )}

                {suggestions
                  .filter((suggestion) => suggestion.field === field.field_name)
                  .map((suggestion) => (
                    <div
                      key={suggestion.suggestion_id}
                      style={{
                        padding: 'var(--space-2)',
                        borderTop: '1px solid var(--border-default)',
                        backgroundColor: 'var(--bg-card)',
                      }}
                    >
                      <SuggestionCard
                        suggestion={suggestion}
                        onAccept={onSuggestionAccept}
                        onReject={onSuggestionReject}
                      />
                    </div>
                  ))}
              </FieldCard>
            ))}
          </FieldGroup>
        );
      })}
    </div>
  );
}

/**
 * 그 필드를 가리키는 판정의 수정 가이드를 찾습니다.
 *
 * 시안에는 "저해상도 스캔 — 인식 신뢰도가 기준에 미달합니다" 같은 사유가
 * 적혀 있었지만, FieldValue에는 사유를 담을 자리가 없습니다. 지어내지 않고,
 * 판정(Verdict)이 실제로 남긴 action_hint가 있을 때만 보여줍니다.
 */
function hintForField(
  verdicts: Verdict[],
  fieldName: string,
): { actionHint: string | null; ruleId: string | null } {
  const verdict = verdicts.find((candidate) => candidate.target_fields.includes(fieldName));
  if (verdict === undefined) return { actionHint: null, ruleId: null };
  return { actionHint: verdict.action_hint, ruleId: verdict.rule_id };
}

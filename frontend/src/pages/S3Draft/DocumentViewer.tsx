import type { CSSProperties } from 'react';
import type { DocumentMeta, FieldValue } from '../../types/domain';
import { DOCUMENT_KIND_LABEL, labelOfField } from '../../constants/domain';
import {
  MOCK_DOCUMENT_ORIGINAL_SIZE,
  bboxToScreenRect,
  type DocumentDisplaySize,
} from './documentGeometry';

// 문서를 화면에 얼마나 크게 그릴지. 612:792 비율을 유지한 채 폭만 480px로 고정.
// 나중에 실제 PDF 뷰어로 바꿀 때도 이 크기를 그대로 두고, 안쪽 내용만 바꾸면 됩니다.
// export하는 이유: S3Draft가 영향 패널을 여는 동안 뷰어 대신 보여주는 "숨김
// 안내" 박스 높이를 여기 맞춰서, 뷰어가 있던 자리 크기가 느껴지게 합니다.
export const DISPLAY_SIZE: DocumentDisplaySize = {
  width: 480,
  height: Math.round(
    480 * (MOCK_DOCUMENT_ORIGINAL_SIZE.height / MOCK_DOCUMENT_ORIGINAL_SIZE.width),
  ),
};

interface DocumentViewerProps {
  /** 지금 사용자가 보고 있는 필드. bbox가 있으면 문서 위에 노란 박스로 표시합니다 */
  focusedField?: FieldValue;
  /**
   * 이 선적에 붙어 있는 서류. 탭으로 그립니다.
   *
   * 시안은 4개(신용장·선적요청서·상업송장·포장명세서)를 고정으로 그렸지만,
   * 여기서는 넘어온 목록 그대로만 그립니다 — 서류가 2건뿐인 선적은 탭도
   * 2개가 뜨는 게 맞습니다.
   */
  documents: DocumentMeta[];
}

/**
 * S3 초안 편집기의 문서 뷰어.
 *
 * 지금은 백엔드가 없어서 실제 PDF 파일이 없기 때문에, 진짜 문서 대신
 * 회색 사각형(목업)을 보여줍니다. focusedField로 필드가 넘어오고 그 필드에
 * bbox(원본 좌표)가 있으면, 문서의 어느 위치에서 그 값을 읽었는지 반투명한
 * 노란 박스로 겹쳐서 표시합니다.
 *
 * 나중에 실제 PDF 파일이 생기면, 아래 "회색 사각형 자리"만 실제 PDF
 * 페이지를 그리는 컴포넌트로 바꿔치기하면 됩니다. 하이라이트를 그리는
 * bboxToScreenRect 계산과 DISPLAY_SIZE는 그대로 재사용할 수 있습니다.
 */
export function DocumentViewer({ focusedField, documents }: DocumentViewerProps) {
  // 어느 탭을 보여줄지는 지금 선택된 필드가 정합니다 — 필드를 누르면 그 값이
  // 나온 서류로 자동으로 넘어갑니다. 아직 아무 필드도 안 눌렀으면 첫 서류.
  // (탭을 직접 누르는 기능은 필드 클릭과 규칙이 충돌할 수 있어 뒤로 미룹니다)
  const activeDocument =
    documents.find((document) => document.document_id === focusedField?.source_doc_id) ??
    documents[0] ??
    null;
  const bbox = focusedField?.bbox ?? null;
  const highlightRect =
    bbox !== null ? bboxToScreenRect(bbox, MOCK_DOCUMENT_ORIGINAL_SIZE, DISPLAY_SIZE) : null;

  // 폭·높이는 이제 인라인이 아니라 index.css의 .s3-viewer-box가 정합니다 —
  // 1024px 이하에서는 미디어쿼리로 width:100%(최대 480px)가 되고, 높이는
  // aspect-ratio가 비율대로 따라갑니다. highlightRect는 여전히 DISPLAY_SIZE
  // (480x621) 기준으로 계산하므로, 실제 렌더 폭이 480px보다 작아지는 아주
  // 좁은 화면(480px 미만 컨테이너)에서는 하이라이트 위치가 살짝 어긋날 수
  // 있습니다 — 지금 확인 대상인 1024·768px에서는 뷰어가 항상 480px로
  // 렌더되니 문제 없습니다.
  const documentAreaStyle: CSSProperties = {
    position: 'relative',
    backgroundColor: 'var(--bg-card)',
    border: '1px solid var(--border-default)',
    borderRadius: 'var(--radius-card)',
    boxShadow: 'var(--shadow-card)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  };

  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 6,
        // 오른쪽 필드 목록을 스크롤해도 문서 뷰어는 화면에 계속 보이도록 고정.
        // NavBar가 sticky/fixed가 아니라 페이지 상단과 안 겹치므로 top은 여백값만 주면 됨.
        position: 'sticky',
        top: 'var(--space-5)',
      }}
    >
      {documents.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%' }}>
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 2,
              borderBottom: '1px solid var(--border-default)',
            }}
          >
            {documents.map((document) => {
              const isActive = document.document_id === activeDocument?.document_id;
              return (
                <span
                  key={document.document_id}
                  style={{
                    padding: '8px 11px',
                    fontSize: 12.5,
                    fontWeight: isActive ? 700 : 500,
                    color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                    borderBottom: `2px solid ${isActive ? 'var(--brand-primary)' : 'transparent'}`,
                    marginBottom: -1,
                  }}
                >
                  {DOCUMENT_KIND_LABEL[document.kind]}
                </span>
              );
            })}
          </div>
          {activeDocument !== null && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 'var(--space-2)',
                fontSize: 11.5,
                color: 'var(--text-muted)',
              }}
            >
              <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                {activeDocument.file_name}
              </span>
              <span style={{ flexShrink: 0 }}>{activeDocument.page_count}p</span>
            </div>
          )}
        </div>
      )}

      {/* 실제 문서를 대신하는 회색 사각형 자리. 나중에 여기를 PDF 렌더링으로 교체 */}
      <div className="s3-viewer-box" style={documentAreaStyle}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>문서 미리보기 (목업)</span>

        {highlightRect !== null && (
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: highlightRect.left,
              top: highlightRect.top,
              width: highlightRect.width,
              height: highlightRect.height,
              backgroundColor: 'rgba(250, 204, 21, 0.35)',
              border: '1.5px solid rgba(217, 160, 12, 0.9)',
              borderRadius: 2,
            }}
          />
        )}
      </div>

      {/* 뷰어 아래 근거 정보 — 실제 PDF가 없어 회색 박스가 비어 보이는 자리를
          "지금 무엇을 보고 있는지"로 채웁니다. 값은 전부 선택된 필드에서 옵니다 */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          width: '100%',
          padding: 'var(--space-2) 0 0',
          textAlign: 'left',
        }}
      >
        {focusedField === undefined ? (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            오른쪽에서 필드를 누르면 그 값을 어느 서류 어디에서 읽었는지 여기 표시됩니다.
          </span>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-primary)' }}>
                {labelOfField(focusedField.field_name)}
              </span>
              <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                {focusedField.bbox === null
                  ? '원문 근거 없음'
                  : `${focusedField.source_doc_id} · ${focusedField.page}p · 신뢰도 ${Math.round(
                      focusedField.confidence * 100,
                    )}%`}
              </span>
            </div>

            {/* 다른 서류에 다른 값이 있으면 그것도 밝힙니다 (시안의 "충돌 후보" 카드) */}
            {(focusedField.candidates ?? [])
              .filter((candidate) => candidate.value !== focusedField.value)
              .map((candidate) => (
                <div
                  key={`${candidate.source_doc_id}-${candidate.value}`}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 3,
                    padding: '10px 12px',
                    border: '1px solid var(--border-default)',
                    borderLeft: '4px solid var(--severity-critical)',
                    borderRadius: 6,
                    backgroundColor: 'var(--bg-card)',
                  }}
                >
                  <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--severity-critical)' }}>
                    다른 서류의 충돌 후보
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {candidate.value}
                    {candidate.normalized_value !== null && (
                      <span style={{ fontWeight: 400, color: 'var(--text-secondary)' }}>
                        {' '}
                        {candidate.normalized_value}
                      </span>
                    )}
                  </span>
                  <span style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                    {candidate.source_doc_id} · {candidate.page}p · 신뢰도{' '}
                    {Math.round(candidate.confidence * 100)}%
                  </span>
                </div>
              ))}
          </>
        )}
      </div>
    </div>
  );
}

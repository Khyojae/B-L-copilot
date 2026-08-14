import type { CSSProperties } from 'react';
import type { FieldValue } from '../../types/domain';
import {
  MOCK_DOCUMENT_ORIGINAL_SIZE,
  bboxToScreenRect,
  type DocumentDisplaySize,
} from './documentGeometry';

// 문서를 화면에 얼마나 크게 그릴지. 612:792 비율을 유지한 채 폭만 480px로 고정.
// 나중에 실제 PDF 뷰어로 바꿀 때도 이 크기를 그대로 두고, 안쪽 내용만 바꾸면 됩니다.
const DISPLAY_SIZE: DocumentDisplaySize = {
  width: 480,
  height: Math.round(
    480 * (MOCK_DOCUMENT_ORIGINAL_SIZE.height / MOCK_DOCUMENT_ORIGINAL_SIZE.width),
  ),
};

interface DocumentViewerProps {
  /** 지금 사용자가 보고 있는 필드. bbox가 있으면 문서 위에 노란 박스로 표시합니다 */
  focusedField?: FieldValue;
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
export function DocumentViewer({ focusedField }: DocumentViewerProps) {
  const bbox = focusedField?.bbox ?? null;
  const highlightRect =
    bbox !== null ? bboxToScreenRect(bbox, MOCK_DOCUMENT_ORIGINAL_SIZE, DISPLAY_SIZE) : null;

  const documentAreaStyle: CSSProperties = {
    position: 'relative',
    width: DISPLAY_SIZE.width,
    height: DISPLAY_SIZE.height,
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
      {/* 실제 문서를 대신하는 회색 사각형 자리. 나중에 여기를 PDF 렌더링으로 교체 */}
      <div style={documentAreaStyle}>
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
    </div>
  );
}

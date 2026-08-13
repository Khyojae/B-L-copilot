import type { BBox } from '../../types/domain';

// ─────────────────────────────────────────────
// 좌표 변환
//
// mockFields의 bbox([x0, y0, x1, y1])는 "문서 원본 크기" 기준 좌표입니다.
// 예: f('shipper', ..., [72, 118, 340, 136]) → 원본 문서에서 왼쪽에서 72,
// 위에서 118 되는 지점부터 시작하는 사각형.
//
// 화면에는 문서를 원본 그대로의 크기로 그리지 않고 작게 축소해서 보여주므로,
// bbox 좌표도 같은 비율로 축소해서 화면 픽셀 좌표로 바꿔줘야 합니다.
// 이 계산만 따로 함수로 뺀 이유: 지금은 회색 사각형이지만 나중에 실제 PDF
// 렌더러(예: react-pdf)로 바꿔도, "그 PDF가 화면에 몇 px로 그려지는지"만
// 알려주면 이 함수를 그대로 재사용할 수 있기 때문입니다. 사각형 목업인지
// 진짜 PDF인지는 이 함수가 몰라도 됩니다.
// ─────────────────────────────────────────────

/** 문서 원본 좌표계의 가로·세로 크기. bbox 숫자들이 이 크기를 기준으로 찍혀 있습니다 */
export interface DocumentOriginalSize {
  width: number;
  height: number;
}

/** 문서가 화면에 실제로 그려지는 가로·세로 픽셀 크기 */
export interface DocumentDisplaySize {
  width: number;
  height: number;
}

/** 화면 위에 그릴 사각형의 위치·크기 (문서 영역 왼쪽 위 기준 px) */
export interface ScreenRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * mockFields의 bbox 좌표계 크기.
 * 612 x 792는 A4와 비슷한 세로 문서 비율이면서, 픽스처의 bbox 값들
 * (최대 x=612, y=448 정도)이 실제로 그 안에 들어오는 크기입니다.
 */
export const MOCK_DOCUMENT_ORIGINAL_SIZE: DocumentOriginalSize = {
  width: 612,
  height: 792,
};

/**
 * bbox(문서 원본 좌표) → 화면 픽셀 좌표 변환.
 *
 * "원본 크기 대비 화면 크기가 몇 배 축소됐는지"만 계산해서 곱하는 함수라서,
 * 사각형 목업이든 진짜 PDF든 알 필요가 없습니다. 원본 크기와 화면 크기만
 * 정확히 넣어주면 됩니다.
 */
export function bboxToScreenRect(
  bbox: BBox,
  original: DocumentOriginalSize,
  display: DocumentDisplaySize,
): ScreenRect {
  const [x0, y0, x1, y1] = bbox;
  const scaleX = display.width / original.width;
  const scaleY = display.height / original.height;

  return {
    left: x0 * scaleX,
    top: y0 * scaleY,
    width: (x1 - x0) * scaleX,
    height: (y1 - y0) * scaleY,
  };
}

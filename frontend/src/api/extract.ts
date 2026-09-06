/**
 * F1 인테이크 — 업로드한 파일에서 B/L 초안 필드를 뽑아옵니다.
 *
 * S2(업로드)가 이 함수만 부르면 됩니다. 파일 종류마다 백엔드 주소가 다른데
 * 그 판단을 여기서 합니다.
 */

import { postFile } from './client';
import { toFieldValues } from './adapters';
import type { WireDraftResponse } from './wire';
import type { FieldValue } from '../types/domain';

/**
 * 확장자별 백엔드 주소.
 *
 * 근거: docs/ai-service/f1-intake.md — 이미지는 `/extract`, PDF 는
 * `/extract/pdf`, 엑셀·메일은 각각 별도 주소입니다. 주소를 잘못 고르면
 * 백엔드가 400 으로 거절합니다(내용으로 형식을 확인하기 때문).
 */
const PATH_BY_EXT: Record<string, string> = {
  '.pdf': '/extract/pdf',
  '.jpg': '/extract',
  '.jpeg': '/extract',
  '.png': '/extract',
  '.tif': '/extract',
  '.tiff': '/extract',
  // 아래 둘은 constants/domain.ts 에서 '이번 기간 미지원'으로 막혀 있어
  // 여기까지 오지 않습니다. 백엔드에는 이미 있으므로 자리만 적어둡니다.
  '.xlsx': '/extract/excel',
  '.eml': '/extract/email',
};

function getExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf('.');
  return dotIndex === -1 ? '' : fileName.slice(dotIndex).toLowerCase();
}

/**
 * 파일 1개를 백엔드에 올리고, 화면이 쓰는 필드 목록을 돌려줍니다.
 *
 * 실패하면 오류를 던집니다 — 부르는 쪽(S2)이 잡아서 '실패'로 보여줍니다.
 */
export async function extractDraft(
  file: File,
  signal?: AbortSignal,
): Promise<FieldValue[]> {
  const ext = getExtension(file.name);
  const path = PATH_BY_EXT[ext];

  if (path === undefined) {
    // .txt 처럼 화면은 받아주지만 백엔드에 대응 주소가 없는 형식입니다.
    throw new Error(`${ext || '이 형식'}은(는) 아직 추출 서버가 처리하지 못합니다.`);
  }

  const draft = await postFile<WireDraftResponse>(path, file, signal);
  return toFieldValues(draft);
}

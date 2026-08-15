/**
 * F3 하자 검증 — `POST /verify` 한 번 호출하고 화면용으로 번역까지.
 *
 * 화면은 이 함수만 부르면 됩니다. 백엔드 응답 모양(`wire.ts`)이나 번역
 * 규칙(`adapters.ts`)을 화면이 알 필요는 없습니다.
 */

import { postJson } from './client';
import { toBLPayload, toVerifyView, type VerifyView } from './adapters';
import type { WireVerifyRequest, WireVerifyResponse } from './wire';
import type { FieldValue } from '../types/domain';

export interface VerifyOptions {
  /** 신용장 조건(MT700). 없으면 백엔드가 서류 내부 정합성만 검사합니다 */
  lc?: Record<string, string>;
  /**
   * 제시기간 계산 기준 시각.
   * 시연·테스트에서 이걸 넣어야 매번 같은 결과가 나옵니다.
   */
  asOf?: string;
  /** 화면을 떠날 때 요청을 취소하기 위한 신호 */
  signal?: AbortSignal;
}

/**
 * 필드 목록을 백엔드에 보내 하자 검증 결과를 받아옵니다.
 *
 * 용어: `async` 함수는 결과를 바로 주지 않고 "곧 줄게"라는 약속(Promise)을
 * 줍니다. 부르는 쪽에서 `await` 로 기다립니다.
 */
export async function verifyShipment(
  fields: FieldValue[],
  options: VerifyOptions = {},
): Promise<VerifyView> {
  const body: WireVerifyRequest = {
    bl: toBLPayload(fields),
    ...(options.lc ? { lc: options.lc } : {}),
    ...(options.asOf ? { as_of: options.asOf } : {}),
  };

  const res = await postJson<WireVerifyResponse>('/verify', body, options.signal);

  // 백엔드가 판정 시각을 안 주므로 응답을 받은 시각으로 대신합니다.
  // 동기 호출이라 실제 판정 시각과 밀리초 단위 차이입니다.
  return toVerifyView(res, new Date().toISOString());
}

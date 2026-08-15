/**
 * 화면에서 `/verify` 를 부르기 쉽게 감싼 훅(hook).
 *
 * 용어: "훅"은 React 컴포넌트가 상태(state)나 바깥 세계(네트워크 등)를
 * 쓰게 해주는 함수입니다. 이름이 `use` 로 시작해야 React 가 알아봅니다.
 */

import { useEffect, useState } from 'react';
import { verifyShipment } from './verify';
import type { VerifyView } from './adapters';
import type { FieldValue } from '../types/domain';

/**
 * 지금 어떤 상태인지.
 *
 * · `loading` — 백엔드에 물어보는 중
 * · `ok`      — 받아왔음. `view` 에 결과가 들어 있음
 * · `error`   — 실패. `error` 에 이유가 들어 있음 (화면은 목데이터로 물러남)
 */
export type VerifyState =
  | { status: 'loading' }
  | { status: 'ok'; view: VerifyView }
  | { status: 'error'; error: Error };

export function useVerify(
  fields: FieldValue[] | null,
  options: { asOf?: string } = {},
): VerifyState {
  const [state, setState] = useState<VerifyState>({ status: 'loading' });
  const { asOf } = options;

  useEffect(() => {
    if (fields === null) return;

    // 화면을 떠나면 요청을 취소합니다. 취소하지 않으면 이미 사라진
    // 컴포넌트에 결과를 넣으려다 경고가 납니다.
    const controller = new AbortController();

    setState({ status: 'loading' });

    verifyShipment(fields, { asOf, signal: controller.signal })
      .then((view) => setState({ status: 'ok', view }))
      .catch((err: unknown) => {
        // 취소는 실패가 아닙니다 — 그냥 조용히 끝냅니다.
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          error: err instanceof Error ? err : new Error(String(err)),
        });
      });

    return () => controller.abort();
    // fields 는 목데이터라 매 렌더마다 같은 객체입니다. 선적이 바뀌면
    // 새 배열이 오므로 그때만 다시 부릅니다.
  }, [fields, asOf]);

  return state;
}

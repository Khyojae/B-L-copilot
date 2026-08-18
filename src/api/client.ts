/**
 * aiService 로 요청을 보내는 아주 얇은 도구.
 *
 * 지금은 aiService(FastAPI)에 **직접** 붙습니다. 나중에 게이트웨이가 앞에
 * 서면 base URL 하나만 바꾸면 되도록 여기 한 곳에 모아둡니다.
 */

/**
 * 백엔드 주소.
 *
 * 기본값 `/ai-api` 는 **Vite 개발 프록시**를 가리킵니다 (vite.config.ts 참고).
 *
 * aiService 에 CORS 가 열려 있어서 `http://localhost:5000` 을 직접 적어도
 * 동작합니다. 그래도 프록시를 기본으로 두는 이유는, 직접 붙이면 백엔드의
 * 허용 목록(`CORS_ALLOW_ORIGINS`)과 프론트 주소가 **양쪽 다** 맞아야 하기
 * 때문입니다. 프록시를 거치면 브라우저에게는 같은 출처(5173)라 그 조건이
 * 아예 사라집니다.
 *
 * `import.meta.env` 는 Vite 가 `.env` 파일의 값을 넣어주는 자리입니다.
 * `VITE_` 로 시작하는 이름만 들어옵니다 (그래야 실수로 비밀값이 화면에
 * 딸려나가지 않습니다).
 */
export const AI_API_BASE_URL: string =
  import.meta.env.VITE_AI_API_BASE_URL ?? '/ai-api';

/**
 * 백엔드가 에러를 돌려줬을 때 던지는 오류.
 *
 * 용어: `extends Error` 는 "기본 오류에 정보를 더 붙인 오류를 만든다"는 뜻입니다.
 * 화면에서 `err instanceof ApiError` 로 "백엔드가 거절한 것"과 "네트워크가
 * 끊긴 것"을 구분할 수 있습니다.
 */
export class ApiError extends Error {
  // 생성자 인자에 바로 readonly 를 붙이는 축약형(파라미터 프로퍼티)은 이
  // 프로젝트의 tsconfig(`erasableSyntaxOnly`)가 막습니다 — 타입만 지우면
  // 그대로 JS 가 되는 문법만 쓰겠다는 설정이라, 필드를 따로 선언합니다.
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`aiService ${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * JSON 을 POST 하고 JSON 을 받습니다.
 *
 * `<TRes>` 는 "받아올 응답의 타입을 부르는 쪽이 정한다"는 뜻입니다 (제네릭).
 * 예: `postJson<WireVerifyResponse>('/verify', body)`
 */
export async function postJson<TRes>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<TRes> {
  const res = await fetch(`${AI_API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    // FastAPI 는 에러를 { "detail": "..." } 로 내려줍니다.
    // 에러 본문이 JSON 이 아닐 수도 있으니(502 등) 실패해도 넘어갑니다.
    const detail = await res
      .json()
      .then((j: { detail?: string }) => j.detail ?? res.statusText)
      .catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }

  return (await res.json()) as TRes;
}

/**
 * 파일 하나를 올리고 JSON 을 받습니다 (F1 인테이크 `/extract*`).
 *
 * 용어: `FormData` 는 "파일 첨부가 가능한 요청 본문"입니다. JSON 과 달리
 * 파일 원본 바이트를 그대로 실어 보낼 수 있습니다.
 *
 * 백엔드(FastAPI)는 `file` 이라는 이름의 첨부를 기대합니다
 * (`api/main.py` 의 `file: UploadFile = File(...)`).
 */
export async function postFile<TRes>(
  path: string,
  file: File,
  signal?: AbortSignal,
): Promise<TRes> {
  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`${AI_API_BASE_URL}${path}`, {
    method: 'POST',
    // ⚠ Content-Type 을 직접 넣으면 안 됩니다. multipart 는 본문을 나누는
    //   경계 문자열이 헤더에 같이 들어가야 하는데, 그건 브라우저만 압니다.
    body: form,
    signal,
  });

  if (!res.ok) {
    const detail = await res
      .json()
      .then((j: { detail?: unknown }) => readDetail(j.detail) ?? res.statusText)
      .catch(() => res.statusText);
    throw new ApiError(res.status, detail);
  }

  return (await res.json()) as TRes;
}

/**
 * FastAPI 의 `detail` 을 사람이 읽을 한 줄로 바꿉니다.
 *
 * 보통은 문자열이지만, 422(스키마 불일치)일 때만 배열로 옵니다
 * (`[{ loc, msg, type }, ...]`). 배열을 그대로 화면에 쓰면 "[object Object]"
 * 가 되므로 `msg` 만 뽑아 이어 붙입니다.
 */
function readDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: { msg?: string }) => item.msg ?? JSON.stringify(item))
      .join(' · ');
  }
  return null;
}

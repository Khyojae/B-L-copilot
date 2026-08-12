# aiService API 명세 — 공통 규약

`aiService/api/main.py` (FastAPI, `:5000`). Express 게이트웨이(`:4000`)가 호출한다.

엔드포인트별 상세는 기능 문서에 있다. 이 문서는 **모든 엔드포인트에 공통으로 적용되는 규약**과 `/health` 만 다룬다.

| 기능 | 엔드포인트 | 문서 |
| --- | --- | --- |
| F1 인테이크 | `/extract/label` `/extract` `/extract/pdf` `/extract/excel` `/extract/email` | [f1-intake.md](f1-intake.md#api-명세) |
| F3 하자 예측 | `/rules` `/lc/mt700` `/verify` | [f3-defect-prediction.md](f3-defect-prediction.md#api-명세) |
| F4 리포트 | `/report` `/report/pdf` `/report/share` `/report/shared/{token}` `/report/shared/{token}/pdf` | [f4-report.md](f4-report.md#api-명세) |
| 공통 | `/health` | 이 문서 |

설계 근거(왜 이런 구조인가)는 [api.md](api.md) 를 볼 것.

## Base URL

```
http://localhost:5000
```

게이트웨이 경유 시 프리픽스는 게이트웨이가 정한다.

## 인증

없다. 이 서비스는 내부망 전용이며 인증은 게이트웨이 책임이다.

## 저장하지 않는다

이 서비스는 상태를 갖지 않는다. 저장 책임은 게이트웨이에 있다. 그래서 어떤 엔드포인트도 조회·목록·삭제를 제공하지 않는다 — 모든 요청이 입력을 통째로 싣고 온다.

F4 공유 링크도 예외가 아니다. 토큰이 입력을 싣고 다닌다([f4-report.md](f4-report.md#api-명세)).

## 에러 응답 형식

**주의 — 사내 템플릿의 `{"error", "message"}` 와 다르다.**

FastAPI `HTTPException` 의 기본 형식을 그대로 쓴다.

```json
{
  "detail": "bl 필드가 비어 있습니다."
}
```

422(Pydantic 검증 실패)만 `detail` 이 배열이다.

```json
{
  "detail": [
    { "loc": ["body", "bl"], "msg": "Field required", "type": "missing" }
  ]
}
```

> 게이트웨이에서 `{"error", "message"}` 로 감쌀지, 이 서비스에 예외 핸들러를 추가할지는 **미정**이다. 프런트가 직접 붙는다면 현재는 `detail` 을 읽어야 한다.

## 상태 코드

| 코드 | 언제 |
| --- | --- |
| 400 | 요청 자체가 잘못됨 — 빈 파일, 형식 불일치, 페이지 범위 초과, `bl` 누락 |
| 404 | 공유 토큰 서명 깨짐·형식 오류 |
| 410 | 공유 링크 만료 |
| 413 | 공유 토큰이 URL 길이 한계(6000자) 초과 |
| 422 | Pydantic 스키마 불일치 |
| 503 | OCR 엔진·PyMuPDF 미설치 |

**503 과 500 을 가르는 이유** — 게이트웨이 재시도 때문이다. 라이브러리 미설치는 서버 구성 문제지 요청 오류가 아니므로, 500 으로 흘리면 게이트웨이가 무의미하게 재시도한다.

**410 과 404 를 가르는 이유** — 만료를 404 로 내면 받은 쪽이 '주소가 틀렸나'를 의심한다.

---

# GET `/health`

## **설명**

서비스 상태와 룰 적재 수를 반환한다. 헬스체크·기동 확인용.

## **Request**

**Path Parameter**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| 없음 | | |

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| 없음 | | | |

**Header**

```json
{
}
```

**Body**

```json
{
}
```

## **Response**

**Success (200)**

```json
{
  "status": "ok",
  "rules_loaded": 29,
  "env": "development"
}
```

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `status` | string | 항상 `ok` |
| `rules_loaded` | int | 적재된 룰 수. 룰 카탈로그가 깨졌으면 **서버가 뜨지 않으므로** 이 값이 0 인 응답은 나오지 않는다 |
| `env` | string | `ENV` 환경변수. 기본 `development` |

**Error**

없음. 서비스가 떠 있으면 항상 200 이다.

---

## 자동 생성 문서

FastAPI 가 OpenAPI 스키마를 낸다. 이 문서와 어긋나면 그쪽이 정답이다.

```
http://localhost:5000/docs         # Swagger UI
http://localhost:5000/openapi.json
```

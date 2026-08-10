# aiService API

> 기획안 6.2 백엔드: "Express 5(API 게이트웨이·인증·알림) + **FastAPI(AI 모듈군)**"

Express 게이트웨이(`:4000`)가 이 서비스(`:5000`)를 호출한다. `aiService/api/` 에 있다.

## 저장하지 않는다

이 서비스는 **상태를 갖지 않는다.** 저장 책임은 게이트웨이에 있다.

계획 단계에서는 여기에 저장소 포트(인터페이스 + 인메모리 구현)를 두려 했으나, 서비스 자체가 저장하지 않으면 포트가 필요 없다. 더 단순하고, AI 모듈이 스키마 변경에 묶이지 않는다. 저장소 추상화가 필요해지는 건 Express 계층이고 그건 이번 범위 밖이다.

결과적으로 스키마가 확정돼도 이 서비스 코드는 바뀌지 않는다.

## 엔드포인트

| 메서드 | 경로 | 기능 | 화면 |
|---|---|---|---|
| GET | `/health` | 상태·룰 적재 수 | — |
| GET | `/rules` | 적재된 룰 목록 | S11 설정 |
| POST | `/extract/label` | F1 — 라벨 JSON → 초안 | S3 초안 편집기 |
| POST | `/extract` | F1 — 이미지 업로드 → 초안 | S2 업로드 |
| POST | `/verify` | F3 — 하자 검증 | S4 검증 결과 |
| POST | `/report` | F4 — 리포트 JSON | S7 리포트 |
| POST | `/report/pdf` | F4 — 리포트 PDF | S7 내보내기 |
| POST | `/report/share` | F4 — 공유 링크 발급 | S7 공유 |
| GET | `/report/shared/{token}` | 공유된 리포트 JSON | — |
| GET | `/report/shared/{token}/pdf` | 공유된 리포트 PDF (inline) | — |

### 공유는 저장 없이 한다

기획안 5절이 "PDF 출력·**공유** 가능"을 요구하지만, 이 서비스는 저장하지 않는다(위 절). 리포트를 저장하기 시작하면 그 원칙이 깨지고 만료·삭제·권한까지 AI 모듈이 떠안게 된다.

그래서 **링크가 입력을 싣는다.** 토큰은 `v1.<zlib+base64url(입력)>.<HMAC-SHA256>` 이고, 열릴 때마다 서버가 같은 리포트를 다시 조립한다. 저장소도 DB 도 없다. 전체 B/L + L/C 를 실어도 토큰은 620자 안팎이다.

발급 시 한 번 조립해 보고 실패하면 400 을 낸다. 열어 봐야 터지는 링크를 쥐여주면 받는 쪽에서 깨지고, 그때는 원인을 알 방법이 없다.

**한계 두 가지를 알고 쓸 것.**

1. **토큰은 암호문이 아니다.** 서명은 위조를 막을 뿐 내용을 가리지 않는다. 링크를 가진 사람은 base64 를 풀어 B/L 원문을 읽을 수 있다 — 받을 사람은 어차피 리포트를 볼 사람이므로 의도상 문제는 아니지만, **링크가 새면 서류가 샌다.** 완화책은 짧은 만료뿐이다(기본 7일, `ttl_seconds` 로 조정).
2. **`REPORT_SHARE_SECRET` 를 설정하지 않으면 프로세스마다 임시 키를 쓴다.** 재시작하면 발급한 링크가 전부 죽는다. 고정 기본값을 두면 소스를 읽은 누구나 토큰을 위조할 수 있으므로 이쪽을 택했다. 기동 로그와 발급 응답(`ephemeral_secret`, `warning`)이 이 상태를 알린다.

### 두 개의 추출 경로

`/extract` 가 운영 경로, `/extract/label` 이 라벨 로드 경로다.

`/extract/label` 을 두는 이유는 PaddleOCR·PaddlePaddle 설치가 무겁고 플랫폼을 타는데, 파서 동작 확인과 시연에는 그게 필요 없기 때문이다. CI 에서도 이 경로로 전 구간을 검증한다.

### 상태 코드

| 코드 | 언제 |
|---|---|
| 400 | `bl` 이 비었거나 빈 파일 업로드 — 요청 자체가 잘못됨 |
| 404 | 공유 토큰의 서명이 깨졌거나 형식이 틀림 |
| 410 | 공유 링크 만료 — **404 로 내면 받은 쪽이 '주소가 틀렸나'를 의심한다** |
| 413 | 공유 링크가 URL 길이 한계 초과 (`MAX_TOKEN_BYTES`) |
| 422 | Pydantic 스키마 불일치 |
| 503 | OCR 엔진 미설치 — **서버 구성 문제지 요청 오류가 아니다** |

503 을 쓰는 이유는 게이트웨이 재시도 때문이다. 500 으로 흘리면 게이트웨이가 무의미하게 재시도한다.

## 입력 형태

`/verify` 와 `/report` 는 `bl` 을 **평범한 dict** 로 받는다. F1 이 뽑은 값이든 S3 편집기에서 사람이 고친 값이든 같은 형태다.

두 경로를 가르면 '편집 후 재검증'이 다른 코드 경로를 타게 되고, 그쪽에만 있는 버그가 생긴다.

`as_of` 는 제시기간 계산의 기준 시각이다. 생략하면 현재 시각을 쓰지만, 테스트·시연에서는 넣어야 결과가 고정된다.

## 룰 카탈로그는 기동 시 1회 로드

요청마다 읽으면 YAML 파싱이 응답 시간에 들어가고, 카탈로그 오류를 기동이 아니라 첫 요청에서 발견하게 된다. lifespan 핸들러에서 검증하므로 **룰이 깨졌으면 서버가 뜨지 않는다.**

## 실행

```bash
cd aiService
pip install -r requirements.txt
uvicorn api.main:app --port 5000 --reload
```

문서: <http://localhost:5000/docs>

### 동작 확인 기록

```
$ curl -s http://127.0.0.1:5099/health
{"status":"ok","rules_loaded":21,"env":"development"}
```

```
$ curl -X POST .../verify -d '{"bl":{...},"lc":{...},"as_of":"2026-06-10T00:00:00"}'
 확률 1.0 | 심각도 {'critical': 6, 'warning': 1, 'info': 0} | 평가 18 | 미검사 3
   D003  선적항이 L/C 지정 항구와 다릅니다. (서류 SHANGHAI, CHINA / L/C BUSAN)
   D005B Consignee 가 L/C 지정과 다릅니다. (서류 WRONG CO. / L/C DHHJ FRANCHISING CO., LTD.)
   D006  화물 명세에 L/C 요구 키워드가 없습니다. (누락 SPARE PARTS)
   D013  분할선적 금지 조건인데 분할선적 표시가 있습니다. (PARTIAL SHIPMENT)
```

```
$ curl -X POST .../report -d '{...}'
 등급 높음 | 산출 rules-v1 | 요약출처 template
 헤드라인: 제출 전 정정이 필요한 치명 하자 6건이 발견되었습니다.
 기한: 2026-06-22 | 남은일수 12
 미제출: ['요구 서류: COMMERCIAL INVOICE', '요구 서류: PACKING LIST']
 예상: 하자 통보 및 재제출 요구 예상
```

```
$ curl -X POST .../report/pdf -o out.pdf
content-type: application/pdf
content-disposition: attachment; filename="BL_Copilot_Report_HG290309.pdf"
  10,295 bytes | 3쪽 | 한글 1077자
```

## LLM 설정

`.env.example` 의 `LLM_PROVIDER` 로 분기한다. 기획안 6.1 의 "동일 코드베이스에서 환경 설정으로 분기"(SaaS 클라우드 LLM / 폐쇄망 로컬 LLM)를 이 자리에서 구현한다.

```bash
LLM_PROVIDER=template     # 외부 호출 없음 (기본값)
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
```

**키가 없거나 `changeme` 면 조용히 템플릿으로 떨어진다.** 개발·시연 환경에서 키 없이도 리포트가 완성되어야 하기 때문이다.

어느 쪽을 썼는지는 응답의 `summary.narrative_source` 에 남는다. LLM 호출이 실패해 템플릿으로 떨어진 경우에도 정확히 `template` 로 표기된다 — 요약기 클래스 이름으로 판정하면 실패했는데도 'AI 생성 요약'이라고 표기하게 되고, 그 값이 PDF 각주에 그대로 찍힌다.

## 테스트

```bash
cd aiService && python -m pytest        # 230 passed
```

| 파일 | 개수 |
|---|---|
| `test_rule_engine.py` | 46 |
| `test_defect_model.py` | 41 |
| `test_field_parser.py` | 38 |
| `test_api.py` | 29 |
| `test_draft.py` | 24 |
| `test_report.py` | 23 |
| `test_llm_providers.py` | 15 |
| `test_extractor.py` | 14 |

PaddleOCR·DB 없이 전부 돈다. FastAPI 미설치 시 `test_api.py` 는 자동으로 건너뛴다.

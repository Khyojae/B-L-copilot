# F4 — 선제 대응 서류 분석 리포트

> 기획안 5절 F4: "제출 전 종합 리포트 자동 생성: 하자 리스크 요약, 누락 서류·기한 체크리스트, 심각도별 수정 권고, 예상 심사 결과. PDF 출력·공유 가능"
> **AI 기술: F3 결과 종합 + LLM 리포트 생성**

F3 의 `Verdict` 를 사람이 읽는 문서로 옮긴다. `aiService/report/` 에 있다.

기획안 5.4(v2 · 1차에서는 5.2)는 이 리포트의 차별점을 이렇게 규정한다.

> 기존 상용 도구가 은행 심사 후 하자를 "통보"하는 문서를 낳는다면, 본 리포트는 제출 전에 "예방"하는 문서로서 하자 재제출 루프 자체를 제거하는 것을 목표로 한다

> **v2(2026-08-11) 대비.** 5.4 에 수용 기준이 붙었다 — 리포트 15초·PDF 포함 30초, **리포트 내 모든 수치가 원본 판정 데이터와 일치(자동 대조 100%)**, 모든 위반이 조문 인용과 최소 1개의 구체적 조치 문장 보유. 뒤의 둘은 아래 "골격은 결정론, LLM 은 산문만"이 구조로 보장하지만 **시간은 잰 적이 없다**(`remaining-work.md` 19번). 한편 10.1 컷라인은 이번 기간 F4 산출물을 "화면 미리보기와 PDF 출력, **공유 링크·권한 제어는 제외**"로 잘랐다 — 우리가 구현한 공유(11번)는 컷라인 **밖의 추가분**이며, 발표에서 그렇게 말해야 한다.

## 구성

기획안 5.4 의 5개 구성을 그대로 옮겼다. 여기에 하나를 더했다.

| # | 구성 | 출처 |
|---|---|---|
| ① | 요약 (하자 확률·심각도 분포) | `Verdict.counts`, `defect_probability` |
| ② | 항목별 리스크와 **근거 조문** | `Violation.source` (룰 카탈로그) |
| ③ | 누락 서류·제출 기한 체크리스트 | L/C 46A + UCP 600 Art.14(c) 계산 |
| ④ | 수정 권고 (우선순위순) | `Violation.remedy`, 심각도 정렬 |
| ⑤ | 예상 심사 결과 시나리오 | 심각도 분포 + 기한 상태 |
| **부록** | **미검사 항목** | `Verdict.skipped` |

**부록은 1차 기획안에 없던 추가분이다.** 검사하지 못한 룰을 리포트에서 감추면 사용자는 '검사했고 문제없다'로 읽는다. 제출 전 예방을 표방하는 문서가 그 오해를 만들면 안 된다.

> **v2 도 ⑥ 부록을 넣었다 — 다만 내용이 다르다.** v2 5.4 의 부록은 **판정에 사용된 룰 카탈로그 버전·모델 버전·입력 서류 목록과 해시**이고(5.8 판정 재현성 규약과 짝을 이룬다), 우리 부록은 *검사하지 못한 항목*이다. 둘은 배타적이지 않으므로 합쳐야 한다. **지금 리포트가 내는 버전 정보는 `model`(`rules-v1` / `xgboost`) 하나뿐이고 룰 카탈로그 버전·입력 해시는 없다.** 우리 쪽 부록의 취지는 v2 에서는 5.4 예외 규칙("위반이 없으면 축약본을 내되 검증 범위를 명시해 *검사하지 않아서 깨끗한 것*과 구분한다")이 그대로 받는다.

⑤ 예상 심사 결과에도 같은 취지가 들어간다:

> 다만 자료 부족으로 검사하지 못한 항목이 3건 있어, 이 결과가 서류 전체를 보증하지는 않습니다.

## 골격은 결정론, LLM 은 산문만

리포트의 수치·체크리스트·기한은 `builder.py` 가 전부 계산한다. LLM(`narrative.py`)은 이미 만들어진 리포트를 사람이 읽을 문장으로 옮기기만 한다.

두 가지 이유다.

1. **LLM 이 없거나 한도에 걸려도 리포트는 나와야 한다.** 발표 중에 외부 API 하나 때문에 산출물이 통째로 비는 상황을 만들지 않는다.
2. **수치를 LLM 이 만들면 검증할 방법이 없다.** 확률·기한·건수를 생성하게 두면 리포트의 숫자와 본문이 어긋나도 아무도 못 잡는다.

`TemplateNarrator` 가 기본값이고, LLM 이 붙으면 `narrative_source` 가 `template` → `llm` 으로 바뀐다. 어느 쪽으로 썼는지 리포트가 스스로 밝힌다.

## 제출 기한 계산

UCP 600 Art.14(c) 는 두 가지를 요구한다.

- 선적일로부터 제시기간(기본 21일, L/C 가 정하면 그 값) 이내
- 그리고 **어떤 경우에도** 신용장 유효기일(31D) 이내

둘 중 **이른 날**이 실질 기한이다. `Deadline.basis` 에 어떻게 계산했는지 남겨서, 사용자가 날짜를 납득할 수 있게 한다.

```python
Deadline(
    presentation_due=date(2026, 6, 22),   # 선적일 + 21일
    expiry=date(2026, 12, 31),            # 31D
    effective_due=date(2026, 6, 22),      # 이른 날
    days_left=12,
    basis="선적일 + 21일(UCP 600 Art.14(c)) / 신용장 유효기일(31D) 중 이른 날",
)
```

기한을 계산하지 못하면 체크리스트에 그 사실을 적는다 — 침묵하면 '기한 문제 없음'으로 읽힌다.

## 예상 심사 결과는 시나리오다

확정 예측이 아니다. 지금 확률의 출처가 학습된 모델이 아니라 룰 가중치일 수 있기 때문이다(`Verdict.model` 이 `rules-v1` 인 경우). 문구에서 단정을 피한다.

| 상태 | 문구 |
|---|---|
| 기한 경과 | 제시기한 경과 — 수리 불가 가능성 높음 |
| CRITICAL 있음 | 하자 통보 및 재제출 요구 예상 |
| WARNING 만 | 심사역 재량 — 하자 지적 가능성 있음 |
| 없음 | 수리 예상 |

기한 경과를 맨 앞에 두는 이유는, 제시기한이 지나면 하자 여부와 무관하게 거절될 수 있어서다.

## PDF

**한글 폰트는 ReportLab 내장 CID 폰트를 쓴다.**

```python
pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
```

원본 `ai_sample/report_generator.py` 는 macOS/Ubuntu 폰트 경로 목록을 뒤지는 방식이라 **Windows 에서 PDF 생성이 실패한다.** CID 폰트는 파일시스템에 의존하지 않아 전 플랫폼에서 동일하게 동작한다. 폰트 파일을 배포에 포함할 필요도 없다.

**`render_pdf()` 는 파일이 아니라 `bytes` 를 반환한다.** 저장 위치(S3·DB·로컬)를 호출부가 정하게 두기 위해서다. 스키마가 확정되면 `verification_reports` 에 넣든 S3 pre-signed URL 로 올리든 이 함수는 바뀌지 않는다.

## 사용

```python
from ruleEngine import RuleEngine, LCTerms
from report import build_report
from report.pdf import render_pdf

verdict = RuleEngine().verify(bl, lc, as_of=now)
report = build_report(
    verdict,
    bl.to_dict(),
    lc,
    submitted_documents=["COMMERCIAL INVOICE", "BILL OF LADING"],
    as_of=now,
)

report.to_dict()                      # S7 화면용 JSON
pathlib.Path("out.pdf").write_bytes(render_pdf(report))
```

## 실행 확인

하자 있는 건과 없는 건 양쪽으로 실제 PDF 를 만들어 확인했다.

```
[defect] 등급 높음 | 확률 1.0 | 리스크 8 | 권고 8 | 미검사 3 | 11,222B  → 3쪽, 한글 1126자
[clean ] 등급 낮음 | 확률 0.0 | 리스크 0 | 권고 0 | 미검사 3 |  6,998B  → 2쪽, 한글  441자
```

추출한 본문에서 근거 조문이 정상 출력되는 것을 확인했다.

```
치명  선적항 불일치
      선적항이 L/C 지정 항구와 다릅니다. (서류 SHANGHAI, CHINA / L/C BUSAN)
      근거: UCP 600 Art.20(a)(iii) — 선하증권상 선적항은 신용장에 명시된 선적항과 일치해야 한다.
      대상 필드: port_of_loading
```

## API 명세

공통 규약(Base URL·에러 형식·상태 코드)은 [api-spec.md](api-spec.md) 를 먼저 볼 것.

| 메서드 | 경로 | 기능 |
| --- | --- | --- |
| POST | `/report` | 리포트 JSON |
| POST | `/report/pdf` | 리포트 PDF (attachment) |
| POST | `/report/share` | 공유 링크 발급 |
| GET | `/report/shared/{token}` | 공유 리포트 JSON |
| GET | `/report/shared/{token}/pdf` | 공유 리포트 PDF (inline) |

요청 본문은 앞의 셋이 동일 계열이다 — `ReportRequest` = F3 `VerifyRequest` + `submitted_documents`, `ShareRequest` = `ReportRequest` + `ttl_seconds`.

---

### POST `/report`

## **설명**

선제 대응 리포트 JSON. 기획안 S7 미리보기가 이걸 그린다. 구성 5+1 절은 위 "구성" 참조.

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
  "Content-Type": "application/json"
}
```

**Body**

```json
{
  "bl": { "bl_no": "HG290309", "consignee": "DHHJ FRANCHISING CO., LTD." },
  "lc": { "lc_no": "LC20260001", "documents_required": "COMMERCIAL INVOICE, PACKING LIST" },
  "as_of": "2026-06-10T00:00:00",
  "submitted_documents": ["BILL OF LADING", "COMMERCIAL INVOICE"]
}
```

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `bl` | object | **Y** | [f3-defect-prediction.md](f3-defect-prediction.md) `/verify` 와 동일 |
| `lc` | object | N | 동일 |
| `as_of` | datetime | N | 동일. 제출 기한 계산의 기준 시각이기도 하다 |
| `submitted_documents` | array\<string> | N | 실제 제출한 서류명. **L/C 46A 와 대조해 누락을 찾는다** |

## **Response**

**Success (200)**

```json
{
  "bl_no": "HG290309",
  "lc_no": "LC20260001",
  "generated_at": "2026-06-10",
  "summary": {
    "defect_probability": 1.0,
    "risk_level": "높음",
    "counts": { "critical": 6, "warning": 1, "info": 0 },
    "model": "rules-v1",
    "headline": "제출 전 정정이 필요한 치명 하자 6건이 발견되었습니다.",
    "narrative": "선적항과 수하인이 신용장 지정과 다릅니다. ...",
    "narrative_source": "template"
  },
  "risks": [
    {
      "rule_id": "D003",
      "severity": "critical",
      "severity_label": "치명",
      "title": "선적항 불일치",
      "message": "선적항이 L/C 지정 항구와 다릅니다.",
      "source": "UCP 600 Art.20(a)(iii)",
      "fields": ["port_of_loading"],
      "observed": { "bl": "SHANGHAI, CHINA", "lc": "BUSAN" }
    }
  ],
  "checklist": [
    { "label": "요구 서류: COMMERCIAL INVOICE", "done": true, "detail": "" },
    { "label": "요구 서류: PACKING LIST", "done": false, "detail": "미제출" }
  ],
  "deadline": {
    "presentation_due": "2026-06-22",
    "expiry": "2026-06-30",
    "effective_due": "2026-06-22",
    "days_left": 12,
    "is_overdue": false,
    "basis": "선적일 + 21일 (UCP 600 Art.14(c))"
  },
  "recommendations": [
    {
      "order": 1,
      "severity_label": "치명",
      "action": "운송인에게 선적항 정정 B/L 을 요청하십시오.",
      "target_fields": ["port_of_loading"],
      "source": "UCP 600 Art.20(a)(iii)"
    }
  ],
  "outlook": {
    "verdict": "하자 통보 및 재제출 요구 예상",
    "detail": "치명 하자 6건이 남아 있어 은행이 지급을 보류할 가능성이 높습니다."
  },
  "unchecked": [
    {
      "rule_id": "D021",
      "title": "운임 표기 일치",
      "reason": "total_freight 가 비어 있어 판단할 수 없습니다."
    }
  ]
}
```

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `summary.risk_level` | string | `높음`(critical 있음) \| `보통`(warning 있음) \| `낮음` |
| `summary.narrative_source` | string | `template` \| `llm`. **LLM 호출이 실패해 템플릿으로 떨어져도 정확히 `template`** (위 "골격은 결정론, LLM 은 산문만" 절) |
| `deadline.effective_due` | date\|null | 제시기한과 유효기일 중 **이른 날** (위 "제출 기한 계산" 절) |
| `deadline.basis` | string | 어떻게 계산했는지 |
| `outlook` | object | 예상 심사 결과. **시나리오지 예언이 아니다** |
| `unchecked` | array | 검사하지 못한 항목. 기획안에 없지만 의도적으로 추가한 절이다 |

**Error**

```json
{
  "detail": "bl 필드가 비어 있습니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | `bl` 이 비었거나 입력 형 오류 |
| 422 | 스키마 불일치 |

---

### POST `/report/pdf`

## **설명**

리포트 PDF. 기획안 5.4 "PDF 내보내기". 요청 본문은 `/report` 와 완전히 동일하다.

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
  "Content-Type": "application/json"
}
```

**Body**

`POST /report` 와 동일.

## **Response**

**Success (200)**

PDF 바이너리.

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="BL_Copilot_Report_HG290309.pdf"
```

`bl_no` 가 없으면 파일명은 `BL_Copilot_Report_draft.pdf`.

**Error**

```json
{
  "detail": "bl 필드가 비어 있습니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | `bl` 이 비었거나 입력 형 오류 |
| 422 | 스키마 불일치 |

---

### POST `/report/share`

## **설명**

공유 링크 발급. 기획안 5절 "PDF 출력·공유 가능".

**저장하지 않는다.** 링크가 입력을 싣고 다니며, 열릴 때마다 서버가 같은 리포트를 다시 조립한다. 토큰은 `v1.<zlib+base64url(입력)>.<HMAC-SHA256>` 형식이고 전체 B/L + L/C 를 실어도 620자 안팎이다.

발급 시 한 번 조립해 본다. 열어 봐야 400 이 나는 링크를 쥐여주면 받는 쪽에서 터지고, 그때는 원인을 알 방법이 없다.

**한계 두 가지**

1. **토큰은 암호문이 아니다.** 서명은 위조를 막을 뿐 내용을 가리지 않는다. 링크를 가진 사람은 base64 를 풀어 B/L 원문을 읽을 수 있다 — **링크가 새면 서류가 샌다.** 완화책은 짧은 만료뿐이다.
2. **`REPORT_SHARE_SECRET` 미설정 시 프로세스마다 임시 키를 쓴다.** 재시작하면 발급한 링크가 전부 죽는다. 응답의 `ephemeral_secret` 과 `warning` 이 이 상태를 알린다.

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
  "Content-Type": "application/json"
}
```

**Body**

```json
{
  "bl": { "bl_no": "HG290309", "consignee": "DHHJ FRANCHISING CO., LTD." },
  "lc": { "lc_no": "LC20260001" },
  "as_of": "2026-06-10T00:00:00",
  "submitted_documents": ["BILL OF LADING"],
  "ttl_seconds": 604800
}
```

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `bl` | object | **Y** | `/report` 와 동일 |
| `lc` | object | N | `/report` 와 동일 |
| `as_of` | datetime | N | `/report` 와 동일 |
| `submitted_documents` | array\<string> | N | `/report` 와 동일 |
| `ttl_seconds` | int | N | 링크 유효기간(초). **최소 60, 최대 7776000(90일)**. 생략 시 7일 |

## **Response**

**Success (200)**

```json
{
  "token": "v1.eJyNkMFqwzAMhl_F6...Xg.7pQz3mKd1YrJ",
  "path": "/report/shared/v1.eJyNkMFqwzAMhl_F6...Xg.7pQz3mKd1YrJ",
  "pdf_path": "/report/shared/v1.eJyNkMFqwzAMhl_F6...Xg.7pQz3mKd1YrJ/pdf",
  "expires_at": "2026-06-17T00:00:00",
  "ephemeral_secret": false,
  "warning": null
}
```

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `token` | string | 공유 토큰 |
| `path` | string | 리포트 JSON 경로 |
| `pdf_path` | string | 리포트 PDF 경로 |
| `expires_at` | datetime | 만료 시각 |
| `ephemeral_secret` | bool | **`true` 면 서버 재시작 시 링크가 무효가 된다** |
| `warning` | string\|null | `ephemeral_secret` 이 `true` 일 때 안내 문구 |

**Error**

```json
{
  "detail": "공유 링크가 너무 깁니다 (7231 > 6000자). 서류 항목을 줄이거나 PDF 를 직접 내려받아 전달하세요."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | `bl` 이 비었거나 입력 형 오류 (발급 전 조립 실패) |
| 413 | 토큰이 `MAX_TOKEN_BYTES`(6000자) 초과 |
| 422 | `ttl_seconds` 가 60 미만 또는 7776000 초과 |

---

### GET `/report/shared/{token}`

## **설명**

공유된 리포트 JSON. 토큰에서 입력을 복원해 리포트를 다시 조립한다.

## **Request**

**Path Parameter**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `token` | string | `/report/share` 가 발급한 토큰 |

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

`POST /report` 와 동일한 리포트 구조.

**Error**

```json
{
  "detail": "공유 링크가 만료되었습니다. 새로 발급하세요."
}
```

| 코드 | 조건 | `detail` |
| --- | --- | --- |
| 404 | 형식 오류 | `토큰 형식이 올바르지 않습니다.` |
| 404 | 버전 불일치 | `지원하지 않는 토큰 버전입니다: <ver>` |
| 404 | 서명 위조 | `서명이 일치하지 않습니다.` |
| 404 | 본문 손상 | `토큰 본문을 해석할 수 없습니다.` |
| 410 | 만료 | **404 로 내면 받은 쪽이 '주소가 틀렸나'를 의심한다** |

---

### GET `/report/shared/{token}/pdf`

## **설명**

공유된 리포트 PDF. 링크를 클릭하면 브라우저에서 바로 열린다.

## **Request**

**Path Parameter**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `token` | string | `/report/share` 가 발급한 토큰 |

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

PDF 바이너리.

```
Content-Type: application/pdf
Content-Disposition: inline; filename="BL_Copilot_Report_HG290309.pdf"
```

`/report/pdf` 와 달리 **`inline`** 이다 — 공유 링크는 브라우저에서 바로 열려야 한다.

**Error**

`GET /report/shared/{token}` 과 동일 (404 / 410).

## 테스트

```bash
cd aiService && python -m pytest        # 164 passed
```

PDF 본문 검증에 PyMuPDF 를 쓴다. 파일이 생성됐는지만 보면 한글이 깨져도 통과하므로, 실제로 텍스트를 추출해 대조한다.

## 남은 것

- **LLM Narrator 구현** — 지금은 `TemplateNarrator` 만 있다. 인터페이스(`Narrator` Protocol)는 잡혀 있어 붙이기만 하면 된다. 폐쇄망 프로파일(기획안 3.1 ③)에서는 로컬 LLM 을 쓴다.
- **S7 화면 연동** — `report.to_dict()` 가 그 계약이다.
- **`verification_reports` 저장** — 스키마 확정 후. B파트 요청 시트에서 `file_path` 삭제·S3 전환이 이미 합의된 항목이다.

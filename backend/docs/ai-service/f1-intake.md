# F1 — 서류 인테이크·초안 작성

> 기획안 5절 F1: "이메일·엑셀·PDF 등 비정형 선적 서류를 자동 인식·추출하여 B/L 초안을 생성. 사용자는 확인·수정만 수행"

비정형 B/L 문서에서 필드를 추출하고, 사용자가 **확인·수정만 하면 되는 초안**을 만든다.
`aiService/ocr/` 에 있다.

## 파이프라인

```
이미지 ──[preprocessor]──> 정규화 이미지 ──[extractor]──┐
                                                        ├─> OCRResult ─[field_parser]─> BLFields ─[draft]─> BLDraft
라벨 JSON ─────────────────────────────[extractor]──────┘
```

| 모듈 | 역할 |
|---|---|
| `preprocessor.py` | 그레이스케일 → 노이즈 제거 → 이진화 → 기울기 보정 → 해상도 정규화 |
| `extractor.py` | PaddleOCR 3.6.0 추출 또는 라벨 JSON 로드 |
| `field_parser.py` | 좌표 구역 할당 → 필드별 규칙 추출 → 앵커 fallback |
| `draft.py` | 확인 필요 판정을 붙인 초안 생성 |
| `pipeline.py` | 위를 엮은 진입점 |

## 두 가지 입력 경로

`from_image` 가 운영 경로, `from_json` 이 라벨 로드 경로다.

`from_json` 을 유지하는 이유는 테스트다. PaddleOCR·PaddlePaddle 은 설치가 무겁고
플랫폼을 타는데, 파서와 하자 검증 로직은 그것과 무관하다. 라벨 JSON 경로가 있으면
OCR 엔진 없이 CI 에서 전 구간을 돌릴 수 있다.

```python
from ocr import IntakePipeline

draft = IntakePipeline().run_from_json("label.json")   # OCR 엔진 불필요
draft = IntakePipeline().run_from_image("scan.png")    # PaddleOCR 필요
```

## 필드 추출 방식

**1차 — 좌표 구역.** bbox 중심점을 13개 구역에 단독 할당한다.
좌표는 1654×2340 스캔본 실측 기준이며 이미지 크기에 비례 환산한다.

bbox 를 라인으로 먼저 묶지 않고 **개별 할당**하는 게 핵심이다. 선적항과 양하항은
같은 y 대의 좌우 컬럼이라, 라인 단위로 묶으면 한 줄이 되어 서로의 값을 오염시킨다.

**2차 — 키워드 앵커.** 구역 추출이 실패하면 필드 라벨(`PORT OF LOADING` 등)을 찾아
그 오른쪽/아래 텍스트를 수집한다. 비표준 서식 대응용이다.

## 신뢰도

기획안 S3(초안 편집기)가 "저신뢰 필드는 노란색 배경으로 표시해 사람 확인을 유도"를
요구한다. 어떤 필드가 불확실한지 모르면 전 필드를 검토하게 되어 F1 의 시간 단축
목표(8.1절, 70% 이상)가 무너진다.

값과 신뢰도는 **별도 맵**으로 담는다. `ocr_results` 테이블이 `structured_fields` 와
`field_confidence` 를 두 JSONB 컬럼으로 나눠 정의하고 있어 그 구조를 그대로 따랐다.
한 객체에 묶으면 저장할 때 다시 갈라야 하고, 하자 검증(F3)은 값만 필요한데 래퍼를
벗겨야 한다.

```python
fields.to_dict()          # → structured_fields 로 저장
fields.confidence_dict()  # → field_confidence 로 저장
```

**산출 방식**
- 필드 신뢰도 = 그 값에 기여한 bbox 들의 `rec_scores` 평균
- 앵커로 찾은 값은 여기에 `0.85` 를 곱한다 — OCR 이 확신해도 "라벨 오른쪽에 값이
  있다"는 레이아웃 가정이 틀릴 수 있어 구역 방식보다 불확실하다
- 값이 없으면 신뢰도를 **남기지 않는다**. '값 없음'과 '신뢰도 0'은 다르고,
  후자를 남기면 저신뢰 목록에 누락 필드가 섞인다

> PaddleOCR 3.x 는 `rec_scores` 를 돌려주는데 `ai_sample` 원본은 이 값을 버렸다.
> 이식하면서 살렸다.

## 초안

`BLDraft` 는 필드마다 **확인 필요 여부와 사유**를 붙인다.

| 사유 | 조건 |
|---|---|
| `missing_critical` | 핵심 필드인데 추출 실패 |
| `missing` | 그 외 필드 추출 실패 |
| `low_confidence` | 값은 있으나 신뢰도가 임계값(기본 0.80) 미만 |
| `anchor_derived` | 핵심 필드가 좌표가 아닌 라벨 근접으로 추정됨 |

`anchor_derived` 를 핵심 필드에만 거는 것은 의도적이다. 전 필드에 걸면 확인 큐가
불어나 F1 의 시간 단축 효과가 사라진다.

`is_ready_for_verification` 은 핵심 필드가 모두 찼는지 본다. 비어 있는 채로 F3 를
돌리면 결과가 '값이 없어서 하자'로만 도배되어 의미가 없다.

핵심 필드는 `bl_no` · `consignee` · `port_of_loading` · `port_of_discharge` · `date_of_issue` 다.

## 저장

파이프라인은 **저장하지 않는다.** 스키마 미확정 때문이 아니라 넣으면 안 되기
때문이다. 추출 로직이 저장소를 알게 되면 테스트에 DB 가 필요해지고, 스키마가 바뀔
때마다 추출 로직까지 흔들린다. 저장은 호출부(FastAPI 레이어)가 결과를 받아서 한다.

## API 명세

공통 규약(Base URL·에러 형식·상태 코드)은 [api-spec.md](api-spec.md) 를 먼저 볼 것.

F1 은 입력 5종에 엔드포인트 하나씩을 둔다. **응답은 5개가 모두 동일한 초안 구조**이므로 아래 "공통 응답"에 한 번만 적는다.

| 메서드 | 경로 | 입력 | OCR |
| --- | --- | --- | --- |
| POST | `/extract/label` | 라벨 JSON | 불필요 |
| POST | `/extract` | 이미지 | **필요** |
| POST | `/extract/pdf` | PDF | 텍스트 레이어면 불필요 |
| POST | `/extract/excel` | xlsx | 불필요 |
| POST | `/extract/email` | .eml | 첨부에 따라 |

---

### POST `/extract/label`

## **설명**

라벨 JSON(OCR bbox 목록)에서 B/L 초안을 만든다. **OCR 엔진 없이 파서만 태우는 경로**로 PaddleOCR 설치 없이 동작한다. CI·시연에서 쓴다.

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
  "Images": {
    "identifier": "HG290309",
    "width": 1654,
    "height": 2340
  },
  "bbox": [
    {
      "data": "HG290309",
      "x": [120, 340, 340, 120],
      "y": [210, 210, 250, 250],
      "confidence": 0.98
    }
  ]
}
```

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `Images` | object | N | 이미지 메타. 생략 시 `{}` |
| `bbox` | array | **Y** | OCR bbox 목록. 비면 400 |

## **Response**

**Success (200)**

아래 [공통 응답](#공통-응답--초안-구조) 참조. `source` 는 `json`.

**Error**

```json
{
  "detail": "bbox 가 비어 있습니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | `bbox` 가 비어 있음 |
| 422 | 스키마 불일치 |

---

### POST `/extract`

## **설명**

이미지 업로드에서 B/L 초안을 만든다. **PaddleOCR 이 필요하다.** 스캔 서류 운영 경로.

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
  "Content-Type": "multipart/form-data"
}
```

**Body**

`multipart/form-data`

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | file | **Y** | 이미지 파일. 확장자로 임시 파일명을 정하며 없으면 `.png` 로 본다 |

## **Response**

**Success (200)**

[공통 응답](#공통-응답--초안-구조) 참조. `source` 는 `image`.

**Error**

```json
{
  "detail": "빈 파일입니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | 빈 파일 |
| 503 | PaddleOCR 미설치 (`detail` 에 `pip install` 안내 포함) |

---

### POST `/extract/pdf`

## **설명**

PDF 에서 B/L 초안을 만든다.

**텍스트 레이어가 있는 PDF 는 OCR 을 타지 않는다.** 텍스트 줄이 10개 미만이면 스캔본으로 보고 200dpi 로 구워 OCR 에 넘긴다. 어느 경로였는지는 `source` 에 `pdf-text` / `pdf-ocr` 로 남는다. 위 "두 가지 입력 경로" 절 참조.

PDF 판정은 확장자가 아니라 `%PDF` 매직바이트로 한다.

## **Request**

**Path Parameter**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| 없음 | | |

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `page` | int | N | 읽을 페이지 (0-base). 기본 `0` |

**Header**

```json
{
  "Content-Type": "multipart/form-data"
}
```

**Body**

`multipart/form-data`

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | file | **Y** | PDF 파일 |

## **Response**

**Success (200)**

[공통 응답](#공통-응답--초안-구조) 참조. `source` 는 `pdf-text` 또는 `pdf-ocr`.

**Error**

```json
{
  "detail": "PDF 파일이 아닙니다. 이미지는 /extract 를 쓰세요."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | 빈 파일 / `%PDF` 아님 / 페이지 범위 초과 |
| 503 | PyMuPDF 미설치, 또는 스캔본인데 PaddleOCR 미설치 |

---

### POST `/extract/excel`

## **설명**

Excel(xlsx)에서 B/L 초안을 만든다. **OCR 을 타지 않는다.**

`sheet` 를 주지 않으면 **값이 가장 많은 시트**를 고른다. 첫 시트를 쓰면 표지·안내 시트가 앞에 있는 파일에서 빈 결과가 나온다.

xlsx 는 zip 컨테이너이므로 `PK` 매직바이트로 판정한다. 구형 `.xls`(OLE2)나 CSV 는 400 이다.

## **Request**

**Path Parameter**

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| 없음 | | |

**Query Parameter**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `sheet` | string | N | 시트명. 생략 시 값이 가장 많은 시트 |

**Header**

```json
{
  "Content-Type": "multipart/form-data"
}
```

**Body**

`multipart/form-data`

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | file | **Y** | xlsx 파일 |

## **Response**

**Success (200)**

[공통 응답](#공통-응답--초안-구조) 참조. `source` 는 `excel`.

**Error**

```json
{
  "detail": "xlsx 파일이 아닙니다. 구형 .xls 는 xlsx 로 변환해 주세요."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | 빈 파일 / `PK` 아님 / 없는 시트명 / 값이 없는 시트 |
| 503 | openpyxl 미설치 |

---

### POST `/extract/email`

## **설명**

이메일(`.eml`)에서 B/L 초안을 만든다.

**첨부를 먼저 본다.** 본문은 대개 안내문이고 첨부가 서류이므로, 본문부터 읽으면 선하증권 대신 인사말을 파싱한다. 지원 첨부가 없을 때만 본문을 읽는다.

`source` 가 어느 경로였는지 알린다 — 본문에서 뽑은 값과 첨부 원본에서 뽑은 값은 신뢰 수준이 다르다.

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
  "Content-Type": "multipart/form-data"
}
```

**Body**

`multipart/form-data`

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `file` | file | **Y** | `.eml` 파일 |

## **Response**

**Success (200)**

[공통 응답](#공통-응답--초안-구조) 참조. `source` 는 `email-pdf` / `email-excel` / `email-image` / `email-body`.

**Error**

```json
{
  "detail": "빈 파일입니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | 빈 파일 / 본문도 비었고 읽을 첨부도 없음 |
| 503 | 첨부가 스캔 이미지인데 PaddleOCR 미설치 등 |

---

### 공통 응답 — 초안 구조

위 5개 엔드포인트가 모두 이 구조를 반환한다. `BLDraft.to_dict()` 다.

```json
{
  "image_id": "HG290309",
  "form_type": "선하증권",
  "source": "json",
  "ocr_mean_confidence": 0.9421,
  "processing_time_ms": 12,
  "completeness": 0.8,
  "is_ready_for_verification": true,
  "review_required_count": 2,
  "fields": [
    {
      "name": "bl_no",
      "label": "B/L 번호",
      "value": "HG290309",
      "confidence": 0.98,
      "source": "region",
      "is_critical": true,
      "needs_review": false,
      "review_reason": null,
      "review_message": null
    },
    {
      "name": "voyage_no",
      "label": "항차",
      "value": null,
      "confidence": null,
      "source": null,
      "is_critical": false,
      "needs_review": true,
      "review_reason": "missing",
      "review_message": "추출하지 못했습니다. 원본을 확인해 주세요."
    }
  ]
}
```

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `form_type` | string | `선하증권` \| `상업송장` \| `포장명세서` \| `미상`. **종류가 달라도 응답 형태는 같다** |
| `source` | string | `json` \| `image` \| `pdf-text` \| `pdf-ocr` \| `excel` \| `email-pdf` \| `email-excel` \| `email-image` \| `email-body` |
| `completeness` | float | 값이 채워진 필드 비율 (0.0~1.0) |
| `is_ready_for_verification` | bool | 핵심 필드가 모두 찼는지. false 면 F3 결과가 '값 없음' 하자로 도배된다 |
| `review_required_count` | int | 사람 확인이 필요한 필드 수 |
| `fields[].source` | string\|null | `region`(좌표) \| `anchor`(항목명 근접) \| `llm` \| `null`(값 없음) |
| `fields[].review_reason` | string\|null | 아래 표 |

**`review_reason` 값** — 위 "신뢰도" 절이 각각의 판정 근거를 설명한다.

| 값 | 의미 |
| --- | --- |
| `missing_critical` | 핵심 필드인데 추출 실패 |
| `missing` | 그 외 필드 추출 실패 |
| `low_confidence` | 값은 있으나 OCR 신뢰도 미달 |
| `anchor_derived` | 좌표가 아닌 항목명 근접으로 추정 |
| `label_echoed` | 값에 서식의 항목명이 섞임 |
| `uncalibrated_layout` | 구역 좌표를 보정하지 않은 형식 (`pdf-text`/`excel`/`email-body`) |

**B/L 필드 15개** — `bl_no`, `shipper`, `consignee`, `notify_party`, `vessel`, `voyage_no`, `port_of_loading`, `port_of_discharge`, `description_of_goods`, `gross_weight`, `measurement`, `date_of_issue`, `place_of_issue`, `on_board_date`, `total_freight`

이 중 **핵심 필드 5개**(`is_critical: true`)는 위 "초안" 절에 적은 것과 같다.

## 테스트

```bash
cd aiService && python -m pytest        # 76 passed
```

실제 라벨 데이터셋은 저장소에 없으므로 구역 좌표에 맞춘 합성 라벨을 `conftest.py`
에서 만들어 쓴다. 어떤 값이 어느 구역에 있는지 테스트가 직접 통제하므로 실패했을
때 원인이 분명하다는 이점이 있다.

PaddleOCR 없이 전부 돈다.

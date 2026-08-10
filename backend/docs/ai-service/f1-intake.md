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

## 테스트

```bash
cd aiService && python -m pytest        # 76 passed
```

실제 라벨 데이터셋은 저장소에 없으므로 구역 좌표에 맞춘 합성 라벨을 `conftest.py`
에서 만들어 쓴다. 어떤 값이 어느 구역에 있는지 테스트가 직접 통제하므로 실패했을
때 원인이 분명하다는 이점이 있다.

PaddleOCR 없이 전부 돈다.

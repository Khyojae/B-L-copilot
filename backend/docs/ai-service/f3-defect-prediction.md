# F3 — 제출 전 하자 예측

> 기획안 5절 F3: "작성된 서류 세트를 L/C 조건(MT700 필드) 및 서류 간 정합성과 대조하여 하자 확률·위반 예상 조항(UCP600·ISBP)을 제출 전에 예측"
> **AI 기술: 룰엔진(조문 코드화) + XGBoost**

명세대로 두 축을 모두 만들었다. 6.1 아키텍처의 L4 공유 척추에도 '룰 카탈로그'가 구성요소로 잡혀 있다.

| 축 | 위치 | 답하는 질문 |
|---|---|---|
| 룰엔진 (결정론) | `aiService/ruleEngine/` | "어느 조문에 걸리는가" |
| XGBoost (확률) | `aiService/mlModel/` | "은행이 하자로 잡을 것 같은가" |

둘은 다른 질문이다. 룰을 통과해도 하자가 되는 건이 있고(추출 품질 문제), 룰에 걸려도 수리되는 건이 있다(컨테이너 환적, UCP 600 Art.20(c)).

## 성능

기획안 8.1 정량 목표는 **합성 검증셋 기준 F1 ≥ 0.85** 다.

```
$ PYTHONPATH=. python -m mlModel.evaluate --count 2000

학습 1400건 / 검증 600건

룰엔진 단독
  precision 0.9832  recall 0.8825  F1 0.9302  accuracy 0.9267

룰 + XGBoost
  precision 0.9702  recall 0.8825  F1 0.9243  accuracy 0.9200

  모델 기여도: F1 -0.0059

✅ 목표 달성  (최고 F1 0.9302)
```

**룰 단독과 결합을 나눠 보고한다.** 합쳐서 하나의 숫자만 내면 모델이 실제로 기여했는지, 룰이 다 한 건지 구분할 수 없다.

읽는 법: **현 최고 성능은 룰엔진 단독이고, 모델을 얹으면 F1 이 내려간다.** 부호가 음수인 이유와 그럼에도 모델을 두는 이유는 `remaining-work.md` 3.1 절에 있다 — 요약하면 하자 **판정**은 룰이 맡고, 모델은 룰이 침묵하는 구간을 가르는 위험도 **순위**(AUC 우세)를 맡는다.

### 하자 유형별 재현율

```
consignee_mismatch   1.000  ████████████████████
expired              1.000  ████████████████████
(주입 10개 유형 전부 1.000)
```

판정 기준은 본 지표와 같은 `has_critical` 이다. '위반이 하나라도 있으면 검출'로 느슨하게 잡으면 전 유형이 1.000이 되어 진단 도구 구실을 못 한다.

**이 1.000 은 합성 생성기가 주입하는 10개 유형에 한한 값이다.** 카탈로그의 나머지 룰 — 특히 8번에서 더한 고장 문언·예정 선박·항구 미특정·운임 조건 — 은 생성기가 만들지 않아 **재현율이 측정된 적이 없다.** 근거는 단위 테스트뿐이다 (`remaining-work.md` 5.8).

## 룰엔진

### 룰을 코드가 아닌 데이터로 둔다

"조문 코드화"의 요구다. `rules.yaml` 에 룰 29개(그중 ISBP 근거 8개)가 UCP600/ISBP 조문 근거와 함께 들어 있다. 서류 간 정합성 룰 10개는 입력 서명이 달라 `cross_rules.yaml` 로 나눠 두었다.

```yaml
- id: D002
  title: 선적기한 초과
  severity: critical
  weight: 0.40
  fields: [on_board_date, date_of_issue]
  check: date_not_after
  lc_field: latest_shipment_date
  source: UCP 600 Art.14(c) — 선적일이 신용장에 명시된 최종 선적기일을 경과해서는 안 된다.
  message: 선적일({bl})이 L/C 최종 선적기한({lc})을 넘었습니다.
  remedy: 사후 정정이 불가능한 하자입니다. L/C 조건변경(기한 연장)을 받아야 합니다.
```

이유 셋:
1. **조문을 화면·리포트가 인용해야 한다.** F7("모든 판정에 조문 근거를 인용한 자연어 설명")과 S4("항목별 조문 근거 펼침")가 `source` 를 그대로 출력한다. 코드에 하드코딩하면 리포트가 조문을 지어내게 된다.
2. `validation_rules` 테이블 시드로 그대로 옮겨간다.
3. 룰 추가·심각도 조정에 코드 변경이 필요 없다.

### 룰은 3상태다

```python
passed()         # 검사했고 문제없음
violated(...)    # 검사했고 위반
not_evaluated()  # 판단할 근거가 없음
```

세 번째가 핵심이다. 이항으로 만들면 L/C 조건이 없거나 날짜 파싱이 실패한 룰이 '통과'로 집계되어, **입력이 나쁠수록 하자가 적어 보이는 역전**이 생긴다. 하자 예측 시스템에서 이 역전은 치명적이다.

평가불가는 `Verdict.skipped` 에 사유와 함께 남아 리포트에 실린다. 검사하지 못한 항목을 침묵으로 넘기면 사용자는 '검사했고 문제없다'로 읽는다.

### 로드 시점에 카탈로그를 전수 검증한다

모르는 `check` 이름, 중복 `id`, 범위 밖 `weight` 를 실행 시점까지 끌고 가면 룰이 조용히 건너뛰어져 '하자 없음'으로 보고된다. **하자 검증 시스템에서 조용한 실패는 틀린 답보다 나쁘다.**

### 오탐 관리

기획안 9절이 '현실 대조 오탐'을 리스크로 들고 '심각도 보수적 산정'을 대응책으로 명시한다.

- **항구 이명 흡수** — BUSAN/PUSAN, INCHEON/INCHON 등. 표기 차이로 하자를 내면 오탐이다
- **법인격 표기 제거** — "CO., LTD." 유무로 불일치를 내면 오탐이 폭증한다
- **토큰 겹침 60% 기준** — 1.0이면 표기 흔들림에 다 걸리고, 낮추면 다른 항구가 통과한다
- **금지조건 기본값은 허용** — UCP 600 상 분할선적(Art.31(a))·환적(Art.20(c))은 신용장이 침묵하면 허용이다. 금지로 기본값을 잡으면 명시 없는 정상 건이 전부 하자가 된다
- **누락은 한 번만 센다** — `required` 룰이 잡으면 `match` 룰은 평가불가로 빠진다. 둘 다 세면 이중 계상된다

## 확률 축 (XGBoost 3.3.0)

### 피처에 룰 위반을 그대로 넣지 않는다

넣으면 모델이 룰을 베끼게 되고, 룰이 이미 잡은 것만 잡아 존재 이유가 없어진다. 대신 **룰이 못 보는 신호**를 넣는다.

- `skipped_ratio` — 무엇을 검사하지 **못했는지**. 룰은 여기서 침묵한다
- `mean_confidence` · `low_confidence_ratio` · `anchor_derived_ratio` — F1이 넘겨준 추출 품질
- `days_to_shipment_deadline` — 위반 전 단계의 위험
- `lc_condition_count` — 조건이 적은 L/C 는 '하자 없음'이 쉽게 나온다. 그 편향을 보정한다

실측 기여도에서 `field_missing_ratio`·`skipped_ratio` 가 실제로 쓰이는 게 확인된다.

기획안 3.1 ④ 피드백 플라이휠이 실전 라벨을 쌓으면, 이 피처로 "룰은 통과했지만 은행이 하자로 잡은" 케이스를 학습하게 된다.

### 합성 라벨에 의도적 잡음을 넣는다

기획안 9절이 리스크로 든 "실제 하자 라벨 데이터 부재 — 은행 심사 기록은 기밀로 확보 불가"에 대한 대응이다.

라벨은 "은행이 하자로 잡는가"이지 "룰이 걸리는가"가 아니다. 둘을 같게 만들면 라벨이 룰의 결정론적 함수가 되어 모델이 배울 게 없다. 그래서 두 종류의 잡음을 넣는다.

- **룰이 못 잡는 하자** — 서류는 멀쩡한데 추출 품질이 나빠 제시 단계에서 문제가 되는 건
- **룰은 잡지만 수리되는 건** — 환적 표시가 있어도 컨테이너 운송이면 UCP 600 Art.20(c)로 수리된다

테스트가 이 잡음의 존재를 검사한다 (`test_라벨이_룰_결과와_완전히_같지는_않다`).

### 모델이 없으면 룰 가중치로 대체한다

학습 전에도 파이프라인 전체가 돌아야 한다. 어느 쪽으로 산출했는지는 `Verdict.model` / `Prediction.model` 에 남는다 (`rules-v1` vs `xgboost-v1`).

화면이 룰 가중치 합산을 학습된 모델의 확률로 표기하면 안 되기 때문이다.

### 피처 순서를 모델과 함께 저장한다

순서가 어긋나면 XGBoost 는 **조용히 틀린 답을 낸다.** `.meta.json` 에 같이 저장하고 로드 시 대조해서, 다르면 로드를 거부한다.

## 입력 형태

`BLFields` 와 `dict` 를 모두 받는다. F1 파이프라인은 객체를 주지만, S3 편집기에서 사람이 고친 값과 API 요청 본문은 dict 로 온다.

`getattr` 하나로 처리하면 dict 가 들어왔을 때 전 필드가 `None` 이 되고, 그 결과는 예외가 아니라 **'전 필드 누락'이라는 틀린 검증 결과**로 나온다. 정상 서류에 없는 하자가 날조되므로 알 수 없는 형태는 조용히 넘기지 않고 바로 터뜨린다.

형 검증은 룰 루프 **앞에서** 한다. 루프 안에서 터지면 룰별 예외 처리에 흡수되어 카탈로그 전건이 '평가불가'가 되는데, 그 결과는 위반 0건이라 얼핏 '하자 없음'으로 읽힌다.

## 사용

```python
from ruleEngine import RuleEngine, LCTerms
from mlModel import DefectPredictor

engine = RuleEngine()
lc = LCTerms.from_tags({"44E": "BUSAN", "44C": "2026-06-30"}, lc_no="LC-001")

verdict = engine.verify(bl_fields, lc, as_of=datetime.now())
prediction = DefectPredictor().predict(bl_fields, lc, verdict)

print(verdict.counts)              # {'critical': 2, 'warning': 1, 'info': 0}
print(prediction.probability)      # 0.87
print(prediction.model)            # 'xgboost-v1' 또는 'rules-v1'
for v in verdict.sorted_violations():
    print(v.rule_id, v.source, v.remedy)
```

`as_of` 는 제시기간 계산의 기준 시각이다. 주입하지 않으면 테스트가 실행 날짜에 따라 흔들린다.

## API 명세

공통 규약(Base URL·에러 형식·상태 코드)은 [api-spec.md](api-spec.md) 를 먼저 볼 것.

| 메서드 | 경로 | 기능 |
| --- | --- | --- |
| GET | `/rules` | 룰 카탈로그 조회 |
| POST | `/verify` | 하자 검증 |

---

### GET `/rules`

## **설명**

적재된 룰 카탈로그 목록. S11 설정 화면과 발표 시연에서 쓴다.

`unverified_source_count` 는 **조문 인용이 실무 검증을 거치지 않은 룰 수**다. 화면이 이 값을 숨기면 미검증 조문이 검증된 것처럼 인용된다.

카탈로그는 기동 시 1회만 읽는다(위 "로드 시점에 카탈로그를 전수 검증한다" 절).

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
  "count": 29,
  "unverified_source_count": 3,
  "rules": [
    {
      "id": "D003",
      "title": "선적항 불일치",
      "severity": "critical",
      "source": "UCP 600 Art.20(a)(ii)",
      "source_verified": true,
      "check": "lc_match"
    }
  ]
}
```

`severity` — `critical`(치명) | `warning`(경고) | `info`(참고)

**Error**

없음.

---

### POST `/verify`

## **설명**

하자 검증. 기획안 S4(검증 결과) 화면이 이 응답을 그대로 그린다.

`bl` 은 F1 이 뽑은 값이든 S3 편집기에서 사람이 고친 값이든 **같은 형태로 받는다**(위 "입력 형태" 절). 두 경로를 가르면 '편집 후 재검증'이 다른 코드 경로를 탄다.

**판정은 `verdict`(룰), 위험도 순위는 `prediction`(모델)** 이 담당한다. 이진 판정은 룰이, 순위는 모델이 낫다는 측정 결과에 따른 분리다(위 "성능" 절).

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
  "bl": {
    "bl_no": "HG290309",
    "shipper": "HANJIN SHIPPING CO., LTD.",
    "consignee": "DHHJ FRANCHISING CO., LTD.",
    "port_of_loading": "BUSAN, KOREA",
    "port_of_discharge": "LOS ANGELES, USA",
    "description_of_goods": "SPARE PARTS",
    "date_of_issue": "2026-06-10",
    "on_board_date": "2026-06-08"
  },
  "lc": {
    "lc_no": "LC20260001",
    "expiry_date": "2026-06-30",
    "latest_shipment_date": "2026-06-15",
    "port_of_loading": "BUSAN",
    "port_of_discharge": "LOS ANGELES",
    "description_of_goods": "SPARE PARTS",
    "documents_required": "COMMERCIAL INVOICE, PACKING LIST",
    "partial_shipment": "PROHIBITED",
    "transhipment": "ALLOWED"
  },
  "as_of": "2026-06-10T00:00:00"
}
```

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `bl` | object | **Y** | B/L 필드. 필드명은 [f1-intake.md](f1-intake.md) 의 15개. 비면 400 |
| `lc` | object | N | 신용장 조건(MT700). 생략 시 **서류 내부 정합성만** 검사 |
| `as_of` | datetime | N | 제시기간 계산 기준 시각. 생략 시 현재 시각. **테스트·시연에서는 넣어야 결과가 고정된다** |

**`lc` 는 MT700 태그명 대신 내부 필드명을 쓴다** (`MT700_TAGS`)

| MT700 | 필드명 |
| --- | --- |
| 31D | `expiry_date` |
| 32B | `currency_amount` |
| 39A | `tolerance_pct` |
| 43P | `partial_shipment` (`ALLOWED` \| `PROHIBITED`) |
| 43T | `transhipment` (`ALLOWED` \| `PROHIBITED`) |
| 44C | `latest_shipment_date` |
| 44E | `port_of_loading` |
| 44F | `port_of_discharge` |
| 45A | `description_of_goods` |
| 46A | `documents_required` |
| 50 | `applicant` |

모르는 키는 조용히 버린다.

## **Response**

**Success (200)**

```json
{
  "shipment_id": "HG290309",
  "verdict": {
    "model": "rules-v1",
    "defect_probability": 1.0,
    "evaluated_count": 18,
    "skipped_count": 3,
    "counts": { "critical": 6, "warning": 1, "info": 0 },
    "has_critical": true,
    "violations": [
      {
        "rule_id": "D003",
        "severity": "critical",
        "severity_label": "치명",
        "title": "선적항 불일치",
        "message": "선적항이 L/C 지정 항구와 다릅니다.",
        "fields": ["port_of_loading"],
        "source": "UCP 600 Art.20(a)(ii)",
        "remedy": "운송인에게 정정 B/L 을 요청하십시오.",
        "observed": { "bl": "SHANGHAI, CHINA", "lc": "BUSAN" }
      }
    ],
    "skipped": [
      {
        "rule_id": "D021",
        "title": "운임 표기 일치",
        "reason": "total_freight 가 비어 있어 판단할 수 없습니다."
      }
    ]
  },
  "prediction": {
    "probability": 0.8734,
    "model": "xgboost-v1",
    "is_defect": true,
    "threshold": 0.5
  }
}
```

| 이름 | 타입 | 설명 |
| --- | --- | --- |
| `shipment_id` | string\|null | `bl.bl_no` 를 그대로 반환 |
| `verdict.model` | string | 확률 산출 주체. `rules-v1` = 룰 가중치 합산 |
| `verdict.defect_probability` | float | 룰 가중치 합을 1.0 에서 자른 값. **확률보다 위험 점수에 가깝다** — `model` 을 함께 읽을 것 |
| `verdict.skipped` | array | **평가하지 못한 룰**(3상태 중 `not_evaluated`). 화면에서 감추면 사용자가 '검사했고 문제없다'로 읽는다 |
| `verdict.violations` | array | 심각도 내림차순 → 가중치 내림차순 정렬 |
| `prediction.model` | string | `xgboost-v1`, 또는 모델 미적재·예측 실패 시 `rules-v1` |

> **`prediction.model` 이 `rules-v1` 이면 학습된 모델이 아니라 룰 가중치다**(위 "모델이 없으면 룰 가중치로 대체한다" 절). 예측이 실패해도 검증 결과는 돌려주도록 설계돼 있어 200 으로 나간다. 화면에서 이걸 학습 모델의 확률로 표기하면 안 된다.

**Error**

```json
{
  "detail": "bl 필드가 비어 있습니다."
}
```

| 코드 | 조건 |
| --- | --- |
| 400 | `bl` 이 비었거나 입력 형 오류 |
| 422 | `bl` 키 자체가 없음 |

## 테스트

```bash
cd aiService && python -m pytest        # 359 passed, 1 skipped
```

XGBoost 미설치 시 모델 테스트는 자동으로 건너뛴다(`importorskip`). 룰엔진은 PyYAML 만 있으면 돈다.

## 남은 것

- **심각도 어휘 정합화** — 여기서는 기획안 S4 의 `critical/warning/info` 를 쓴다. B파트 워크북의 `verification_rules.severity` 는 `critical/major/minor` 로 적혀 있다. 기획안(2026-08-06)이 워크북(2026-07-17)보다 최신이고 화면 계약이라 이쪽을 택했다. 스키마 freeze 시 맞춰야 한다.
- **룰 카탈로그 → `validation_rules` 시드** — 스키마 확정 후
- **`weight` 재조정** — 지금은 실무 감각으로 잡은 값이다. 실전 라벨이 쌓이면 데이터로 정해야 한다
- **신규 룰의 재현율 미측정** — 합성 생성기(`synth.py` `DEFECT_KINDS`)가 고장 문언·예정 선박·항구 미특정·운임 조건을 주입하지 않아 이 4종은 평가셋에서 한 번도 발화하지 않는다. 주입 유형을 늘리면 잴 수 있으나 기존 수치가 전부 이동한다 (`remaining-work.md` 5.8)
- **모델 artifact 와 룰 카탈로그의 동기** — `meta.json` 은 피처 **순서**만 대조한다. 룰이 늘면 `evaluated_count`·`skipped_ratio` 분포가 바뀌는데 로드는 그대로 성공하므로, 재학습을 잊으면 값만 조용히 낡는다. 카탈로그 지문을 함께 저장하는 것이 근본 대응이다
- ~~**서류 간 정합성**~~ — 완료. `cross_rules.yaml` 10건 (B/L ↔ Invoice ↔ Packing List ↔ L/C)

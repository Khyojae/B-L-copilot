# 저장 계층 근거 강제 — 기술 A 에게 넘기는 계약

ACK 2026 논문(저장 계층의 근거 강제를 통한 문서 AI 추출값의 환각 억제)의 기술 B 산출물.
A 는 이 문서에 적힌 파일 형식·스위치·뷰만 쓰고, 트리거 내부 함수는 부르지 않는다
(작업분배 §04 "파일로만", §06 "하지 말 것").

정본 DDL: `migrations/sql/evidence/10_evidence_enforcement.sql` (리비전 `0003_evidence_enforcement`).

```bash
docker compose up -d && uv run alembic upgrade head
uv run python scripts/load_evidence_glossary.py     # B2 — 없으면 E3 = E2
uv run pytest tests/test_evidence_trigger.py tests/test_ungrounded_quarantine.py \
              tests/test_manual_actor_required.py tests/test_evidence_modes.py -q
```

> Windows + Docker Desktop 에서 `DATABASE_URL` 의 `localhost` 가 IPv6 로 먼저 붙으려다
> 접속당 수십 초를 기다린다. `.env` 에서 `127.0.0.1` 로 두면 테스트 48건이 4분 → 25초.

## 1. A → B : `tokens.jsonl` → `document_token`

한 줄 = 토큰 하나. A2 어댑터가 기존 OCR(`aiService/ocr`) 의 `BBox` 를 이 모양으로 바꾼다.

```json
{"document_id": "<uuid>", "page": 1, "idx": 0, "text": "BUSAN,", "bbox": [0.05, 0.13, 0.11, 0.15], "ocr_confidence": 0.97}
```

| 키 | 컬럼 | 규칙 |
|---|---|---|
| `document_id` | `document_token.document_id` | `document` 행이 먼저 있어야 한다 (FK, ON DELETE CASCADE) |
| `page` | `page` | 1부터 |
| `idx` | `idx` | 페이지 안 읽기 순서 (`center_y`, `x_min`). **0부터 연속** — 역추적 창이 연속성을 전제한다 |
| `text` | `text` | OCR 이 읽은 그대로. 라벨 텍스트를 넣지 않는다(오라클 오염) |
| `bbox` | `bbox_x1..y2` | 이미지 너비/높이 대비 0~1 비율, `x1<x2`, `y1<y2` |
| `ocr_confidence` | `ocr_confidence` | 0~1, 없으면 생략 |

`norm_text` 는 넣지 않는다 — DB 트리거가 `evidence_norm(text)` 로 채우고, 넣어도 덮어쓴다.

```sql
INSERT INTO document_token (document_id, page, idx, text, bbox_x1, bbox_y1, bbox_x2, bbox_y2, ocr_confidence)
VALUES (:document_id, :page, :idx, :text, :x1, :y1, :x2, :y2, :conf);
```

## 2. A → B : `fields.jsonl` → `field_value`

한 줄 = 필드값 후보 하나. 실험기(A6)는 이걸 모드마다 INSERT 한다.

```json
{"document_id": "<uuid>", "field_code": "BL.PORT_OF_LOADING", "value": "KRPUS",
 "source_layer": "LLM", "page": null, "span": null, "bbox": null, "confidence": 0.81}
```

| 키 | 컬럼 | 규칙 |
|---|---|---|
| `field_code` | `field_code` | `field_definition.code` (`BL.*`, 09_seed_catalog.sql) |
| `value` | `value` | 추출값 원문. `null` 이면 `grade='NOT_FOUND'` 로 넣는다 |
| `source_layer` | `source_layer` | `REGION` · `ANCHOR` · `LLM`. 지표를 계층별로 나눌 때 쓴다 |
| `page` + `span` `[from, to)` | `page`, `evidence_token_from/to` | 파서가 값을 뽑은 토큰 범위(half-open). LLM 값은 보통 `null` |
| `bbox` | `bbox_x1..y2` | 스팬이 없고 bbox 만 있으면 트리거가 중심점 포함 토큰으로 스팬을 도출한다 |
| — | `extractor` | 자동값은 `OCR_LLM` (또는 `RULE`). `MANUAL`·`JSON` 은 면제 경로라 실험에 넣지 않는다 |
| — | `grade` | 파서가 준 등급 그대로. 격리되면 트리거가 `REVIEW_REQUIRED` 로 덮는다 |
| — | `is_representative` | 한 선적·한 필드에 `true` 는 하나뿐 (`field_value_representative_uk`) |

```sql
INSERT INTO field_value (tenant_id, shipment_id, field_code, document_id, page,
                         value, grade, extractor, source_layer,
                         evidence_token_from, evidence_token_to,
                         bbox_x1, bbox_y1, bbox_x2, bbox_y2, is_representative)
VALUES (...)
RETURNING id, evidence_status, derivation, evidence_mode, evidence_reason,
          grade, page, evidence_token_from, evidence_token_to;
```

`evidence_status` · `derivation` · `evidence_mode` · `evidence_reason` 는 넣어도 트리거가 덮어쓴다.

## 3. B → A : 모드 스위치

```sql
SELECT set_evidence_mode('E2');                 -- P · E1 · E2 · E3
SELECT set_evidence_reattach_threshold(0.85);   -- θ (A5 가 검수 100건으로 정한 값). 기본 0.800
SELECT current_evidence_mode();
```

단일 행 `evidence_enforcement_config`. 트리거가 매 행마다 읽고, 판정에 쓴 모드를
`field_value.evidence_mode` 에 남긴다 — 어느 조건에서 나온 행인지 결과에서 바로 구분된다.

| 모드 | 검사하는 명제 | 통과 조건 |
|---|---|---|
| `P` | 없음 | 전부. `evidence_status` = NULL |
| `E1` | 근거 좌표가 존재한다 | `document_id`·`page` 와 (`bbox` 또는 스팬) 이 있다 → `GROUNDED/NONE` |
| `E2` | 스팬 텍스트가 값을 문자열 수준에서 뒷받침한다 | `EXACT` · `SUBSTRING` |
| `E3` | E2 + 선언된 파생 규칙 | + `FORMAT`(날짜·수량, `evidence_format_rule`) · `GLOSSARY`(`glossary_alias`) · `SIMILARITY`(trigram ≥ θ) |

E2·E3 는 스팬이 없으면 §4.6 역추적을 한다: `word_similarity` 상위 N 토큰을 시작점으로
1~(단어수+1) 토큰 창을 만들어 `similarity ≥ θ` 인 최적 창을 스팬으로 결속한다. 못 찾으면 격리.

수치·날짜 타입(`field_definition.data_type`)은 `SUBSTRING` 을 인정하지 않는다 ("12" ⊂ "1234").

## 4. 결과 읽기

```sql
-- 기계 경로 (룰 엔진·리포트·재학습) — UNGROUNDED 가 나오지 않는다
SELECT * FROM field_value_trusted WHERE shipment_id = :s;
-- 사람 경로 — 격리값은 대표값 자격을 유지하므로 여기 남는다
SELECT * FROM field_value_review_queue WHERE shipment_id = :s;
```

지표 계산에 쓰는 컬럼:

| 컬럼 | 값 |
|---|---|
| `evidence_status` | `GROUNDED` · `DERIVED` · `UNGROUNDED` · NULL(P 모드 또는 면제) |
| `derivation` | `EXACT` · `SUBSTRING` · `FORMAT` · `GLOSSARY` · `SIMILARITY` · `NONE` |
| `evidence_mode` | 판정 당시 모드 |
| `evidence_reason` | 아래 코드 |
| `grade` | 격리되면 `REVIEW_REQUIRED` |

`evidence_reason` 코드:

| 코드 | 뜻 |
|---|---|
| `CONTENT_MISMATCH` | 스팬은 실재하지만 값을 뒷받침하지 않는다 (fabricated citation · 환각) |
| `SPAN_NOT_FOUND` | 스팬이 가리키는 토큰이 없다 (좌표 날조) |
| `NO_EVIDENCE_SPAN best_sim=…` | 역추적 실패 — 원문 어디에도 비슷한 글자가 없다 (환각 후보) |
| `NO_COORDS` | E1: 좌표 없음 |
| `NO_TOKEN_LAYER` | 그 서류의 토큰이 적재되지 않았다 — 실험 설정 오류로 봐야 한다 |
| `NO_DOCUMENT` · `NO_PAGE` · `NO_VALUE` · `EMPTY_VALUE` | 입력 결손 |
| `COORDS_PRESENT` | E1 통과 |
| `REATTACHED sim=…` | 통과 비고: 역추적으로 스팬을 되찾았다 |
| `SPAN_FROM_BBOX` | 통과 비고: bbox 기하로 스팬을 도출했다 |
| `EXEMPT_MANUAL` · `EXEMPT_JSON` · `NOT_FOUND` | 면제 (검사하지 않음, `evidence_status` NULL) |

## 5. 면제 조항 봉인 (§4.5)

`field_value_manual_actor_ck`: `extractor = 'MANUAL'` 이면 `edited_by`(app_user) 가 있어야 한다.
모드와 무관한 무결성 제약이라 P 모드에서도 걸린다. 자동 경로가 좌표 없다고 "수동 입력"을
참칭하는 길을 막는다.

## 6. 트리거 비용 (참고, 표 3 은 A 가 잰다)

500 토큰 문서, 단일 노드, 200행 INSERT 기준 행당: 명시 스팬 EXACT ≈ 2 ms · 역추적 ≈ 9 ms ·
P 모드 ≈ 0.2 ms. `document_token` 은 PK(document_id, page, idx) 로 서류 단위 조회,
`norm_text` 에 trigram GIN.

## 7. 알려진 한계 (6절에 쓸 것)

- `E3` 는 "값이 스팬 어딘가에 실재함"만 보장한다. 스팬이 그 필드의 자리라는 보장은 없다 —
  파서가 넘긴 스팬이 다른 칸이면 같은 문자열로도 통과한다(필드–영역 정합 미보장).
- 오라클이 OCR 품질에 의존한다. OCR 이 놓친 글자는 `NO_EVIDENCE_SPAN` 으로 격리된다(FQR 하한).
- 격리값의 대체 후보 자동 승격은 없다. 사람이 검토 큐에서 고른다.
- 규칙표(`evidence_format_rule`)와 용어사전(`std-2026.1`)은 결과를 본 뒤 바꾸지 않는다.

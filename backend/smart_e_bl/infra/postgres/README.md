# B/L Copilot 데이터 스키마

`docs/BL_Copilot_기획안_v2.docx` 를 근거로 한 PostgreSQL 18 스키마입니다.

**구현 범위: F1 서류 인테이크 · F2 표준 용어 교정 · F3 하자 예측 · F4 리포트**
F5 정정 영향분석 · F6 현실 대조 · 피드백 플라이휠은 이번 범위에서 제외했습니다
(아래 "제외한 것" 참고).

테이블 21 · 열거형 12 · 인덱스 66 · CHECK 제약 32 · FK 54

## 파일 구성

DDL 은 `migrations/sql/` 에 있고, Alembic 의 `0001_baseline` 리비전이 파일명 순서대로
실행합니다. 적용은 아래 "적용 방법" 절 참고.

| 파일 | 담는 것 | 기능 | 기획안 |
|---|---|---|---|
| `01_extensions_and_types.sql` | 확장, 열거형 12종, 공통 트리거 | 공통 | 5.8 |
| `02_tenancy_and_shipment.sql` | `tenant` `app_user` `shipment` `shipment_status_history` | 공통 | 6.1, 5.8 |
| `03_documents_and_fields.sql` | `ingest_job` `document` `field_definition` `field_value` | **F1** | 5.1 |
| `04_glossary.sql` | `glossary_term` `glossary_alias` `normalization_suggestion` | **F2** | 5.2 |
| `05_rules.sql` | `rule_catalog_version` `rule` | **F3** 계층 A | 5.3 |
| `06_verdicts_and_predictions.sql` | `verdict` `verdict_evidence` `verdict_disposition` `model_version` `defect_prediction` `prediction_factor` | **F3** | 5.3 |
| `07_reports.sql` | `report` | **F4** | 5.4 |
| `08_audit.sql` | `audit_log` | 공통 | 5.8 |
| `09_seed_catalog.sql` | 필드 정의 45 · 룰 20 | — | 5.1, 5.3 |
| `evidence/10_evidence_enforcement.sql` | `document_token` · `field_value` 근거 컬럼 · 검증 트리거 `fn_field_value_enforce_evidence` · 뷰 `field_value_trusted`/`field_value_review_queue` · 모드 스위치 `evidence_enforcement_config` · 규칙표 `evidence_format_rule` | 논문 프로토타입 (리비전 `0003`) | [docs/evidence_harness.md](../../docs/evidence_harness.md) |
| `catalog/11_invoice_packing_fields.sql` | 상업송장 6 · 포장명세서 6 필드 정의 추가 — aiService 추출 필드·서류 간 룰(`cross_rules.yaml`)이 쓰는 코드. `mapping.DB_FIELD_CODE_TO_AI` 와 1:1 | **F1·F3** (리비전 `0004`) | 5.1, 5.3 |

`evidence/` · `catalog/` 하위는 baseline 이 아니라 각각 `0003_evidence_enforcement` · `0004_invoice_packing_fields` 리비전이 실행합니다.
이 리비전은 `field_value_evidence_required_ck`(좌표 존재 CHECK)를 트리거의 E1 모드로
대체하고, 위반 시 거부 대신 격리(`UNGROUNDED` + `REVIEW_REQUIRED`)합니다. 기본 모드는
E3(내용 일치 + 선언된 파생) 라 운영 경로의 보장은 이전보다 강합니다. 기계 소비 경로는
`field_value` 대신 `field_value_trusted` 를 읽어야 합니다.

## 설계 판단

### 명세의 규칙을 애플리케이션이 아니라 제약으로 옮겼다

기획안이 "~하지 않는다"로 못박은 규칙 중 데이터 형태로 표현 가능한 것은 DB 제약으로
내렸습니다. 코드 경로가 늘어나도 규칙이 새지 않습니다.

| 기획안 문장 | 구현 |
|---|---|
| 5.1 "원문 근거 좌표가 없는 값은 저장하지 않는다(추정 생성 금지)" | `field_value_evidence_required_ck` — 자동 추출 값은 `document_id`·`page`·`bbox` 필수 |
| 5.1 "임의 추정값 표시 금지" | `field_value_not_found_ck` — 미검출 등급은 값을 가질 수 없음 |
| 5.1 "대표값을 정하되 후보를 폐기하지 않는다" | `field_value_representative_uk` 부분 유니크 — 대표는 1개, 후보는 무제한 |
| 5.2 "표준 사전(읽기 전용) → 조직 사전 → 선적 예외" | `glossary_term_scope_owner_ck` — 계층별 소유자 강제 |
| 5.2 "거절 시 사유를 기록한다" | `normalization_suggestion_reject_ck` |
| 5.2 "판별 불가 시 후보를 나열해 사용자에게 선택시킨다(임의 선택 금지)" | `normalization_suggestion.candidates` jsonb (상위 5건) + `chosen_term_id` |
| 5.1 "한 파일에 여러 서류가 섞인 경우 페이지 단위로 분할·재분류" | `document.source_page_from/to` + 중복 검출 키에 구간 포함 |
| 5.3 "모든 룰 위반 항목의 조문 근거 표시율 100%" | `verdict_evidence` + `verdict_evidence_target_ck` |
| 5.4 "서류가 수정되어도 과거 리포트는 변경되지 않는다" | `report_immutable` 트리거 — 스냅샷 UPDATE 거부, PDF 경로만 허용 |
| 5.8 "강제 진행 사유는 리포트와 피드백 데이터에 남는다" | `shipment_status_force_reason_ck` |

### 룰은 코드가 아니라 데이터

기획안 5.3 "룰은 코드가 아니라 데이터로 관리하여 조문 개정 시 배포 없이 갱신한다" 를
`rule` 테이블로 구현했습니다. 판정식(`expression`)·메시지 템플릿·심각도·활성 여부가
모두 행 데이터입니다.

### 판정 재현성

`verdict` · `defect_prediction` · `report` 는 모두 `rule_catalog_version` ·
`model_version` · `glossary_version` 을 함께 저장합니다(기획안 5.8). 조문이 개정되어도
과거 판정을 당시 기준으로 재현할 수 있습니다.

### PostgreSQL 18 을 쓴 이유

기본 키는 PG18 에서 새로 들어온 `uuidv7()` 입니다. 시간순 정렬 UUID 라 B-tree 삽입이
말단에 집중되어, `uuidv4` 대비 인덱스 단편화가 적습니다.

## 제외한 것

| 기능 | 제외한 테이블 | 다시 넣을 때 드는 비용 |
|---|---|---|
| F5 정정 영향분석 | `field_constraint` `correction` `correction_field_change` `correction_impact_item` | **추가만** — 기존 테이블 변경 없음. 그래프 노드는 이미 `field_definition` 이 갖고 있음 |
| F6 현실 대조 | `conflict_rule` `reality_event` `adapter_connection` `shipment_link` `normal_practice_whitelist` | `verdict` 에 `origin`·`conflict_rule_id` 컬럼 추가, `verdict_evidence.evidence_side` 에 `REALITY_SIDE` 허용, `rule_id` NOT NULL 완화 필요 |
| 피드백 플라이휠 | `outcome` | **추가만** — `defect_prediction` 을 참조하면 됨 |

F6 만 기존 테이블 변경을 동반합니다. 기획안 5.8 이 `verdict` 를 F3·F6 공용 객체로
정의하기 때문인데, 이번 범위에서는 룰엔진 판정만 있으므로 `rule_id` 를 NOT NULL 로 두고
`origin` 컬럼을 없앴습니다. 나중에 F6 을 넣을 때 마이그레이션 3줄이면 되돌릴 수 있습니다.

`shipment_status` 열거형에는 `MONITORING`·`CLOSED` 를 남겨 두었습니다. F6·플라이휠
소관 상태지만, 상태 컬럼 하나로 선적의 전 생애를 표현해야 하기 때문입니다.
`shipment.cargo_control_no` 도 F1 의 식별번호 필드라 그대로 있습니다.

## 채워야 하는 것

**룰 조문 원문(`rule.authority_snippet`)이 비어 있습니다.** 현재 `(조문 원문 미적재)`
플레이스홀더가 20건 들어가 있습니다. UCP600·ISBP 는 ICC 저작물이라 원문을 임의로 채워 넣지
않았습니다. 기획안 5.4 는 F4 리포트 ②항목별 리스크가 "근거 조문 원문"을 포함해야 한다고
규정하므로, **ICC 라이선스를 확보해 이 컬럼을 채워야 리포트가 명세대로 성립합니다.**

`rule.expression` 의 판정식도 기획안 5.3 이 제시한 DSL 형태의 초안이며, F3 구현 시 실제
평가기와 함께 확정해야 합니다.

용어사전(`glossary_term`·`glossary_alias`)은 비어 있습니다. 기획안 10.1 의 이번 기간
목표는 별칭 300건입니다. UN/LOCODE·UN/ECE Rec 20 은 공개 데이터라 적재 스크립트로 채울 수
있습니다.

## 알려진 제약

**baseline 리비전(`migrations/sql/`)은 직접 수정하지 마세요.** 이미 적용된 DB 에는
반영되지 않습니다. 스키마 변경은 새 리비전으로 쌓아야 합니다
(`uv run alembic revision -m "..."`).

**테넌트 격리는 애플리케이션 책임입니다.** 모든 테넌트 스코프 테이블에 `tenant_id` 를
두었을 뿐 DB 차원의 강제는 없습니다. Row-Level Security 로 내리는 방안은 별도 검토가
필요합니다.

**`tenant_id` 단독 인덱스가 없는 테이블이 있습니다** (`document`·`field_value`·`verdict`·
`report` 등). 테넌트 삭제는 드문 관리 작업이라 CASCADE 순차 스캔을 감수하는 대신 쓰기
오버헤드를 아꼈습니다. 테넌트 오프보딩이 잦아지면 추가하세요.

**`audit_log` 파티셔닝은 하지 않았습니다.** 시간축으로 무한 증가하므로 운영 데이터가
쌓이면 `occurred_at` 기준 range 파티셔닝을 검토하세요. 지금 단계에서는 불필요한
복잡도입니다.

## 확인

```bash
docker exec -it smart-ebl-postgres psql -U smart_ebl -d smart_ebl -c "\dt"
```

## 적용 방법 (Alembic)

`initdb/` 는 비어 있습니다. 스키마 DDL 의 출처는 `migrations/sql/` 이고 Alembic 이 적용을 관리합니다.

```bash
docker compose up -d && uv run alembic upgrade head
```

**소유권 경계** — `migrations/env.py` 의 `SQL_OWNED_TYPES` 가 인덱스·CHECK·UNIQUE 를
autogenerate 비교에서 제외합니다. 제외하지 않으면 모델에 선언되지 않은 이 객체들을
autogenerate 가 매번 "제거" 로 제안하고, 그대로 적용하면 부분 인덱스 15개와 명세 규칙
CHECK 32개가 사라집니다. 테이블·컬럼 변경은 정상 감지되며, 제약·인덱스를 추가할 때는
생성된 리비전에 `op.execute()` 로 직접 작성하세요.

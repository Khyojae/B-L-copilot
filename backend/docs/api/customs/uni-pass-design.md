# UNI-PASS 기반 통관 상태 조회 구조 설계

> 출처: 717 멘토님 피드백 회의 발표 자료

## 개요

관세청 UNI-PASS Open API(화물통관 진행정보 조회)를 연동해 e-B/L의 통관 상태를 실시간으로 조회/알림한다.

이 API로 충족 가능한 핵심 기능:
- 통관 상태 추적 (상태 배지 표시)
- 화물 기본 정보 (품명, 화물구분)
- 누가 운송/대행 중인지 (선사, 포워더)
- 반출입 이력 (언제 어떤 처리가 있었는지)

## 1. 입출력 정의

**요청**: `cargMtNo`(화물관리번호), `mblNo`/`hblNo`(B/L No), `blYy`(입항연도)

**응답 주요 필드**: `cargMtNo`, `prgsStts`(진행상태), `prgsStCd`(진행상태코드), `shipNat`/`shipNatNm`(선박국적), `agnc`(대리점), `shcoFlcoSgn`/`shcoFlco`(선사항공사), `cargTp`(화물구분), `shipNm`(선박명), `blPt`/`blPtNm`(B/L유형), `dsprCd`/`dsprNm`(양륙항), `prnm`(품명), `cntrGcnt`/`cntrNo`(컨테이너), `csclPrgsStts`(통관진행상태), `frwrSgn`/`frwrEntsConm`(포워더), `cargTrcnRelaBsopTpcd`/`rlbrDttm`/`rlbrCn`(반출입 이력, 0..n)

## 2. 에러코드 정의

UNI-PASS는 모든 에러를 `tCnt = -1` + `ntceInfo`(한글 메시지)로만 내려준다. HTTP 상태코드나 표준 에러코드 체계가 없어서, 우리 플랫폼에서 직접 에러코드를 설계하고 매핑해야 한다.

**전략**:
1. 에러코드를 먼저 설계한다 (예: `UNAUTHORIZED`, `FORBIDDEN_ROLE`, `INVALID_FORMAT`, `MISSING_PARAM`, `CUSTOMS_NOT_FOUND`, `CUSTOMS_AUTH_ERROR`, `CUSTOMS_UPSTREAM_ERROR`, `CUSTOMS_PARSE_ERROR` 등)
2. 실제 UNI-PASS API를 호출하면서 마주치는 `ntceInfo`의 실제 한글 문구를 각 코드에 채워나간다 (사전 방식)

에러 분류 축:
- **우리 플랫폼 자체 검증 단계** (JWT/role/파라미터 형식 등 — 우리가 정의)
- **UNI-PASS 응답 기반 분기** (HTTP 200 + `tCnt`/`ntceInfo` 파싱)
- **외부 연동 장애** (UNI-PASS 쪽 인증서 오류, 타임아웃, XML 파싱 실패 등 — 모두 HTTP 200 + `tCnt=-1` + 한글 메시지로 옴)

## 3. XML 파싱

UNI-PASS 응답은 JSON이 아니라 XML — 백엔드에서 파싱 단계가 하나 더 필요.

- 라이브러리: `fast-xml-parser` (가볍고 빠름)
- 파싱 후 정상/에러 분기로 연결

## 4. 폴링

UNI-PASS는 REST 조회만 제공하고 웹훅/푸시는 없음 → 주기적 폴링 방식으로 구현.

- 대상: `customs_declarations` 테이블에서 `is_polling_active`인 건만 폴링
- 주기: `node-cron` 30분 간격
- 상태가 실제로 바뀌었을 때만 '변경'으로 처리 (알림 발송 등)
- 완료 상태(예: 반출완료) 도달 시 해당 건 폴링 종료

## 5. 캐싱

동일 B/L 반복 조회를 막아 응답 속도를 개선.

- 저장: 조회 결과를 `customs_declarations`(최신 상태 + `unipass_response` JSONB)와 `customs_status_history`(상태 변경 이력)에 함께 보관
- TTL: 마지막 조회 후 30분 이내 재요청 시 DB 캐시 반환 (UNI-PASS 미호출)
- 갱신: TTL 경과 또는 폴링 주기 도래 시에만 실제 호출
- 완료 건은 더 이상 상태가 안 바뀌므로 영구 캐시 (재호출 안 함)

## 실제 테이블 (customs_tracking 초안 대체)

이전 초안에서 새 `customs_tracking` 테이블을 제안했으나, 실제 스키마(`eB_L_DB_Schema_보완추가.xlsx`)에 이미 같은 역할을 하는 테이블이 있어 그쪽을 그대로 쓴다.

### customs_declarations

| 컬럼 | 타입 | 설명 |
|---|---|---|
| customs_id | BIGSERIAL (PK) | |
| bl_id | BIGINT (FK -> bill_of_lading) | 연결된 e-B/L |
| declaration_number | VARCHAR(50), UNIQUE, NULL | 수입신고번호 (유니패스 채번) |
| declaration_type | VARCHAR(30), NULL | import / export |
| customs_status | VARCHAR(30), DEFAULT 'pre_declaration' | pre_declaration / declared / examining / released / rejected |
| declarant_name | VARCHAR(100), NULL | |
| customs_office | VARCHAR(100), NULL | |
| unipass_response | JSONB, NULL | 최신 API 응답 원본 |
| is_polling_active | BOOLEAN, DEFAULT TRUE | 완료 시 FALSE |
| poll_fail_count | INTEGER, DEFAULT 0 | 연속 실패 횟수 (N회 초과 시 폴링 제외) |
| query_key | VARCHAR(50), NULL | UNI-PASS 조회 키(cargMtNo/hblNo+blYy) |
| last_checked_at | TIMESTAMPTZ, NULL | TTL 계산 기준 |
| created_at / updated_at | TIMESTAMPTZ | |

### customs_status_history

| 컬럼 | 타입 | 설명 |
|---|---|---|
| history_id | BIGSERIAL (PK) | |
| customs_id | BIGINT (FK -> customs_declarations) | |
| status | VARCHAR(30) | 변경된 통관 상태 |
| status_description | TEXT, NULL | 세관 메시지 |
| unipass_response | JSONB, NULL | 이력 시점의 응답 원본 |
| recorded_at | TIMESTAMPTZ | |

> 상태: 확정 — [auth/db-schema.md](../auth/db-schema.md)와 같은 마이그레이션 세트(`api/db/migrations/001_create_core_schema.sql`)에 포함.

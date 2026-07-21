# Auth DB 스키마

> 상태: 실제 스키마 확정 (`eB_L_DB_Schema_보완추가.xlsx` 기준, BIGSERIAL PK). `api/db/migrations/`에 마이그레이션으로 반영됨.
> JWT/RBAC 설계 배경은 [jwt-design.md](./jwt-design.md), [rbac-matrix.md](./rbac-matrix.md), PKI는 [pki-design.md](./pki-design.md) 참고.

## users

| 컬럼 | 타입 | 설명 |
|---|---|---|
| user_id | BIGSERIAL (PK) | |
| email | VARCHAR(255), UNIQUE | 로그인 ID |
| password_hash | VARCHAR(255) | bcrypt 해시 |
| role | VARCHAR(50), CHECK | shipper / carrier / forwarder / bank / customs / admin |
| company_name | VARCHAR(255) | 소속 회사명 |
| company_code | VARCHAR(100), NULL | 사업자/회사 코드 — JWT payload의 `org_id` 클레임 값은 여기서 가져옴 (FK 아님, 텍스트 매칭) |
| wallet_address | VARCHAR(42), UNIQUE, NULL | Ethereum 지갑 주소 (MetaMask) |
| public_key | TEXT, NULL | PKI 공개키 (전자서명 검증용, `certificates` 테이블과 별개로 빠른 조회용) |
| is_active | BOOLEAN, DEFAULT TRUE | 계정 활성화 여부 |
| token_version | INTEGER, DEFAULT 0 | 비밀번호 변경/role 변경/계정정지/전체 로그아웃 시 증가 — JWT의 `tv` 클레임과 비교해 즉시 폐기 처리 |
| email_verified_at | TIMESTAMPTZ, NULL | |
| phone_verified_at | TIMESTAMPTZ, NULL | |
| phone_number | VARCHAR(20), UNIQUE, NULL | 휴대폰 본인인증용 |
| last_login_at | TIMESTAMPTZ, NULL | |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

## refresh_tokens

| 컬럼 | 타입 | 설명 |
|---|---|---|
| token_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id) | |
| family_id | UUID | 로그인(기기) 1회당 고정, rotation 내내 유지 — 재사용 탐지 시 이 family 전체를 폐기 |
| token_hash | VARCHAR(255) | 원문 대신 해시 저장 |
| jti | VARCHAR(64), UNIQUE | 토큰 고유 ID |
| replaced_by | BIGINT, NULL (FK -> refresh_tokens.token_id) | 이 토큰을 대체한 다음 세대 토큰 |
| expires_at | TIMESTAMPTZ | 발급 시점 + 1일 (RT 만료 정책) |
| is_revoked | BOOLEAN, DEFAULT FALSE | 로그아웃/rotation/재사용탐지 시 TRUE |
| created_at | TIMESTAMPTZ | |

**재사용 탐지(Reuse Detection)**: `/refresh` 요청 시 원자적 `UPDATE ... WHERE token_hash = $1 AND is_revoked = FALSE RETURNING *`로 rotation. 이미 `is_revoked = TRUE`인 토큰이 다시 들어오면 탈취로 간주 — 같은 `family_id`의 모든 토큰을 즉시 폐기하고 `audit_logs`에 기록.

## certificates (PKI)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| cert_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id) | 선사만 보유 |
| serial_no | VARCHAR(64), UNIQUE | X.509 일련번호 |
| public_key | TEXT | 검증용 공개키 |
| valid_from | TIMESTAMPTZ | |
| valid_to | TIMESTAMPTZ | 발급 + 1년 |
| is_revoked | BOOLEAN, DEFAULT FALSE | CRL 대신 이 컬럼으로 폐기 확인 (검증 주체가 우리 하나뿐이라 표준 CRL 불필요) |
| revoked_at | TIMESTAMPTZ, NULL | |
| revoke_reason | VARCHAR(200), NULL | |
| created_at | TIMESTAMPTZ | |

## audit_logs

| 컬럼 | 타입 | 설명 |
|---|---|---|
| log_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id), NULL | |
| action | VARCHAR(50) | login/refresh/rt_reuse_detected/sign/verify/role_change 등 |
| entity_type | VARCHAR(50), NULL | |
| entity_id | BIGINT, NULL | |
| result | VARCHAR(20) | success/fail/denied |
| ip_address | VARCHAR(45), NULL | |
| created_at | TIMESTAMPTZ | |

admin 역할의 모든 쓰기 작업은 예외 없이 여기 기록한다 ([rbac-matrix.md](./rbac-matrix.md) 참고).

## email_verification_tokens

| 컬럼 | 타입 | 설명 |
|---|---|---|
| token_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id) | |
| token_hash | VARCHAR(255) | |
| expires_at | TIMESTAMPTZ | |
| consumed_at | TIMESTAMPTZ, NULL | |

## phone_verifications

| 컬럼 | 타입 | 설명 |
|---|---|---|
| verification_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id), NULL | 가입 전 단계에서는 NULL 가능 |
| phone_number | VARCHAR(20) | |
| code_hash | VARCHAR(255) | 인증번호 해시 |
| expires_at | TIMESTAMPTZ | |
| verified_at | TIMESTAMPTZ, NULL | |

> 실제 SMS 발송은 스텁(`smsProvider.js`)으로 구현 — NICE/PASS 등 실제 본인인증 연동은 비용/계약 문제로 이후 교체 지점만 남겨둠.

## password_reset_tokens

| 컬럼 | 타입 | 설명 |
|---|---|---|
| token_id | BIGSERIAL (PK) | |
| user_id | BIGINT (FK -> users.user_id) | |
| token_hash | VARCHAR(255) | |
| expires_at | TIMESTAMPTZ | |
| consumed_at | TIMESTAMPTZ, NULL | |

## customs_declarations / customs_status_history / notifications

인증 모듈 범위 밖이지만 audit_logs와 마찬가지로 이미 실제 스키마에 존재 — [uni-pass-design.md](../customs/uni-pass-design.md) 참고.

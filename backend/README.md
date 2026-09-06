# Smart_e-BL_Backend

블록체인 기반 전자선하증권(e-B/L) 발행·양도 서비스의 백엔드 저장소입니다.
API 서버, 스마트컨트랙트(블록체인), AI 서류검증 서비스를 포함합니다.

## 디렉토리 구조

```
Smart_e-BL_Backend/
├── api/                     # 메인 API 서버 (BE)
│   ├── src/
│   │   ├── auth/            # 회원가입/로그인/PKI 전자서명/RBAC 미들웨어
│   │   ├── ebl/              # e-B/L 발행·조회·양도·소각 API
│   │   ├── document/         # 문서 업로드, AI 검증 요청/결과 API
│   │   ├── customs/          # UNI-PASS 통관 상태 연동
│   │   ├── notification/     # 이메일 알림 서비스
│   │   ├── workflow/         # 발행→검증→통관→D/O 워크플로 엔진
│   │   └── common/           # 설정, 공통 미들웨어
│   ├── db/                   # PostgreSQL 스키마/마이그레이션
│   └── tests/                # BE 단위 테스트
├── blockchain/               # 스마트컨트랙트 (BlockChain)
│   ├── contracts/            # e-B/L, 소유권이전, L/C연동, 소각 컨트랙트
│   ├── scripts/               # Hardhat 배포 스크립트
│   ├── ipfs/                  # IPFS 업로드/핀닝 모듈
│   └── test/                  # Hardhat 단위 테스트
└── aiService/                 # AI 서류 진위검증
    ├── ocr/                   # PaddleOCR (B/L, Invoice, Packing List)
    ├── ruleEngine/            # 하자 시각화, L/C 매칭 규칙
    ├── mlModel/               # XGBoost 이상거래탐지 모델
    ├── api/                   # FastAPI 래핑 엔드포인트
    └── tests/
```

## 환경 변수

각 서비스 디렉토리(`api/`, `blockchain/`, `aiService/`)에 `.env.example`을 참고하여
`.env` 파일을 생성하세요. `.env`는 git에 커밋되지 않습니다.

## 관련 저장소
- `Smart_e-BL_Frontend`: 프론트엔드 (화면 구현 단위 브랜치 전략)
- `Smart_e-BL`: 배포/CI-CD/통합테스트/문서

## 통합 저장소 동기화

이 저장소의 작업 결과는 통합 저장소 [`SmartBLAI/Smart_e-BL`](https://github.com/SmartBLAI/Smart_e-BL)의
`develop` 브랜치 `backend/` 폴더로 동기화됩니다.

```bash
# 전송 대상 확인 (PR 생성하지 않음)
./scripts/sync-to-monorepo.sh --dry-run

# 동기화 실행 → 통합 저장소에 PR 생성
./scripts/sync-to-monorepo.sh
```

`main`에 push되면 `.github/workflows/sync-to-monorepo.yml`이 같은 스크립트를 자동 실행합니다.
Actions 탭에서 `모노레포 동기화` → `Run workflow`로 수동 실행할 수도 있습니다.

### 동기화 대상

`git archive`로 **git이 추적 중인 파일만** 내보냅니다. 따라서 다음은 구조적으로 제외됩니다.

| 제외 항목 | 사유 |
|---|---|
| `api/certs/` | `scripts/generate-dev-ca.js`로 로컬 생성되는 개발용 CA 개인키 (untracked) |
| `.env` | 자격증명 (gitignore) |
| `node_modules/`, `__pycache__/` | 빌드 산출물 (gitignore) |
| `.github/` | 이 워크플로가 통합 저장소에서 중복 실행되는 것을 방지 |

제외 목록을 사람이 관리하지 않아도 되도록 의도적으로 `rsync` 대신 `git archive`를 씁니다.
`--dry-run`이 민감 항목 포함 여부를 매번 검사합니다.

### 사전 준비 (최초 1회)

GitHub Actions로 자동 동기화하려면 `MONOREPO_TOKEN` Secret 등록이 필요합니다.
기본 `GITHUB_TOKEN`은 이 저장소에만 유효해서 통합 저장소에 push할 수 없습니다.

1. `SmartBLAI/Smart_e-BL`에 대한 `contents:write` · `pull_requests:write` 권한을 가진
   PAT(또는 GitHub App 토큰)을 발급
2. Settings → Secrets and variables → Actions → New repository secret
3. 이름 `MONOREPO_TOKEN`으로 등록

등록 전에는 `workflow_dispatch`의 `dry_run` 옵션으로만 실행하세요.

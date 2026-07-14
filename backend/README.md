# eblBackend

블록체인 기반 전자선하증권(e-B/L) 발행·양도 서비스의 백엔드 저장소입니다.
API 서버, 스마트컨트랙트(블록체인), AI 서류검증 서비스를 포함합니다.

## 디렉토리 구조

```
eblBackend/
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
- `eblFrontend`: 프론트엔드 (화면 구현 단위 브랜치 전략)
- `eblIntegration`: 배포/CI-CD/통합테스트/문서

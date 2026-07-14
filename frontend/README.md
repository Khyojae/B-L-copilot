# ebl-frontend

블록체인 기반 전자선하증권(e-B/L) 발행·양도 서비스의 프론트엔드 저장소입니다.
관리 효율을 위해 하나의 큰 저장소 대신 **기능 및 화면 단위 브랜치 전략**으로 관리합니다.

## 디렉토리 구조

```
ebl-frontend/
├── src/
│   ├── features/
│   │   ├── common/         # 디자인시스템, 레이아웃, 인증(로그인/회원가입), 랜딩, 알림센터
│   │   ├── ebl/            # e-B/L 발행 폼, 목록/조회, 소유권이전 UI, MetaMask 연동
│   │   ├── verification/   # 문서업로드, OCR결과, 하자시각화, L/C매칭, 이상거래탐지 화면
│   │   ├── customs/        # 통관 모니터링 대시보드
│   │   └── admin/          # 관리자 대시보드, D/O 처리 화면
│   └── shared/              # 공통 컴포넌트/훅/유틸
└── tests/                    # FE 단위 테스트
```

## 브랜치 전략

| 브랜치 | 설명 |
|---|---|
| `main` | 배포 가능한 안정 브랜치 |
| `develop` | 통합 개발 브랜치 (모든 feature 브랜치가 병합되는 지점) |
| `feature/common` | 디자인시스템/레이아웃/인증/랜딩/알림센터 |
| `feature/ebl` | e-B/L 발행/조회/양도 화면 |
| `feature/verification` | 서류 업로드/OCR/하자/L-C매칭/이상거래탐지 화면 |
| `feature/customs` | 통관 모니터링 대시보드 |
| `feature/admin` | 관리자 대시보드 |

작업 시 해당 `feature/*` 브랜치에서 `src/features/{module}/` 디렉토리를 중심으로
개발하고, 완료 후 `develop`으로 병합합니다. `develop`이 안정화되면 `main`으로 병합합니다.

## 관련 저장소
- `ebl-backend`: API 서버 / 블록체인 / AI 검증 서비스
- `ebl-integration`: 배포/CI-CD/통합테스트/문서

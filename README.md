# B/L Copilot

전자 선하증권(B/L) 자동검증 플랫폼 **B/L Copilot**의 통합 저장소입니다.
`backend/`와 `frontend/`를 각각의 독립 저장소에서 동기화해 한 곳에서 볼 수
있도록 모아둔 리포지토리이며, 실제 개발은 각 하위 저장소에서 이루어집니다.

## 구성

| 폴더 | 설명 | 원본 저장소 |
|---|---|---|
| [`frontend/`](./frontend) | 수출기업·포워더·은행 심사역이 쓰는 웹 UI (React + TypeScript) | `Smart_e-BL_Frontend` |
| [`backend/`](./backend) | API 서버(`api/`), AI 서류검증 서비스(`aiService/`), 스마트컨트랙트(`blockchain/`) | `Smart_e-BL_Backend` |

각 폴더 안의 README에 더 자세한 디렉토리 구조·환경 변수·실행 방법이 있습니다.

## 무엇을 만드는지

수출기업·포워더가 선적 서류를 올리면 AI가 하자를 자동으로 검증하고,
은행 심사역이 그 검증 결과를 확인하는 흐름을 지원합니다. 프론트엔드는
S1 대시보드 · S2 업로드 · S3 초안 편집기 · S4 검증 결과 · S5 타임라인 ·
S6 경보 센터 화면을, 백엔드는 API 서버 · OCR/규칙엔진/이상거래탐지로
구성된 AI 검증 서비스 · 스마트컨트랙트를 담당합니다.

## 시작하기

```bash
# 프론트엔드
cd frontend
npm install
npm run dev

# 백엔드 (각 서비스 디렉토리 README 참고)
cd backend/api        # 또는 backend/aiService, backend/blockchain
```

각 서비스는 자체 `.env.example`을 참고해 `.env`를 구성하세요.

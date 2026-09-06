"""B/L Copilot — 선하증권 AI 검증·작성 지원 시스템.

FastAPI 단일 구성입니다. 프로세스는 둘로 나뉩니다.

  API    : uvicorn smart_e_bl.api.main:app     — 짧은 요청, 잡 접수·상태 조회
  워커   : python -m smart_e_bl.worker.main    — OCR·LLM 추출·추론

스키마의 출처는 migrations/sql/ 이며 Alembic 이 적용을 관리합니다.
"""

__version__ = "0.1.0"

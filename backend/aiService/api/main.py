"""
AI 서비스 API (기획안 6.2 "FastAPI(AI 모듈군)").

Express 게이트웨이(:4000)가 이 서비스(:5000)를 호출하고, 결과는
`BACKEND_CALLBACK_URL` 로 되돌린다. 저장은 하지 않는다 — 저장 책임은
게이트웨이에 있고, 여기서 DB 를 잡으면 AI 모듈이 스키마 변경에 묶인다.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from report import apply_narrative, build_report, render_pdf
from ruleEngine import LCTerms, RuleEngine

# 룰 카탈로그는 프로세스 기동 시 1회만 읽는다. 요청마다 읽으면 YAML 파싱이
# 응답 시간에 그대로 들어가고, 카탈로그 오류를 기동이 아니라 첫 요청에서
# 발견하게 된다.
_engine: Optional[RuleEngine] = None


def engine() -> RuleEngine:
    global _engine
    if _engine is None:
        _engine = RuleEngine()
    return _engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    """기동 시 카탈로그를 검증한다. 룰이 깨졌으면 여기서 죽는 편이 낫다."""
    print(f"[aiService] 룰 카탈로그 로드 완료: {len(engine())}건")
    yield


app = FastAPI(
    title="B/L Copilot AI Service",
    version="0.1.0",
    description="F1 인테이크 · F3 하자 예측 · F4 리포트",
    lifespan=lifespan,
)


# ── 요청/응답 모델 ───────────────────────────────────────────────

class VerifyRequest(BaseModel):
    """하자 검증 요청.

    bl 은 F1 이 뽑은 값이든 S3 편집기에서 사람이 고친 값이든 같은 형태로
    받는다. 두 경로를 가르면 '편집 후 재검증'이 다른 코드 경로를 타게 된다.
    """

    bl: Dict[str, Optional[str]] = Field(
        ..., description="B/L 필드. BLFields.to_dict() 와 같은 형태."
    )
    lc: Optional[Dict[str, Any]] = Field(
        None, description="신용장 조건(MT700). 없으면 서류 내부 정합성만 검사."
    )
    as_of: Optional[datetime] = Field(
        None, description="제시기간 계산 기준 시각. 생략하면 현재 시각."
    )


class VerifyResponse(BaseModel):
    shipment_id: Optional[str] = None
    verdict: Dict[str, Any]


# ── 엔드포인트 ───────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "rules_loaded": len(engine()),
        "env": os.getenv("ENV", "development"),
    }


@app.get("/rules")
def list_rules() -> dict:
    """적재된 룰 목록. S11 설정 화면과 발표 시연에서 쓴다."""
    return {
        "count": len(engine()),
        "rules": [
            {
                "id": r["id"],
                "title": r["title"],
                "severity": r["severity"],
                "source": r.get("source", ""),
                "check": r["check"],
            }
            for r in engine().rules
        ],
    }


# ── F1 인테이크 ──────────────────────────────────────────────────

class LabelExtractRequest(BaseModel):
    """라벨 JSON 으로 추출.

    OCR 엔진 없이 파서만 태우는 경로다. PaddleOCR·PaddlePaddle 은 설치가
    무겁고 플랫폼을 타는데, 파서 동작 확인과 시연에는 그게 필요 없다.
    """

    Images: Dict[str, Any] = Field(default_factory=dict, description="이미지 메타")
    bbox: List[Dict[str, Any]] = Field(default_factory=list, description="OCR bbox 목록")


def _draft_response(draft) -> dict:
    return draft.to_dict()


@app.post("/extract/label")
def extract_from_label(req: LabelExtractRequest) -> dict:
    """F1 — 라벨 JSON → B/L 초안. 기획안 S3(초안 편집기)가 이 응답을 그린다."""
    import json
    import tempfile
    from pathlib import Path

    from ocr import IntakePipeline

    if not req.bbox:
        raise HTTPException(status_code=400, detail="bbox 가 비어 있습니다.")

    # 추출기가 경로를 받는 구조라 임시 파일을 거친다. 요청 본문을 그대로
    # 파서에 넣는 오버로드를 두면 두 입력 경로가 갈려 유지보수가 늘어난다.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "label.json"
        path.write_text(
            json.dumps({"Images": req.Images, "bbox": req.bbox}, ensure_ascii=False),
            encoding="utf-8",
        )
        draft = IntakePipeline().run_from_json(str(path))

    return _draft_response(draft)


@app.post("/extract")
async def extract_from_image(file: UploadFile = File(...)) -> dict:
    """F1 — 이미지 → B/L 초안. PaddleOCR 이 필요하다."""
    import tempfile
    from pathlib import Path

    from ocr import IntakePipeline

    suffix = Path(file.filename or "upload.png").suffix or ".png"
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(payload)
        try:
            draft = IntakePipeline().run_from_image(str(path))
        except ImportError as exc:
            # OCR 엔진 미설치는 서버 구성 문제지 요청 오류가 아니다.
            # 500 으로 흘리면 게이트웨이가 무의미하게 재시도한다.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _draft_response(draft)


@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    """F3 하자 예측. 기획안 S4(검증 결과) 화면이 이 응답을 그대로 그린다."""
    if not req.bl:
        raise HTTPException(status_code=400, detail="bl 필드가 비어 있습니다.")

    lc = LCTerms.from_dict(req.lc) if req.lc else None

    try:
        verdict = engine().verify(req.bl, lc, as_of=req.as_of)
    except TypeError as exc:
        # 입력 형 오류는 400 이다. 500 으로 흘리면 게이트웨이가 재시도한다.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return VerifyResponse(shipment_id=req.bl.get("bl_no"), verdict=verdict.to_dict())


class ReportRequest(VerifyRequest):
    """F4 리포트 요청. 검증 입력에 제출 서류 목록만 더한다."""

    submitted_documents: Optional[List[str]] = Field(
        None, description="실제 제출한 서류명. 신용장 46A 와 대조해 누락을 찾는다."
    )


def _make_report(req: "ReportRequest"):
    """검증 → 리포트 조립 → 요약. /report 와 /report/pdf 가 공유한다."""
    if not req.bl:
        raise HTTPException(status_code=400, detail="bl 필드가 비어 있습니다.")

    lc = LCTerms.from_dict(req.lc) if req.lc else None
    try:
        verdict = engine().verify(req.bl, lc, as_of=req.as_of)
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    report = build_report(
        verdict, req.bl, lc,
        submitted_documents=req.submitted_documents,
        as_of=req.as_of,
    )
    return apply_narrative(report)


@app.post("/report")
def report_json(req: ReportRequest) -> dict:
    """리포트 JSON. 기획안 S7(선제 대응 리포트) 미리보기가 이걸 그린다."""
    return _make_report(req).to_dict()


@app.post("/report/pdf")
def report_pdf(req: ReportRequest) -> Response:
    """리포트 PDF. 기획안 5.2 'PDF 로 저장·공유'."""
    report = _make_report(req)
    filename = f"BL_Copilot_Report_{report.bl_no or 'draft'}.pdf"
    return Response(
        content=render_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["app"]

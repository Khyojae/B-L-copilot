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

from dotenv import load_dotenv

from report import apply_narrative, build_report, render_pdf
from report.share import (
    DEFAULT_TTL_SECONDS,
    ExpiredShareToken,
    ShareTokenError,
    ShareTokenTooLarge,
)
from report import share as share_tokens
from ruleEngine import LCTerms, RuleEngine

# `.env` 를 읽는다. 이 호출이 없으면 `.env.example` 이 설명하는 설정이 하나도
# 적용되지 않으며, **그 실패는 조용하다.** GEMINI_API_KEY 가 없으면 리포트가
# 템플릿으로 떨어지고, REPORT_SHARE_SECRET 가 없으면 프로세스마다 임시 키를
# 만들어 재시작 시 발급한 공유 링크가 전부 죽는다. 둘 다 에러 없이 "동작하는
# 것처럼" 보이므로 기동 시점에 확실히 읽어 둔다.
#
# 이미 설정된 환경변수는 덮지 않는다(python-dotenv 기본값). 컨테이너·CI 가
# 주입한 값이 파일보다 우선해야 하기 때문이다.
load_dotenv()

# 룰 카탈로그는 프로세스 기동 시 1회만 읽는다. 요청마다 읽으면 YAML 파싱이
# 응답 시간에 그대로 들어가고, 카탈로그 오류를 기동이 아니라 첫 요청에서
# 발견하게 된다.
_engine: Optional[RuleEngine] = None


def engine() -> RuleEngine:
    global _engine
    if _engine is None:
        _engine = RuleEngine()
    return _engine


# 하자 확률 예측기도 1회만 만든다. 모델 파일 로드가 요청 시간에 들어가면
# 첫 요청만 느려지고, 그 편차가 성능 측정을 흐린다.
#
# 모델이 없으면 룰 가중치 합산으로 대체되며 산출 출처가 `rules-v1` 로
# 남는다 — 예외가 아니라 값이 달라지는 실패라서, 그 사실이 응답에 드러나야
# 한다.
_predictor: Optional["DefectPredictor"] = None


def predictor() -> "DefectPredictor":
    global _predictor
    if _predictor is None:
        from mlModel.predictor import DefectPredictor

        _predictor = DefectPredictor()
    return _predictor


@asynccontextmanager
async def lifespan(_: FastAPI):
    """기동 시 카탈로그를 검증한다. 룰이 깨졌으면 여기서 죽는 편이 낫다."""
    print(f"[aiService] 룰 카탈로그 로드 완료: {len(engine())}건")
    unverified = engine().unverified_rules()
    if unverified:
        # 기획안 9절 "멘토 기업 실무 검증"의 남은 작업량이다. 발표에서
        # 조문이 틀리면 시스템 전체의 신뢰가 무너지므로 조용히 두지 않는다.
        print(
            f"[aiService] 경고: 조문 인용 미검증 {len(unverified)}건 "
            f"/ {len(engine())}건 — 실무 검증 필요"
        )
    # 모델 적재 여부를 기동 시 확정한다. 첫 요청에서 알게 되면, 그때는
    # 이미 rules-v1 로 산출된 응답이 나간 뒤다.
    probe = predictor().predict({}, None, RuleEngine(rules=[
        {"id": "_probe", "title": "probe", "severity": "info",
         "check": "required", "source": "-", "message": "-", "fields": ["bl_no"]}
    ]).verify({}))
    if probe.model == "rules-v1":
        print(
            "[aiService] 경고: 학습된 하자 예측 모델이 없습니다 — "
            "위험 점수를 룰 가중치로 대체합니다. "
            "학습: python -m mlModel.evaluate --save-model"
        )
    else:
        print(f"[aiService] 하자 예측 모델 적재: {probe.model}")

    if share_tokens.secret_is_ephemeral():
        # 죽이지는 않는다 — 개발·시연에서는 임시 키로 충분하다. 다만 배포에서
        # 이 줄이 보이면 재시작마다 공유 링크가 끊긴다는 뜻이다.
        print(
            f"[aiService] 경고: {share_tokens.SECRET_ENV} 미설정 — "
            "공유 링크가 서버 재시작 시 무효가 됩니다."
        )
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
    prediction: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "하자 확률(위험도 순위용). 판정 자체는 verdict 가 한다 — "
            "이진 판정은 룰이, 순위는 모델이 낫다는 측정 결과에 따른다."
        ),
    )


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
        # 조문 인용이 실무 검증을 거치지 않은 룰 수. 화면이 이 값을 숨기면
        # 미검증 조문이 검증된 것처럼 인용된다 — 기획안 9절의 리스크다.
        "unverified_source_count": len(engine().unverified_rules()),
        "rules": [
            {
                "id": r["id"],
                "title": r["title"],
                "severity": r["severity"],
                "source": r.get("source", ""),
                "source_verified": r.get("verified") is True,
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


@app.post("/extract/pdf")
async def extract_from_pdf(
    file: UploadFile = File(...),
    page: int = 0,
) -> dict:
    """F1 — PDF → B/L 초안.

    텍스트 레이어가 있는 PDF(전자 발행 서류 대부분)는 **OCR 을 타지 않는다.**
    스캔본만 이미지로 구워 OCR 에 넘기므로, 그때만 PaddleOCR 이 필요하다.
    어느 경로였는지는 응답의 `source` 에 `pdf-text` / `pdf-ocr` 로 남는다.
    """
    import tempfile
    from pathlib import Path

    from ocr import IntakePipeline

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if not payload.startswith(b"%PDF"):
        # 확장자가 아니라 내용으로 판정한다. 이미지 파일을 .pdf 로 바꿔
        # 올리는 일이 흔하고, 그때 PyMuPDF 오류를 그대로 흘리면 원인을
        # 알 수 없는 500 이 된다.
        raise HTTPException(
            status_code=400,
            detail="PDF 파일이 아닙니다. 이미지는 /extract 를 쓰세요.",
        )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(payload)
        try:
            draft = IntakePipeline().run_from_pdf(str(path), page_number=page)
        except ValueError as exc:
            # 페이지 번호 범위 초과·빈 PDF — 요청이 잘못된 경우다.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ImportError as exc:
            # PyMuPDF 미설치, 또는 스캔본인데 PaddleOCR 미설치.
            # 서버 구성 문제지 요청 오류가 아니다.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _draft_response(draft)


@app.post("/extract/excel")
async def extract_from_excel(
    file: UploadFile = File(...),
    sheet: Optional[str] = None,
) -> dict:
    """F1 — 엑셀 → B/L 초안. OCR 을 타지 않는다.

    sheet 를 주지 않으면 값이 가장 많은 시트를 고른다. 첫 시트를 쓰면
    표지·안내 시트가 앞에 있는 파일에서 빈 결과가 나온다.
    """
    import tempfile
    from pathlib import Path

    from ocr import IntakePipeline

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if not payload.startswith(b"PK"):
        # xlsx 는 zip 컨테이너다. 확장자가 아니라 내용으로 판정한다.
        # 구형 .xls(OLE2)나 CSV 를 올리면 여기서 걸리는데, openpyxl 오류를
        # 그대로 흘리는 것보다 무엇이 잘못됐는지 알려주는 편이 낫다.
        raise HTTPException(
            status_code=400,
            detail="xlsx 파일이 아닙니다. 구형 .xls 는 xlsx 로 변환해 주세요.",
        )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.xlsx"
        path.write_bytes(payload)
        try:
            draft = IntakePipeline().run_from_excel(str(path), sheet=sheet)
        except ValueError as exc:
            # 값이 없는 시트·없는 시트명 — 요청이 잘못된 경우다.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _draft_response(draft)


@app.post("/extract/email")
async def extract_from_email(file: UploadFile = File(...)) -> dict:
    """F1 — 이메일(.eml) → B/L 초안.

    **첨부를 먼저 본다.** 본문은 대개 안내문이고 첨부가 서류이므로, 본문부터
    읽으면 선하증권 대신 인사말을 파싱한다. 지원 첨부가 없을 때만 본문을 읽는다.

    응답의 `source` 가 어느 경로였는지 알린다 — `email-pdf` / `email-excel` /
    `email-image` / `email-body`. 본문에서 뽑은 값과 첨부 원본에서 뽑은 값은
    신뢰 수준이 다르다.
    """
    import tempfile
    from pathlib import Path

    from ocr import IntakePipeline

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.eml"
        path.write_bytes(payload)
        try:
            draft = IntakePipeline().run_from_email(str(path))
        except ValueError as exc:
            # 본문도 비었고 읽을 첨부도 없는 경우.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ImportError as exc:
            # 첨부가 스캔 이미지인데 PaddleOCR 이 없는 경우 등.
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _draft_response(draft)


# ── L/C 인테이크 ─────────────────────────────────────────────────

class MT700Request(BaseModel):
    """MT700 전문 원문.

    파일 업로드가 아니라 텍스트로 받는다. SWIFT 전문은 텍스트이고, 파일로
    받으면 인코딩 추측이 한 겹 더 붙는다 — 그 추측이 틀리면 태그는 읽히는데
    상호·품명만 깨지고, 그 상태로도 검증이 돌아 버린다.
    """

    text: str = Field(..., description="MT700 전문 원문. 블록 구조({4:...-})가 있어도 된다.")


@app.post("/lc/mt700")
def parse_lc_mt700(req: MT700Request) -> dict:
    """MT700 원문 → L/C 조건(기획안 v2 5.1 입력 사양).

    `/verify` 의 `lc` 에 그대로 실을 수 있는 형태로 돌려준다. 이 경로를
    `/extract/*` 에 두지 않은 이유는 응답이 다르기 때문이다 — 추출 경로는
    전부 B/L 초안을 내는데 이건 L/C 조건을 낸다. 같은 접두어에 다른 응답을
    섞으면 S3 편집기가 경로마다 분기해야 한다.

    응답의 `notes` 와 `unmapped` 를 화면이 버리지 말 것. L/C 조건이 비면
    그 조건을 쓰는 룰은 평가불가로 빠지고, **위반 0건은 '하자 없음'으로
    읽힌다.** 무엇을 못 읽었는지가 결과만큼 중요하다.
    """
    from ruleEngine import MT700ParseError, parse_mt700

    try:
        parsed = parse_mt700(req.text)
    except MT700ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return parsed.to_dict()


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

    return VerifyResponse(
        shipment_id=req.bl.get("bl_no"),
        verdict=verdict.to_dict(),
        prediction=_predict(req.bl, lc, verdict, req.as_of).to_dict(),
    )


def _predict(bl, lc, verdict, as_of):
    """하자 확률. 예측이 실패해도 검증 결과는 돌려준다.

    모델은 부가 축이다. 여기서 터져 500 을 내면, 룰엔진이 정상적으로 낸
    하자 목록까지 함께 잃는다.
    """
    try:
        return predictor().predict(bl, lc, verdict, as_of)
    except Exception as exc:  # noqa: BLE001
        print(f"[aiService] 경고: 하자 확률 예측 실패 — {exc}")
        from mlModel.predictor import Prediction

        return Prediction(
            probability=verdict.defect_probability,
            model="rules-v1",
            is_defect=verdict.has_critical,
            threshold=0.5,
        )


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
        prediction=_predict(req.bl, lc, verdict, req.as_of),
    )
    return apply_narrative(report)


@app.post("/report")
def report_json(req: ReportRequest) -> dict:
    """리포트 JSON. 기획안 S7(선제 대응 리포트) 미리보기가 이걸 그린다."""
    return _make_report(req).to_dict()


@app.post("/report/pdf")
def report_pdf(req: ReportRequest) -> Response:
    """리포트 PDF. 기획안 5.2 'PDF 로 저장·공유'."""
    return _pdf_response(_make_report(req), inline=False)


def _pdf_response(report, inline: bool) -> Response:
    """PDF 응답. 공유 링크는 브라우저에서 바로 열려야 하므로 inline 이다."""
    disposition = "inline" if inline else "attachment"
    filename = f"BL_Copilot_Report_{report.bl_no or 'draft'}.pdf"
    return Response(
        content=render_pdf(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


# ── F4 공유 ──────────────────────────────────────────────────────

class ShareRequest(ReportRequest):
    """공유 링크 발급 요청. 리포트 요청에 만료만 더한다."""

    ttl_seconds: Optional[int] = Field(
        None,
        ge=60,
        le=90 * 24 * 60 * 60,
        description="링크 유효기간(초). 생략하면 7일.",
    )


class ShareResponse(BaseModel):
    token: str
    path: str
    pdf_path: str
    expires_at: datetime
    ephemeral_secret: bool = Field(
        ...,
        description=(
            "True 면 서버 재시작 시 링크가 무효가 된다. "
            "REPORT_SHARE_SECRET 를 설정하면 False."
        ),
    )
    warning: Optional[str] = None


@app.post("/report/share", response_model=ShareResponse)
def create_share_link(req: ShareRequest) -> ShareResponse:
    """F4 — 리포트 공유 링크 발급. 기획안 5절 "PDF 출력·공유 가능".

    저장하지 않는다. 링크가 입력을 싣고 다니며, 열릴 때마다 같은 리포트를
    다시 조립한다. 설계 근거와 한계는 `report/share.py` 를 볼 것.
    """
    # 발급 시점에 한 번 조립해 본다. 열어 봐야 400 이 나는 링크를 쥐여주면
    # 공유받은 쪽에서 터지고, 그때는 원인을 알 방법이 없다.
    _make_report(req)

    payload = {
        "bl": req.bl,
        "lc": req.lc,
        "as_of": req.as_of.isoformat() if req.as_of else None,
        "submitted_documents": req.submitted_documents,
    }
    try:
        token = share_tokens.encode(
            payload, ttl_seconds=req.ttl_seconds or DEFAULT_TTL_SECONDS
        )
    except ShareTokenTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    ephemeral = share_tokens.secret_is_ephemeral()
    return ShareResponse(
        token=token,
        path=f"/report/shared/{token}",
        pdf_path=f"/report/shared/{token}/pdf",
        expires_at=datetime.fromtimestamp(share_tokens.expires_at(token)),
        ephemeral_secret=ephemeral,
        warning=(
            f"{share_tokens.SECRET_ENV} 가 설정되지 않아 서버 재시작 시 "
            "링크가 무효가 됩니다."
            if ephemeral else None
        ),
    )


def _report_from_token(token: str):
    """토큰 → 리포트. 공유 경로 두 개가 공유한다."""
    try:
        payload = share_tokens.decode(token)
    except ExpiredShareToken as exc:
        # 410 이다. 404 로 내면 받은 쪽이 '주소가 틀렸나'를 의심하게 된다.
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ShareTokenError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    as_of = payload.get("as_of")
    return _make_report(
        ReportRequest(
            bl=payload["bl"],
            lc=payload.get("lc"),
            as_of=datetime.fromisoformat(as_of) if as_of else None,
            submitted_documents=payload.get("submitted_documents"),
        )
    )


@app.get("/report/shared/{token}")
def read_shared_report(token: str) -> dict:
    """공유된 리포트 JSON."""
    return _report_from_token(token).to_dict()


@app.get("/report/shared/{token}/pdf")
def read_shared_report_pdf(token: str) -> Response:
    """공유된 리포트 PDF. 링크를 클릭하면 브라우저에서 바로 열린다."""
    return _pdf_response(_report_from_token(token), inline=True)


__all__ = ["app"]

"""
리포트 → PDF (기획안 5.2 "PDF 로 저장·공유").

한글은 reportlab 내장 CID 폰트(HYSMyeongJo/HYGothic)로 찍는다. TTF 를 쓰면
폰트 파일을 배포에 같이 넣어야 하고, 폐쇄망 온프레미스 프로파일에서
파일 누락으로 조용히 깨진다. CID 폰트는 reportlab 에 포함되어 있다.
"""

from __future__ import annotations

import io
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .model import Report

_SERIF = "HYSMyeongJo-Medium"
_SANS = "HYGothic-Medium"
_FONTS_READY = False

_SEVERITY_COLORS = {
    "critical": colors.HexColor("#B3261E"),
    "warning": colors.HexColor("#B26A00"),
    "info": colors.HexColor("#4A5568"),
}
_RISK_COLORS = {
    "높음": colors.HexColor("#B3261E"),
    "보통": colors.HexColor("#B26A00"),
    "낮음": colors.HexColor("#2E7D32"),
}


def _ensure_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    for name in (_SERIF, _SANS):
        pdfmetrics.registerFont(UnicodeCIDFont(name))
    _FONTS_READY = True


def _styles() -> dict:
    _ensure_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName=_SANS, fontSize=20, leading=26,
            spaceAfter=2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName=_SERIF, fontSize=9.5,
            leading=14, textColor=colors.HexColor("#5F6368"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=_SANS, fontSize=12.5, leading=18,
            spaceBefore=6 * mm, spaceAfter=2 * mm,
            textColor=colors.HexColor("#1A237E"),
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName=_SERIF, fontSize=9.5, leading=15,
            alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName=_SERIF, fontSize=8.5, leading=12.5,
        ),
        "cell_head": ParagraphStyle(
            "cell_head", parent=base["Normal"], fontName=_SANS, fontSize=8.5,
            leading=12.5, textColor=colors.white,
        ),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName=_SERIF, fontSize=8.5, leading=13,
            textColor=colors.HexColor("#5F6368"),
        ),
    }


def render_pdf(report: Report) -> bytes:
    """리포트를 PDF 바이트로 만든다."""
    st = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"선제 대응 서류 분석 리포트 {report.bl_no or ''}".strip(),
        author="B/L Copilot",
    )

    flow: List = []
    flow += _cover(report, st)
    flow += _summary(report, st)
    flow += _risks(report, st)
    flow += _checklist(report, st)
    flow += _recommendations(report, st)
    flow += _outlook(report, st)
    flow += _unchecked(report, st)
    flow += _footer_note(report, st)

    doc.build(flow)
    return buffer.getvalue()


# ── 섹션 ─────────────────────────────────────────────────────────

def _cover(r: Report, st: dict) -> List:
    meta = " · ".join(
        x for x in (
            f"B/L {r.bl_no}" if r.bl_no else None,
            f"L/C {r.lc_no}" if r.lc_no else None,
            f"생성일 {r.generated_at}" if r.generated_at else None,
        ) if x
    )
    return [
        Paragraph("선제 대응 서류 분석 리포트", st["title"]),
        Paragraph(meta or "—", st["subtitle"]),
        Spacer(1, 5 * mm),
    ]


def _summary(r: Report, st: dict) -> List:
    risk_color = _RISK_COLORS.get(r.risk_level, colors.black)
    table = Table(
        [[
            Paragraph(f"<b>위험도</b><br/><font size='16' color='{risk_color}'>"
                      f"{r.risk_level}</font>", st["cell"]),
            Paragraph(f"<b>위험 점수</b><br/><font size='16'>"
                      f"{r.defect_probability:.2f}</font>", st["cell"]),
            Paragraph(
                "<b>검출</b><br/>치명 {c} · 경고 {w} · 참고 {i}".format(
                    c=r.counts.get("critical", 0),
                    w=r.counts.get("warning", 0),
                    i=r.counts.get("info", 0),
                ), st["cell"]),
        ]],
        colWidths=[56 * mm, 56 * mm, 62 * mm],
    )
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C4C7C5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E1E3E1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7F8F8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))

    out = [Paragraph("1. 요약", st["h2"]), table, Spacer(1, 3 * mm)]
    if r.headline:
        out.append(Paragraph(f"<b>{_esc(r.headline)}</b>", st["body"]))
        out.append(Spacer(1, 1.5 * mm))
    if r.narrative:
        out.append(Paragraph(_esc(r.narrative), st["body"]))
    return out


def _risks(r: Report, st: dict) -> List:
    out = [Paragraph("2. 항목별 리스크와 근거 조문", st["h2"])]
    if not r.risks:
        out.append(Paragraph("검출된 위반이 없습니다.", st["body"]))
        return out

    rows = [[
        Paragraph("등급", st["cell_head"]),
        Paragraph("항목", st["cell_head"]),
        Paragraph("내용 및 근거 조문", st["cell_head"]),
    ]]
    for risk in r.risks:
        color = _SEVERITY_COLORS.get(risk.severity, colors.black)
        body = _esc(risk.message)
        if risk.source:
            body += f"<br/><font size='7.5' color='#5F6368'>근거: {_esc(risk.source)}</font>"
        if risk.fields:
            body += (f"<br/><font size='7.5' color='#5F6368'>대상 필드: "
                     f"{_esc(', '.join(risk.fields))}</font>")
        rows.append([
            Paragraph(f"<font color='{color}'><b>{risk.severity_label}</b></font>", st["cell"]),
            Paragraph(_esc(risk.title), st["cell"]),
            Paragraph(body, st["cell"]),
        ])

    table = Table(rows, colWidths=[14 * mm, 40 * mm, 120 * mm], repeatRows=1)
    table.setStyle(_grid_style())
    out.append(table)
    return out


def _checklist(r: Report, st: dict) -> List:
    out = [Paragraph("3. 누락 서류 · 제출 기한 체크리스트", st["h2"])]
    if r.deadline and r.deadline.effective_due:
        d = r.deadline
        state = (f"<font color='#B3261E'><b>{abs(d.days_left)}일 경과</b></font>"
                 if d.is_overdue else f"<b>{d.days_left}일 남음</b>")
        out.append(Paragraph(
            f"실질 제시기한: <b>{d.effective_due}</b> ({state})<br/>"
            f"<font size='8' color='#5F6368'>산출 근거: {_esc(d.basis)}</font>",
            st["body"]))
        out.append(Spacer(1, 2 * mm))

    rows = [[Paragraph("확인", st["cell_head"]), Paragraph("항목", st["cell_head"]),
             Paragraph("비고", st["cell_head"])]]
    for item in r.checklist:
        mark = "O" if item.done else "X"
        color = "#2E7D32" if item.done else "#B3261E"
        rows.append([
            Paragraph(f"<font color='{color}'><b>{mark}</b></font>", st["cell"]),
            Paragraph(_esc(item.label), st["cell"]),
            Paragraph(_esc(item.detail) or "—", st["cell"]),
        ])
    table = Table(rows, colWidths=[12 * mm, 74 * mm, 88 * mm], repeatRows=1)
    table.setStyle(_grid_style())
    out.append(table)
    return out


def _recommendations(r: Report, st: dict) -> List:
    out = [Paragraph("4. 수정 권고 (우선순위순)", st["h2"])]
    if not r.recommendations:
        out.append(Paragraph("권고할 수정 사항이 없습니다.", st["body"]))
        return out

    rows = [[Paragraph("순위", st["cell_head"]), Paragraph("등급", st["cell_head"]),
             Paragraph("조치", st["cell_head"])]]
    for rec in r.recommendations:
        action = _esc(rec.action)
        if rec.target_fields:
            action += (f"<br/><font size='7.5' color='#5F6368'>대상: "
                       f"{_esc(', '.join(rec.target_fields))}</font>")
        rows.append([
            Paragraph(str(rec.order), st["cell"]),
            Paragraph(_esc(rec.severity_label), st["cell"]),
            Paragraph(action, st["cell"]),
        ])
    table = Table(rows, colWidths=[12 * mm, 16 * mm, 146 * mm], repeatRows=1)
    table.setStyle(_grid_style())
    out.append(table)
    return out


def _outlook(r: Report, st: dict) -> List:
    return [
        Paragraph("5. 예상 심사 결과", st["h2"]),
        KeepTogether([
            Paragraph(f"<b>{_esc(r.outlook)}</b>", st["body"]),
            Spacer(1, 1.5 * mm),
            Paragraph(_esc(r.outlook_detail), st["body"]),
        ]),
    ]


def _unchecked(r: Report, st: dict) -> List:
    """미검사 항목. 기획안에 없지만 반드시 싣는다 — 검사하지 못한 것을
    감추면 '전부 검사했고 문제없다'로 읽힌다."""
    if not r.unchecked:
        return []
    out = [PageBreak(), Paragraph("부록. 검사하지 못한 항목", st["h2"]),
           Paragraph(
               "아래 항목은 자료 부족이나 조건 불충족으로 판단하지 못했습니다. "
               "'하자 없음'을 뜻하지 않습니다.", st["note"]),
           Spacer(1, 2 * mm)]
    rows = [[Paragraph("항목", st["cell_head"]), Paragraph("사유", st["cell_head"])]]
    for item in r.unchecked:
        rows.append([Paragraph(_esc(item.title), st["cell"]),
                     Paragraph(_esc(item.reason), st["cell"])])
    table = Table(rows, colWidths=[64 * mm, 110 * mm], repeatRows=1)
    table.setStyle(_grid_style())
    out.append(table)
    return out


def _footer_note(r: Report, st: dict) -> List:
    source = "AI 생성 요약" if r.narrative_source == "llm" else "규칙 기반 요약"
    # 인용한 조문이 어느 카탈로그의 것인지. 룰이 개정되면 같은 서류라도
    # 판정이 달라지므로, 종이로 나간 리포트에도 기준이 남아야 한다.
    catalog = (r.rule_catalog or {}).get("label")
    cross = (r.cross_rule_catalog or {}).get("label")
    # 서류 간 카탈로그는 돌렸을 때만 찍는다. 없는데 자리를 만들면 "서류 간
    # 검사도 했는데 빈 값"으로 읽힌다 — 실제로는 돌리지 않은 것이다.
    labels = " · ".join(x for x in (catalog, cross) if x)
    basis = f" 판정 기준 룰 카탈로그: {_esc(labels)}." if labels else ""
    return [
        Spacer(1, 6 * mm),
        Paragraph(
            f"본 리포트의 위험 점수는 조문 코드화 규칙의 가중 합({_esc(r.model)})이며, "
            f"학습된 예측 모델의 확률이 아닙니다. 요약 문장은 {source}입니다."
            f"{basis} "
            "은행 심사 결과를 보증하지 않습니다.",
            st["note"]),
    ]


# ── 보조 ─────────────────────────────────────────────────────────

def _grid_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474F")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C4C7C5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E1E3E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#FAFAFA")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ])


def _esc(text: Optional[str]) -> str:
    """reportlab 마크업 충돌 방지."""
    if not text:
        return ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


__all__ = ["render_pdf"]

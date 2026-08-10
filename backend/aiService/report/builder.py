"""
Verdict → Report 변환 (F4 본체).

전부 결정론이다. LLM 은 산문 요약만 얹고(narrative.py), 리포트의 골격·수치·
체크리스트·기한은 여기서 계산한다. 이렇게 가른 이유는 두 가지다.

  1. LLM 이 없거나 한도에 걸려도 리포트는 나와야 한다. 발표 중에 외부 API
     하나 때문에 산출물이 통째로 비는 상황을 만들지 않는다.
  2. 하자 확률·기한 같은 수치를 LLM 이 만들면 검증할 방법이 없다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from ruleEngine.checks import parse_date
from ruleEngine.types import (
    DEFAULT_PRESENTATION_DAYS,
    LCTerms,
    Verdict,
)

from .model import (
    ChecklistItem,
    Deadline,
    Recommendation,
    Report,
    RiskItem,
    UncheckedItem,
)

# 심각도 → 정렬 순위. 수정 권고 우선순위에 그대로 쓴다.
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def build_report(
    verdict: Verdict,
    bl: Dict[str, Optional[str]],
    lc: Optional[LCTerms] = None,
    submitted_documents: Optional[Sequence[str]] = None,
    as_of: Optional[datetime] = None,
) -> Report:
    """검증 결과와 서류 정보를 리포트로 조립한다."""
    now = as_of or datetime.now()
    lc = lc or LCTerms()

    report = Report(
        bl_no=_clean(bl.get("bl_no")),
        lc_no=lc.lc_no,
        generated_at=now.date(),
        defect_probability=verdict.defect_probability,
        counts=verdict.counts,
        model=verdict.model,
    )

    report.risks = _risks(verdict)
    report.deadline = _deadline(bl, lc, now)
    report.checklist = _checklist(verdict, bl, lc, submitted_documents, report.deadline)
    report.recommendations = _recommendations(verdict)
    report.outlook, report.outlook_detail = _outlook(verdict, report.deadline)
    report.unchecked = [
        UncheckedItem(rule_id=s.rule_id, title=s.title, reason=s.reason)
        for s in verdict.skipped
    ]

    return report


# ── ② 항목별 리스크 ──────────────────────────────────────────────

def _risks(verdict: Verdict) -> List[RiskItem]:
    return [
        RiskItem(
            rule_id=v.rule_id,
            severity=v.severity.value,
            severity_label=v.severity.label,
            title=v.title,
            message=v.message,
            source=v.source,
            fields=list(v.fields),
            observed=dict(v.observed),
        )
        for v in verdict.sorted_violations()
    ]


# ── ③ 제출 기한 ──────────────────────────────────────────────────

def _deadline(
    bl: Dict[str, Optional[str]], lc: LCTerms, now: datetime
) -> Optional[Deadline]:
    """제시기한을 계산한다.

    UCP 600 Art.14(c): 선적일로부터 제시기간(기본 21일) 이내, 그리고 어떤
    경우에도 신용장 유효기일 이내. 둘 중 이른 날이 실질 기한이다.
    """
    shipped = parse_date(_clean(bl.get("on_board_date")) or "")
    expiry = parse_date(lc.expiry_date or "") if lc.expiry_date else None

    presentation_due: Optional[date] = None
    basis_parts: List[str] = []

    if shipped:
        days = lc.presentation_days or DEFAULT_PRESENTATION_DAYS
        presentation_due = (shipped + timedelta(days=days)).date()
        basis_parts.append(f"선적일 + {days}일(UCP 600 Art.14(c))")

    expiry_date = expiry.date() if expiry else None
    if expiry_date:
        basis_parts.append("신용장 유효기일(31D)")

    candidates = [d for d in (presentation_due, expiry_date) if d]
    if not candidates:
        return None

    effective = min(candidates)
    return Deadline(
        presentation_due=presentation_due,
        expiry=expiry_date,
        effective_due=effective,
        days_left=(effective - now.date()).days,
        basis=" / ".join(basis_parts) + " 중 이른 날",
    )


# ── ③ 체크리스트 ─────────────────────────────────────────────────

def _checklist(
    verdict: Verdict,
    bl: Dict[str, Optional[str]],
    lc: LCTerms,
    submitted: Optional[Sequence[str]],
    deadline: Optional[Deadline],
) -> List[ChecklistItem]:
    items: List[ChecklistItem] = []

    # 신용장이 요구한 서류(46A)를 실제로 제출했는지.
    required = list(lc.documents_required or [])
    if required:
        have = {_norm(d) for d in (submitted or [])}
        for doc in required:
            present = _norm(doc) in have or any(_norm(doc) in h for h in have)
            items.append(
                ChecklistItem(
                    label=f"요구 서류: {doc}",
                    done=present,
                    detail="" if present else "신용장 46A 가 요구하나 제출 목록에 없습니다.",
                )
            )
    else:
        items.append(
            ChecklistItem(
                label="요구 서류 목록(46A) 확인",
                done=False,
                detail="신용장 46A 가 입력되지 않아 서류 누락 여부를 확인하지 못했습니다.",
            )
        )

    # 핵심 필드가 채워졌는지.
    for name, label in (
        ("bl_no", "B/L 번호"),
        ("consignee", "수하인"),
        ("on_board_date", "본선적재일"),
        ("port_of_loading", "선적항"),
        ("port_of_discharge", "양하항"),
    ):
        value = _clean(bl.get(name))
        items.append(
            ChecklistItem(
                label=f"{label} 기재",
                done=bool(value),
                detail="" if value else "필수 기재사항이 비어 있습니다.",
            )
        )

    # 제시기한.
    if deadline and deadline.effective_due:
        if deadline.is_overdue:
            detail = f"기한({deadline.effective_due})이 {abs(deadline.days_left)}일 경과했습니다."
        else:
            detail = f"기한 {deadline.effective_due}까지 {deadline.days_left}일 남았습니다."
        items.append(
            ChecklistItem(label="제시기한 준수", done=not deadline.is_overdue, detail=detail)
        )
    else:
        items.append(
            ChecklistItem(
                label="제시기한 준수",
                done=False,
                detail="선적일 또는 신용장 유효기일이 없어 기한을 계산하지 못했습니다.",
            )
        )

    return items


# ── ④ 수정 권고 ──────────────────────────────────────────────────

def _recommendations(verdict: Verdict) -> List[Recommendation]:
    """위반을 심각도순으로 늘어놓고 조치문을 붙인다.

    remedy 가 비어 있는 룰은 제목을 조치문 자리에 쓴다. 권고 없는 위반이
    리포트에서 사라지면 사용자는 그 항목을 놓친다.
    """
    ordered = sorted(
        verdict.violations,
        key=lambda v: (_SEVERITY_ORDER.get(v.severity.value, 9), -v.weight, v.rule_id),
    )
    return [
        Recommendation(
            order=index,
            severity_label=v.severity.label,
            action=v.remedy or f"{v.title} 항목을 확인하고 정정하십시오.",
            target_fields=list(v.fields),
            source=v.source,
        )
        for index, v in enumerate(ordered, start=1)
    ]


# ── ⑤ 예상 심사 결과 ─────────────────────────────────────────────

def _outlook(verdict: Verdict, deadline: Optional[Deadline]) -> tuple[str, str]:
    """심사 결과 시나리오.

    확정 예측이 아니라 시나리오다. 문구에서 단정을 피하는 이유는, 지금
    확률의 출처가 학습된 모델이 아니라 룰 가중치이기 때문이다.
    """
    critical = verdict.counts.get("critical", 0)
    warning = verdict.counts.get("warning", 0)
    unchecked = len(verdict.skipped)

    if deadline and deadline.is_overdue:
        return (
            "제시기한 경과 — 수리 불가 가능성 높음",
            "제시기한이 지난 서류는 하자 여부와 무관하게 거절될 수 있습니다. "
            "매입은행에 즉시 문의하십시오.",
        )

    if critical:
        head = "하자 통보 및 재제출 요구 예상"
        detail = (
            f"치명 등급 위반 {critical}건은 통상 은행 심사에서 하자로 지적됩니다. "
            "제출 전에 정정하는 편이 재제출 비용보다 낮습니다."
        )
    elif warning:
        head = "심사역 재량 — 하자 지적 가능성 있음"
        detail = (
            f"경고 등급 {warning}건은 은행·심사역에 따라 판단이 갈립니다. "
            "정정이 어려우면 사전에 매입은행과 협의하십시오."
        )
    else:
        head = "수리 예상"
        detail = "검사한 항목에서 하자로 볼 만한 사항이 발견되지 않았습니다."

    if unchecked:
        detail += (
            f" 다만 자료 부족으로 검사하지 못한 항목이 {unchecked}건 있어, "
            "이 결과가 서류 전체를 보증하지는 않습니다."
        )
    return head, detail


# ── 보조 ─────────────────────────────────────────────────────────

def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text).upper() if ch.isalnum())


__all__ = ["build_report"]

"""
Verdict → Report 변환 (F4 본체).

전부 결정론이다. LLM 은 산문 요약만 얹고(narrative.py), 리포트의 골격·수치·
체크리스트·기한은 여기서 계산한다. 이렇게 가른 이유는 두 가지다.

  1. LLM 이 없거나 한도에 걸려도 리포트는 나와야 한다. 발표 중에 외부 API
     하나 때문에 산출물이 통째로 비는 상황을 만들지 않는다.
  2. 하자 확률·기한 같은 수치를 LLM 이 만들면 검증할 방법이 없다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ruleEngine import deadline as deadline_rules
from ruleEngine.types import LCTerms, Verdict

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

# 확률 대신 범위를 제시하는 보류 비율 (기획안 v2 5.4 "전체 필드의 20% 초과").
#
# **초과**다. 정확히 20% 는 점 확률을 유지한다 — 명세가 "초과"로 썼고,
# 경계에서 표기가 뒤집히면 필드 하나 차이로 리포트의 성격이 달라진다.
HOLD_RATIO_LIMIT = 0.20


def build_report(
    verdict: Verdict,
    bl: Dict[str, Optional[str]],
    lc: Optional[LCTerms] = None,
    submitted_documents: Optional[Sequence[str]] = None,
    as_of: Optional[datetime] = None,
    prediction: Optional[Any] = None,
    field_count: int = 0,
) -> Report:
    """검증 결과와 서류 정보를 리포트로 조립한다.

    `prediction` 은 `DefectPredictor.predict()` 결과다. 주면 **위험 점수만**
    그 값으로 바꾼다 — 하자 목록·체크리스트·기한은 그대로 룰엔진 결과다.

    역할을 이렇게 가르는 근거는 측정값이다. 이진 판정(하자냐 아니냐)은
    임계값을 어떻게 잡아도 룰이 모델을 이기고(F1 0.9210 vs 0.9158), 순위
    품질은 모델이 이긴다(AUC 0.9315 vs 0.9285). 그래서 판정은 룰이 하고
    모델은 순서만 매긴다. 룰은 조문을 인용할 수 있고 모델은 못 한다는
    점도 같은 방향이다.

    산출 출처는 `report.model` 에 남아 PDF 각주에 그대로 찍힌다. 5절이
    기록한 "리포트 출처 거짓 표기" 결함과 같은 이유로 이 표기는 정확해야
    한다 — 모델이 없어 룰 가중치로 떨어졌으면 `rules-v1` 이어야 한다.
    """
    now = as_of or datetime.now()
    lc = lc or LCTerms()

    report = Report(
        bl_no=_clean(bl.get("bl_no")),
        lc_no=lc.lc_no,
        generated_at=now.date(),
        defect_probability=(
            prediction.probability if prediction else verdict.defect_probability
        ),
        counts=verdict.counts,
        model=prediction.model if prediction else verdict.model,
        # 위험 점수는 모델이 낼 수 있어도 하자 목록·조문 인용은 언제나
        # 룰엔진 결과다. 그래서 카탈로그 신원은 prediction 유무와 무관하게
        # verdict 에서 온다.
        rule_catalog=verdict.catalog,
        cross_rule_catalog=verdict.cross_catalog,
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
    report.held = [
        UncheckedItem(rule_id=h.rule_id, title=h.title, reason=h.reason)
        for h in verdict.held
    ]
    _apply_hold_gate(report, verdict, bl, field_count)

    return report


# ── ① 판정 보류 게이트 ───────────────────────────────────────────

def _apply_hold_gate(
    report: Report, verdict, bl: Dict[str, Optional[str]], field_count: int
) -> None:
    """보류가 많으면 확률 대신 범위를 쓰게 표시한다 (기획안 v2 5.4).

    **분모는 필드 수이고 분자는 보류된 룰이 참조하는 필드 수다.** 룰 수로
    세지 않는 이유는 명세가 "전체 필드의 20% 초과"로 필드를 단위로 썼기
    때문이고, 그 편이 실제로도 맞다 — 한 필드가 못 미더워서 룰 5건이 보류될
    수 있는데 그걸 5로 세면 필드 하나가 리포트 전체의 성격을 뒤집는다.

    `field_count` 를 인자로 받는 이유는 **분모가 서류 종류마다 다르기**
    때문이다. 선하증권은 15 필드지만 송장·포장명세서는 다르고, 리포트는
    그 명세를 들고 있지 않다. 주지 않으면 `bl` 의 키 수로 떨어진다.
    """
    # 하한은 리포트가 쓰는 확률이다. `verdict.probability_range` 를 그대로
    # 쓰면 모델이 낸 확률(prediction)로 바꿔 놓은 값과 범위가 어긋난다 —
    # 요약에는 0.62 가 찍히는데 범위는 0.30~0.55 로 나오는 식이다.
    low = report.defect_probability
    high = round(min(1.0, low + sum(h.weight for h in verdict.held)), 4)
    report.probability_range = (low, high)

    held_fields = {name for h in verdict.held for name in h.fields}
    report.held_field_count = len(held_fields)

    total = field_count or len(bl) or 0
    report.hold_ratio = round(len(held_fields) / total, 4) if total else 0.0

    if report.hold_ratio <= HOLD_RATIO_LIMIT:
        return

    low, high = report.probability_range
    report.confidence_warning = (
        f"입력 필드 {total}개 중 {len(held_fields)}개가 확인이 필요한 상태라 "
        f"관련 검사 {len(verdict.held)}건의 판정을 보류했습니다. "
        f"하자 확률을 하나의 값으로 제시하지 않고 {low:.2f}~{high:.2f} 범위로 "
        "표시합니다. 해당 필드를 확인한 뒤 다시 검증하십시오."
    )


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
    """제시기한. **계산은 룰엔진이 한다.**

    리포트가 직접 계산하던 것을 `ruleEngine.deadline` 으로 옮겼다. 같은 조문
    (UCP 600 Art.14(c))에서 나온 같은 날짜를 룰과 리포트가 각자 계산하고
    있었고, 실제로 어긋나 있었다 — 룰은 선적일을 `on_board_date` →
    `date_of_issue` 순으로 찾는데 여기는 `on_board_date` 만 봤다. 본선적재일
    없이 발행일만 있는 서류에서 **룰은 하자로 잡고 리포트는 "기한을 계산하지
    못했습니다"** 를 띄웠다.
    """
    return deadline_rules.compute(bl, lc, as_of=now)


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
    # 보류는 평가불가와 따로 말한다. 사용자가 할 일이 다르다 — 평가불가는
    # 서류를 더 올려야 풀리고, 보류는 그 필드를 확인해야 풀린다.
    if verdict.held:
        detail += (
            f" 또한 확인이 필요한 필드 때문에 판정을 보류한 항목이 "
            f"{len(verdict.held)}건 있습니다."
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

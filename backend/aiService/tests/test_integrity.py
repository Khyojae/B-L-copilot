"""리포트 산문의 출력 무결성 검사 (22번 · v2 5.4 · 5.7)."""

from __future__ import annotations

from datetime import date

import pytest

from report import IntegrityReport, check_narrative
from report.model import Recommendation, Report, RiskItem, UncheckedItem
from report.narrative import (
    MAX_NARRATIVE_ATTEMPTS,
    LLMNarrator,
    TemplateNarrator,
)


def make_report() -> Report:
    report = Report(
        bl_no="HG290309",
        lc_no="LC-2026-001",
        generated_at=date(2026, 6, 10),
        defect_probability=0.35,
        counts={"critical": 1, "warning": 2, "info": 0},
        model="rules-v1",
    )
    report.risks = [
        RiskItem(
            rule_id="D003",
            severity="critical",
            severity_label="치명",
            title="선적항 불일치",
            message="선적항(SHANGHAI, CHINA)이 L/C 지정(PUSAN)과 다릅니다.",
            source="UCP 600 Art.14(d) — 서류의 기재는 L/C 조건과 저촉되지 않아야 한다.",
            fields=["port_of_loading"],
            observed={"bl": "SHANGHAI, CHINA", "lc": "PUSAN"},
        ),
    ]
    report.recommendations = [
        Recommendation(
            order=1,
            severity_label="치명",
            action="선적항을 L/C 지정 항구로 정정하십시오.",
            target_fields=["port_of_loading"],
            source="UCP 600 Art.14(d)",
        ),
    ]
    report.unchecked = [
        UncheckedItem(rule_id="D007", title="중량 한도 초과", reason="L/C 에 한도가 없습니다"),
    ]
    return report


class TestCheckNarrative:
    def test_리포트에_있는_수치는_통과한다(self):
        report = make_report()

        result = check_narrative(
            report,
            "치명 하자 1건이 발견되었습니다.",
            "위험 점수는 0.35 이며 경고 2건이 함께 있습니다.",
        )

        assert result.ok, result.describe()

    def test_지어낸_수치를_잡는다(self):
        report = make_report()

        result = check_narrative(report, "", "위험 점수는 0.87 로 추정됩니다.")

        assert not result.ok
        assert "0.87" in result.unknown_numbers

    def test_백분율_표기를_지어낸_것으로_보지_않는다(self):
        # 0.35 를 "35%" 로 쓰는 것은 같은 값을 다르게 적은 것이다.
        report = make_report()

        result = check_narrative(report, "", "하자 위험은 35% 수준입니다.")

        assert result.ok, result.describe()

    def test_날짜를_풀어_써도_통과한다(self):
        report = make_report()

        result = check_narrative(report, "", "이 리포트는 2026년 6월 10일에 생성되었습니다.")

        assert result.ok, result.describe()

    def test_판정에_없는_룰_ID를_잡는다(self):
        report = make_report()

        result = check_narrative(report, "", "D999 규칙에 따라 하자가 예상됩니다.")

        assert not result.ok
        assert result.unknown_rule_ids == ["D999"]

    def test_판정에_있는_룰_ID는_통과한다(self):
        report = make_report()

        result = check_narrative(report, "", "D003 항목을 먼저 정정하십시오.")

        assert result.ok, result.describe()

    def test_인용하지_않은_조문을_잡는다(self):
        report = make_report()

        result = check_narrative(report, "", "UCP 600 Art.20(b) 위반이 예상됩니다.")

        assert not result.ok
        assert result.unknown_articles

    def test_인용한_조문은_표기가_달라도_통과한다(self):
        report = make_report()

        result = check_narrative(report, "", "UCP 600 Art. 14 (d) 를 근거로 합니다.")

        assert result.ok, result.describe()

    def test_룰_ID의_숫자를_수치로_세지_않는다(self):
        # D003 의 3 이나 Art.14 의 14 가 '근거 없는 숫자'로 잡히면 안 된다.
        report = make_report()

        result = check_narrative(report, "", "D003 은 UCP 600 Art.14(d) 에 근거합니다.")

        assert result.unknown_numbers == []

    def test_서사가_비면_통과다(self):
        # LLM 을 아예 안 쓴 경우다. 검사할 것이 없는 것과 위반은 다르다.
        assert check_narrative(make_report(), "", "").ok
        assert check_narrative(make_report(), None, None).ok

    def test_템플릿_서사는_언제나_통과한다(self):
        """검사기 자신의 건전성 확인 — 데이터에서 만든 문장이 걸리면 검사기가 틀린 것이다."""
        report = make_report()
        summary = TemplateNarrator().summarize(report)

        result = check_narrative(report, summary.headline, summary.narrative)

        assert result.ok, result.describe()


class TestIntegrityReport:
    def test_통과면_설명이_통과다(self):
        assert IntegrityReport().describe() == "통과"

    def test_걸린_것을_설명에_담는다(self):
        result = IntegrityReport(unknown_numbers=["0.87"], unknown_rule_ids=["D999"])

        assert "0.87" in result.describe()
        assert "D999" in result.describe()


class TestLLMNarratorRetry:
    def test_통과하면_그대로_채택한다(self):
        calls = []

        def complete(system, user):
            calls.append(system)
            return "치명 하자 1건이 발견되었습니다.\n위험 점수는 0.35 입니다."

        summary = LLMNarrator(complete).summarize(make_report())

        assert summary.source == "llm"
        assert len(calls) == 1

    def test_무결성에_걸리면_재생성한다(self):
        calls = []

        def complete(system, user):
            calls.append(system)
            if len(calls) == 1:
                return "위험 점수는 0.87 입니다.\n곧 하자가 납니다."
            return "치명 하자 1건이 발견되었습니다.\n위험 점수는 0.35 입니다."

        summary = LLMNarrator(complete).summarize(make_report())

        assert summary.source == "llm"
        assert "0.35" in summary.narrative
        assert len(calls) == 2
        # 재생성 지시에는 무엇이 걸렸는지가 들어간다. 같은 지시로 다시 부르면
        # 같은 문장이 나올 확률이 높다.
        assert "0.87" in calls[1]

    def test_계속_걸리면_템플릿으로_떨어진다(self):
        calls = []

        def complete(system, user):
            calls.append(system)
            return "위험 점수는 0.87 입니다.\n하자율 99% 가 예상됩니다."

        summary = LLMNarrator(complete).summarize(make_report())

        assert summary.source == "template"
        assert len(calls) == MAX_NARRATIVE_ATTEMPTS
        # 템플릿 서사는 데이터에서 나오므로 검사를 통과한다.
        report = make_report()
        assert check_narrative(report, summary.headline, summary.narrative).ok

    def test_호출이_터지면_템플릿이다(self):
        def complete(system, user):
            raise RuntimeError("API 한도")

        summary = LLMNarrator(complete).summarize(make_report())

        assert summary.source == "template"

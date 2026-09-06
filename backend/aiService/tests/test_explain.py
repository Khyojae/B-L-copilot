"""
F7 AI 판정 설명 테스트.

보고서(수정17) 요구: "조문 원문과 현재값, 기대값을 컨텍스트로 조립해
3단 문장을 한국어 영어 동일 근거로 생성", "인용 ID 대조 검증기와 2회
재생성 실패 시 템플릿 폴백, 판정 30건 회귀 평가로 인용 무결성 통과율
확보".
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mlModel.synth import SyntheticGenerator
from report import (
    TemplateExplainer,
    TemplateNarrator,
    apply_explanations,
    apply_narrative,
    build_report,
    check_narrative,
)
from report.explain import Explanation, LLMExplainer
from ruleEngine import LCTerms, RuleEngine

AS_OF = datetime(2026, 5, 25)


def clean_bl() -> dict:
    return {
        "bl_no": "MAEU123456789",
        "shipper": "HOMINAI CO LTD",
        "consignee": "TO ORDER OF KEB HANA BANK",
        "notify_party": "ABC IMPORT INC",
        "port_of_loading": "BUSAN, KOREA",
        "port_of_discharge": "LOS ANGELES, USA",
        "description_of_goods": "ELECTRONIC COMPONENTS",
        "gross_weight": "12000 KGS",
        "on_board_date": "2026-05-10",
        "date_of_issue": "2026-05-11",
    }


def matching_lc() -> LCTerms:
    return LCTerms(
        lc_no="LC-2026-0001",
        latest_shipment_date="2026-05-15",
        expiry_date="2026-06-05",
        port_of_loading="INCHEON, KOREA",  # 불일치 → 위반 유발
        port_of_discharge="LOS ANGELES, USA",
        description_of_goods="ELECTRONIC COMPONENTS",
    )


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


def make_report(engine: RuleEngine):
    bl, lc = clean_bl(), matching_lc()
    verdict = engine.verify(bl, lc, as_of=AS_OF)
    assert verdict.violations, "테스트가 위반 0건이면 설명 대상이 없다"
    report = build_report(verdict, bl, lc, as_of=AS_OF)
    return apply_narrative(report, TemplateNarrator())


class Test템플릿_경로:
    """LLM 없이도(폐쇄망 프로파일) 3단 구성과 무결성이 성립해야 한다."""

    def test_위반마다_설명이_하나씩_붙는다(self, engine):
        report = make_report(engine)
        report = apply_explanations(report, TemplateExplainer())

        assert len(report.explanations) == len(report.risks)
        assert all(isinstance(e, Explanation) for e in report.explanations)
        assert all(e.origin == "template" for e in report.explanations)

    def test_3단_구성_조문_현재값_기대값이_들어간다(self, engine):
        report = make_report(engine)
        report = apply_explanations(report, TemplateExplainer())

        # port_of_loading 위반은 observed 에 bl(현재값)·lc(기대값) 쌍을 갖고
        # 있고, 두 언어 설명 모두에 그 값이 나와야 "같은 근거"다.
        port_risk = next(r for r in report.risks if "port_of_loading" in r.fields)
        exp = next(e for e in report.explanations if e.rule_id == port_risk.rule_id)

        assert port_risk.source in exp.body_ko
        assert port_risk.observed.get("bl", "") in exp.body_ko
        assert port_risk.observed.get("lc", "") in exp.body_en

    def test_한국어_영어_둘_다_인용_무결성을_통과한다(self, engine):
        report = make_report(engine)
        report = apply_explanations(report, TemplateExplainer())

        for exp in report.explanations:
            result = check_narrative(report, exp.body_ko, exp.body_en)
            assert result.ok, result.describe()


class TestLLM_경로_실패시_템플릿_폴백:
    def test_completion_예외면_템플릿으로_떨어진다(self, engine):
        report = make_report(engine)

        def boom(system, user):
            raise RuntimeError("네트워크 없음")

        explainer = LLMExplainer(boom)
        report = apply_explanations(report, explainer)

        assert report.explanations
        assert all(e.origin == "template" for e in report.explanations)

    def test_지어낸_숫자는_2회_재시도_후_템플릿으로_떨어진다(self, engine):
        report = make_report(engine)
        calls = {"n": 0}

        def fabricate(system, user):
            calls["n"] += 1
            return "근거 없는 99.9% 확률입니다.\nA fabricated 99.9% figure."

        explainer = LLMExplainer(fabricate)
        n_risks = len(report.risks)
        report = apply_explanations(report, explainer)

        # 위반마다 MAX_EXPLANATION_ATTEMPTS(2)회씩 재시도한다.
        assert calls["n"] == 2 * n_risks
        assert all(e.origin == "template" for e in report.explanations)


class Test회귀_평가_30건:
    """보고서가 요구한 수치 — 판정 30건에서 인용 무결성 통과율을 잰다.

    템플릿 경로는 구조상 100% 가 보장된다(observed·source·rule_id 를
    그대로 옮길 뿐 새 사실을 만들지 않으므로). 그 사실 자체를 assert 한다
    — LLM 키가 없는 CI 환경에서도 이 회귀 평가가 항상 돈다.
    """

    def test_30건_템플릿_설명의_인용_무결성_통과율(self):
        engine = RuleEngine()
        generator = SyntheticGenerator(seed=11)
        samples = generator.generate(30, defect_ratio=1.0)

        total = 0
        passed = 0
        for sample in samples:
            verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
            if not verdict.violations:
                continue
            report = build_report(verdict, sample.bl.to_dict(), sample.lc, as_of=sample.as_of)
            report = apply_narrative(report, TemplateNarrator())
            report = apply_explanations(report, TemplateExplainer())

            for exp in report.explanations:
                total += 1
                result = check_narrative(report, exp.body_ko, exp.body_en)
                if result.ok:
                    passed += 1
                else:
                    print(f"[test] 인용 무결성 실패 {exp.rule_id}: {result.describe()}")

        assert total > 0, "30건 중 위반이 하나도 없었다 — defect_ratio 를 확인할 것"
        rate = passed / total
        print(f"[test] 30건 회귀 평가 — 판정 {total}건 중 통과 {passed}건 ({rate:.2%})")
        assert rate == 1.0

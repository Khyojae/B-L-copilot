"""판정 보류와 확률 범위 (기획안 v2 5.3 예외 · 5.4 엣지 케이스).

명세가 두 절에 나눠 쓴 하나의 규칙이다. 5.3 이 "필수 확인 필드가 남아
있으면 해당 필드 관련 룰은 판정 보류로 표기하고 확률 산출에서 제외"를
정하고, 5.4 가 "판정 보류 항목이 많은 경우(전체 필드의 20% 초과) 확률
대신 범위를 제시"를 정한다.
"""

from __future__ import annotations

from report.builder import HOLD_RATIO_LIMIT, build_report
from report.narrative import TemplateNarrator
from report.integrity import check_narrative
from ruleEngine import RuleEngine
from ruleEngine.types import LCTerms

# 필드 하나씩만 보는 최소 카탈로그. 실제 rules.yaml 로 재면 룰이 어느 필드를
# 참조하는지에 테스트가 묶여, 룰을 고칠 때마다 여기가 깨진다.
_RULES = [
    {
        "id": "T001", "title": "B/L 번호 필수", "severity": "critical",
        "check": "required", "source": "UCP 600 Art.20(a)", "weight": 0.4,
        "message": "B/L 번호가 없습니다.", "fields": ["bl_no"],
    },
    {
        "id": "T002", "title": "수하인 필수", "severity": "warning",
        "check": "required", "source": "UCP 600 Art.14(d)", "weight": 0.3,
        "message": "수하인이 없습니다.", "fields": ["consignee"],
    },
    {
        "id": "T003", "title": "선적항 필수", "severity": "info",
        "check": "required", "source": "UCP 600 Art.20(a)(iii)", "weight": 0.2,
        "message": "선적항이 없습니다.", "fields": ["port_of_loading"],
    },
]

_BL = {"bl_no": "HG290309", "consignee": "ACME", "port_of_loading": "BUSAN"}


def _verify(held=None):
    return RuleEngine(rules=_RULES).verify(_BL, LCTerms(), held_fields=held)


class TestHeldRules:
    def test_보류된_룰은_돌지_않는다(self):
        verdict = _verify(held=["consignee"])

        assert [h.rule_id for h in verdict.held] == ["T002"]
        assert verdict.evaluated_count == 2

    def test_보류는_평가불가와_섞이지_않는다(self):
        # 사용자가 할 일이 다르다 — 평가불가는 서류를 더 올려야 풀리고,
        # 보류는 그 필드를 확인해야 풀린다.
        verdict = _verify(held=["consignee"])

        assert not verdict.skipped
        assert verdict.to_dict()["held_count"] == 1

    def test_보류_사유가_어느_필드_때문인지_말한다(self):
        held = _verify(held=["consignee"]).held[0]

        assert "consignee" in held.reason
        assert "보류" in held.reason

    def test_보류된_룰은_확률에서_빠진다(self):
        # 값이 비어 T002 가 위반이 될 상황인데 보류하면 가중치가 안 잡힌다.
        blank = dict(_BL, consignee=None)
        engine = RuleEngine(rules=_RULES)

        assert engine.verify(blank, LCTerms()).defect_probability == 0.3
        assert (
            engine.verify(blank, LCTerms(), held_fields=["consignee"])
            .defect_probability == 0.0
        )

    def test_범위의_상한은_보류_가중치를_더한_값이다(self):
        verdict = _verify(held=["consignee", "port_of_loading"])

        # 위반 0건이므로 하한 0.0, 보류 가중치 0.3 + 0.2 가 상한이다.
        assert verdict.probability_range == (0.0, 0.5)

    def test_보류가_없으면_범위는_한_점이다(self):
        verdict = _verify()

        low, high = verdict.probability_range
        assert low == high


class TestHoldGate:
    """보류 비율이 20% 를 넘으면 확률 대신 범위를 쓴다."""

    def _report(self, held, field_count):
        verdict = _verify(held=held)
        return build_report(verdict, _BL, LCTerms(), field_count=field_count)

    def test_20퍼센트_초과면_범위로_바뀐다(self):
        # 5 필드 중 2 보류 = 40%
        report = self._report(["consignee", "port_of_loading"], field_count=5)

        assert report.hold_ratio == 0.4
        assert report.probability_is_ranged
        assert report.confidence_warning
        assert report.probability_range == (0.0, 0.5)

    def test_정확히_20퍼센트는_점_확률을_유지한다(self):
        # 명세가 "초과"로 썼다. 경계에서 표기가 뒤집히면 필드 하나 차이로
        # 리포트의 성격이 달라진다.
        report = self._report(["consignee"], field_count=5)

        assert report.hold_ratio == HOLD_RATIO_LIMIT
        assert not report.probability_is_ranged
        assert not report.confidence_warning

    def test_보류가_없으면_경고도_없다(self):
        report = self._report(None, field_count=5)

        assert report.hold_ratio == 0.0
        assert not report.probability_is_ranged
        assert report.held == []

    def test_분모는_필드_수지_룰_수가_아니다(self):
        # 한 필드가 못 미더워 룰 5건이 보류돼도 필드 하나로 센다.
        rules = _RULES + [
            dict(_RULES[1], id=f"T10{i}") for i in range(4)
        ]
        verdict = RuleEngine(rules=rules).verify(
            _BL, LCTerms(), held_fields=["consignee"]
        )
        report = build_report(verdict, _BL, LCTerms(), field_count=5)

        assert len(verdict.held) == 5
        assert report.held_field_count == 1
        assert report.hold_ratio == 0.2

    def test_보류_항목이_리포트에_실린다(self):
        # 5.3: "보류 건수를 리포트에 명시한다"
        report = self._report(["consignee"], field_count=5)

        assert [h.rule_id for h in report.held] == ["T002"]
        assert "보류" in report.outlook_detail


class TestNarrativeWithHold:
    def _ranged_report(self):
        verdict = _verify(held=["consignee", "port_of_loading"])
        return build_report(verdict, _BL, LCTerms(), field_count=5)

    def test_템플릿_산문이_범위로_말한다(self):
        summary = TemplateNarrator().summarize(self._ranged_report())

        assert "0.00~0.50" in summary.narrative
        assert "보류" in summary.narrative

    def test_범위_산문이_무결성_검사를_통과한다(self):
        # 하한·상한을 허용 집합에 넣지 않으면 정상 문장이 전부 걸려
        # 리포트가 통째로 템플릿으로 떨어진다 — 22번과 정반대의 실패다.
        report = self._ranged_report()
        summary = TemplateNarrator().summarize(report)

        result = check_narrative(report, summary.headline, summary.narrative)

        assert result.ok, result.describe()

    def test_보류_상태에서는_점_확률을_LLM에_주지_않는다(self):
        # 사실 목록에 없는 값은 쓸 수 없다. 점 확률을 넣으면 LLM 이 그것을
        # 확정된 확률로 서술하는데, 범위로 내라고 한 이유가 그 값을 단정할
        # 수 없어서다.
        from report.narrative import _render_facts

        facts = _render_facts(self._ranged_report())

        assert "위험 점수 범위" in facts
        assert "위험 점수:" not in facts

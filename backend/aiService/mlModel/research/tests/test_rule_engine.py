"""룰엔진 전수 검사.

F3 하자 예측 시스템의 핵심 구성요소인 룰엔진이 설계대로 동작하는지 검증한다.
- 카탈로그 로드 및 검증
- 삼항 평가 결과(통과/위반/평가불가)
- 입력 형식 처리
- 시각 의존성(as_of) 주입
- 함수별 관찰된 동작 고정화
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pytest

from f3_research.ruleEngine import (
    CheckOutcome,
    LCTerms,
    RuleCatalogError,
    RuleEngine,
    Severity,
    Verdict,
    Violation,
    checks,
    engine,
)


# ── 카탈로그 로드 ────────────────────────────────────────────────────


class Test카탈로그_로드:
    """룰 카탈로그 로드 및 검증."""

    def test_기본_카탈로그는_21개_룰을_로드한다(self):
        """기획안과 rules.yaml 이 정의하는 21개 룰이 모두 로드되어야 한다."""
        engine_instance = RuleEngine()
        assert len(engine_instance) == 21
        # 설계상 이 개수가 변하면 다른 테스트들도 영향을 받으므로 명시적으로 고정한다.

    def test_룰_id는_유일하다(self):
        """같은 id 를 가진 룰이 두 개 이상 있으면 안 된다."""
        engine_instance = RuleEngine()
        rule_ids = engine_instance.rule_ids
        assert len(rule_ids) == len(set(rule_ids)), "중복된 id 가 있습니다"

    def test_모든_룰의_check는_레지스트리에_등록되어_있다(self):
        """rules.yaml 의 모든 룰이 references 하는 check 가 checks.REGISTRY 에 있어야 한다."""
        engine_instance = RuleEngine()
        for rule in engine_instance.rules:
            check_name = rule["check"]
            assert check_name in checks.REGISTRY, (
                f"룰 {rule['id']}: check '{check_name}' 이 레지스트리에 없습니다"
            )

    def test_필수_키_누락_시_RuleCatalogError_발생(self):
        """카탈로그 항목에서 필수 키가 없으면 로드 시점에 터진다."""
        # 필수 키: id, title, severity, check, source, message
        incomplete_rule = {
            "id": "TEST001",
            "title": "Test",
            "severity": "critical",
            # check 가 없다
            "source": "Test source",
            "message": "Test message",
        }
        with pytest.raises(RuleCatalogError):
            RuleEngine(rules=[incomplete_rule])

    def test_알_수_없는_check_발생_시_RuleCatalogError_발생(self):
        """카탈로그의 check 값이 REGISTRY 에 없으면 로드 시점에 터진다."""
        bad_rule = {
            "id": "TEST002",
            "title": "Test",
            "severity": "critical",
            "check": "unknown_check_function",
            "source": "Test source",
            "message": "Test message",
        }
        with pytest.raises(RuleCatalogError):
            RuleEngine(rules=[bad_rule])


# ── 삼항 평가 결과 (passed / violated / not_evaluated) ────────────────


class Test삼항_평가:
    """룰의 세 가지 평가 상태가 올바르게 구분되는지."""

    @pytest.fixture
    def 엔진(self):
        return RuleEngine()

    def test_필수_필드_누락_시_위반(self, 엔진):
        """B/L 에서 필수 필드가 없으면 해당 required 룰이 위반된다."""
        # D001: B/L 번호 누락
        bl = {"consignee": "Test Consignee"}  # bl_no 가 없다
        lc = LCTerms()
        verdict = 엔진.verify(bl, lc)

        d001_violations = [v for v in verdict.violations if v.rule_id == "D001"]
        assert len(d001_violations) > 0, "D001 (B/L 번호 누락) 위반이 기록되지 않았습니다"

    def test_완전한_B_L과_LC_항목_적음_위반(self, 엔진):
        """정상적으로 채워진 B/L 과 최소 L/C 조건이면 위반이 거의 없어야 한다."""
        bl = {
            "bl_no": "BL123456789",
            "consignee": "Test Consignee",
            "port_of_loading": "SHANGHAI",
            "port_of_discharge": "ROTTERDAM",
            "shipper": "Test Shipper",
            "notify_party": "Test Notify",
            "vessel": "Test Vessel",
            "on_board_date": "2024-01-15",
            "date_of_issue": "2024-01-15",
            "description_of_goods": "General Cargo",
            "gross_weight": "100 KG",
        }
        lc = LCTerms()  # 조건이 없으면 대부분 평가불가
        verdict = 엔진.verify(bl, lc)

        # L/C 조건이 없어 대조 룰들은 평가불가가 되지만, 필수 필드 룰은 통과해야 한다
        critical_violations = verdict.by_severity(Severity.CRITICAL)
        assert len(critical_violations) <= 3, (
            f"정상 B/L 이 과도한 위반(critical)을 보입니다: {len(critical_violations)}"
        )
        # evaluated_count 는 양수여야 한다 (최소한 필수 필드 몇 개는 평가됨)
        assert verdict.evaluated_count > 0

    def test_LC_None_일_때_LC_의존_룰은_skip되지_위반_아님(self, 엔진):
        """L/C 가 None 이거나 조건이 없으면 L/C-dependent 룰들은 violated 가 아니라
        skipped 에 들어가야 한다. 이는 설계의 핵심: 입력 부족이 '하자 없음'으로 읽히지 않도록."""
        bl = {
            "bl_no": "BL123456789",
            "consignee": "Test Consignee",
            "port_of_loading": "SHANGHAI",
            "port_of_discharge": "ROTTERDAM",
            "shipper": "Test Shipper",
            "notify_party": "Test Notify",
            "vessel": "Test Vessel",
            "on_board_date": "2024-01-15",
            "date_of_issue": "2024-01-15",
            "description_of_goods": "General Cargo",
        }
        # L/C 가 None — 모든 L/C 조건이 미명시
        verdict = 엔진.verify(bl, None)

        # L/C 조건이 없으면 평가불가 룰들이 많아진다
        skipped_count = len(verdict.skipped)
        assert skipped_count > 0, "L/C 미명시일 때 skipped 룰이 없습니다"

        # 하지만 그들은 violations 에 들어가지 않아야 한다
        violation_ids = {v.rule_id for v in verdict.violations}
        skipped_ids = {s.rule_id for s in verdict.skipped}
        overlap = violation_ids & skipped_ids
        assert len(overlap) == 0, (
            f"같은 룰이 violations 과 skipped 에 동시에 있습니다: {overlap}"
        )

    def test_평가_건수와_skip_건수_합계는_전체_룰_개수(self, 엔진):
        """모든 룰은 세 상태 중 하나다: passed / violated / not_evaluated.
        evaluated_count (passed + violated) + len(skipped) == 전체 룰 개수."""
        bl = {
            "bl_no": "BL123456789",
            "consignee": "Test Consignee",
            "port_of_loading": "SHANGHAI",
            "port_of_discharge": "ROTTERDAM",
            "shipper": "Test Shipper",
            "notify_party": "Test Notify",
            "vessel": "Test Vessel",
            "on_board_date": "2024-01-15",
            "date_of_issue": "2024-01-15",
            "description_of_goods": "General Cargo",
        }
        lc = LCTerms()
        verdict = 엔진.verify(bl, lc)

        total = verdict.evaluated_count + len(verdict.skipped)
        assert total == len(엔진), (
            f"룰 결과가 분할되지 않습니다: "
            f"evaluated {verdict.evaluated_count} + skipped {len(verdict.skipped)} "
            f"!= total {len(엔진)}"
        )


# ── 입력 형식 처리 ────────────────────────────────────────────────────


class Test입력_형식:
    """verify() 메서드의 입력 형식 수용 범위."""

    @pytest.fixture
    def 엔진(self):
        return RuleEngine()

    def test_dict_입력을_받는다(self, 엔진):
        """verify() 는 plain dict 를 입력으로 받는다."""
        bl_dict = {
            "bl_no": "BL001",
            "consignee": "Test",
            "port_of_loading": "PORT1",
            "port_of_discharge": "PORT2",
        }
        lc = LCTerms()
        # 예외 없이 실행된다
        verdict = 엔진.verify(bl_dict, lc)
        assert isinstance(verdict, Verdict)

    def test_dataclass_입력을_받는다(self, 엔진):
        """verify() 는 __dataclass_fields__ 를 가진 dataclass 객체를 받는다."""

        @dataclass
        class BLFields:
            bl_no: Optional[str] = None
            consignee: Optional[str] = None
            port_of_loading: Optional[str] = None
            port_of_discharge: Optional[str] = None

        bl_obj = BLFields(
            bl_no="BL001",
            consignee="Test",
            port_of_loading="PORT1",
            port_of_discharge="PORT2",
        )
        lc = LCTerms()
        verdict = 엔진.verify(bl_obj, lc)
        assert isinstance(verdict, Verdict)

    def test_지원하지_않는_형식은_TypeError_발생(self, 엔진):
        """list, string, int 등 지원하지 않는 형식은 TypeError 를 일으킨다."""
        lc = LCTerms()

        # list
        with pytest.raises(TypeError):
            엔진.verify([1, 2, 3], lc)

        # string
        with pytest.raises(TypeError):
            엔진.verify("not_a_dict", lc)

        # int
        with pytest.raises(TypeError):
            엔진.verify(123, lc)


# ── 시각 의존성 (as_of) 주입 ────────────────────────────────────────────


class Test시각_의존성:
    """presentation_period 룰이 as_of 파라미터를 존중하는지."""

    @pytest.fixture
    def 엔진(self):
        return RuleEngine()

    def test_다른_as_of는_다른_결과를_낸다(self, 엔진):
        """같은 B/L 을 두 가지 다른 as_of 시각으로 평가하면 결과가 달라야 한다.
        선적일로부터의 경과일 계산이 as_of 를 이용하므로, as_of 가 바뀌면
        presentation_period 룰의 평가 결과가 바뀐다."""
        bl = {
            "bl_no": "BL001",
            "consignee": "Test",
            "port_of_loading": "PORT1",
            "port_of_discharge": "PORT2",
            "shipper": "Test",
            "notify_party": "Test",
            "vessel": "Test",
            "on_board_date": "2024-01-01",  # 선적일
            "date_of_issue": "2024-01-01",
        }
        lc = LCTerms(presentation_days=21)

        # as_of = 2024-01-15 (선적일로부터 14일 경과 — 제시기간 내)
        as_of_early = datetime(2024, 1, 15)
        verdict_early = 엔진.verify(bl, lc, as_of=as_of_early)
        d018_early = [v for v in verdict_early.violations if v.rule_id == "D018"]

        # as_of = 2024-02-01 (선적일로부터 31일 경과 — 제시기간 초과)
        as_of_late = datetime(2024, 2, 1)
        verdict_late = 엔진.verify(bl, lc, as_of=as_of_late)
        d018_late = [v for v in verdict_late.violations if v.rule_id == "D018"]

        # 하나는 통과, 하나는 위반이어야 한다 (또는 상태가 달라야 한다)
        # 실제로는 as_of_early 일 때는 평가되지만 위반하지 않고,
        # as_of_late 일 때는 위반해야 한다.
        assert len(d018_early) == 0, (
            "제시기간 내(14일)일 때 D018 이 위반되면 안 됩니다"
        )
        assert len(d018_late) > 0, (
            "제시기간 초과(31일)일 때 D018 이 위반되어야 합니다"
        )


# ── 관찰된 동작 고정화 ────────────────────────────────────────────────


class Test관찰된_동작:
    """후속 작업이 의존하는 기존 동작들을 명시적으로 고정화한다."""

    def test_tokens_match_괄호_접미사는_무시한다(self):
        """_tokens_match("LOS ANGELES, USA (ALT)", "LOS ANGELES, USA") == True.
        괄호로 된 접미사(주로 대체 이름)가 일치 판정에 방해가 되지 않는다."""
        result = checks._tokens_match("LOS ANGELES, USA (ALT)", "LOS ANGELES, USA")
        assert result is True, (
            "괄호 접미사가 있어도 항구명 일치로 판정되어야 합니다"
        )

    def test_parse_quantity_단위_접미사_필수(self):
        """parse_quantity() 는 값에 단위 접미사가 있어야 인식한다.
        - parse_quantity("512.0", "KG") == None (단위 없음)
        - parse_quantity("512.0 KG", "KG") == 512.0 (단위 있음)

        이는 "5" 같은 값이 "1.5 KG"로 오독되는 것을 방지한다."""
        # 단위 없음
        result_no_unit = checks.parse_quantity("512.0", "KG")
        assert result_no_unit is None, (
            "단위 접미사 없는 값('512.0')은 파싱될 수 없어야 합니다"
        )

        # 단위 있음
        result_with_unit = checks.parse_quantity("512.0 KG", "KG")
        assert result_with_unit == 512.0, (
            "올바른 단위 형식('512.0 KG')은 파싱되어야 합니다"
        )

    def test_defect_probability_1_0_에서_clipping(self):
        """Verdict.defect_probability 는 위반의 가중치 합을 1.0 에서 자른다.
        확률이 아니라 위험 점수이므로, 1.0 을 상한으로 본다.

        예: weight [0.5, 0.5, 0.3] 합 = 1.3 → 확률 = 1.0"""
        # 가중치 합이 1.0 을 초과하는 위반들을 생성
        violation1 = Violation(
            rule_id="V1",
            severity=Severity.CRITICAL,
            title="Test 1",
            message="Test",
            weight=0.5,
        )
        violation2 = Violation(
            rule_id="V2",
            severity=Severity.CRITICAL,
            title="Test 2",
            message="Test",
            weight=0.5,
        )
        violation3 = Violation(
            rule_id="V3",
            severity=Severity.WARNING,
            title="Test 3",
            message="Test",
            weight=0.3,
        )
        verdict = Verdict(violations=[violation1, violation2, violation3])

        # 합계: 0.5 + 0.5 + 0.3 = 1.3
        raw_sum = sum(v.weight for v in verdict.violations)
        assert raw_sum > 1.0, "테스트 위반의 가중치 합이 1.0 이상이어야 합니다"

        # 하지만 defect_probability 는 1.0 으로 clipping
        assert verdict.defect_probability == 1.0, (
            f"가중치 합 {raw_sum}인데도 defect_probability 는 1.0 이어야 합니다"
        )


# ── 엣지 케이스 ───────────────────────────────────────────────────────


class Test엣지_케이스:
    """일반적이지 않은 입력들의 처리."""

    @pytest.fixture
    def 엔진(self):
        return RuleEngine()

    def test_빈_BL_dict(self, 엔진):
        """완전히 빈 dict 입력을 처리한다."""
        bl = {}
        lc = LCTerms()
        verdict = 엔진.verify(bl, lc)

        # 모든 필수 필드가 없으므로 많은 위반이 나와야 한다
        assert len(verdict.violations) > 5, "빈 B/L 은 많은 위반을 일으켜야 합니다"
        # 하지만 evaluated_count + skipped 는 여전히 21 이어야 한다
        assert (
            verdict.evaluated_count + len(verdict.skipped) == 21
        ), "룰 결과 분할 불변식이 깨졌습니다"

    def test_None_필드값_처리(self, 엔진):
        """필드값이 명시적 None 인 경우 누락과 같이 처리된다."""
        bl = {
            "bl_no": None,
            "consignee": None,
            "port_of_loading": None,
            "port_of_discharge": None,
        }
        lc = LCTerms()
        verdict = 엔진.verify(bl, lc)

        # 필수 필드가 모두 None 이므로 위반이 나와야 한다
        assert len(verdict.violations) > 0


@pytest.mark.parametrize(
    "rule_id,expected_severity",
    [
        ("D001", "critical"),  # B/L 번호 누락
        ("D002", "critical"),  # 선적기한 초과
        ("D009", "warning"),   # 송하인 누락
        ("D018", "warning"),   # 제시기간 임박
        ("D016", "info"),      # 요구서류 목록에 B/L 없음
    ],
)
def test_규칙_심각도_정의(rule_id, expected_severity):
    """각 규칙이 정의된 심각도를 가지고 있는지 확인한다."""
    엔진 = RuleEngine()
    rule = 엔진.rule(rule_id)
    assert rule is not None, f"규칙 {rule_id} 가 없습니다"
    assert rule["severity"] == expected_severity, (
        f"규칙 {rule_id} 의 심각도가 잘못되었습니다 "
        f"(예상: {expected_severity}, 실제: {rule['severity']})"
    )

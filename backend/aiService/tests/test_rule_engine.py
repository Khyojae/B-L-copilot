"""룰엔진 테스트 — 카탈로그 검증, 3상태 결과, 조문 근거 전달."""

from __future__ import annotations

from datetime import datetime

import pytest

from ocr.types import BLFields
from ruleEngine import (
    UNDECLARED_VERSION,
    CrossDocumentEngine,
    DocumentSet,
    LCTerms,
    RuleCatalogError,
    RuleEngine,
    Severity,
)
from ruleEngine.engine import load_rules, read_catalog

AS_OF = datetime(2026, 6, 10)


def clean_bl(**overrides) -> BLFields:
    """하자 없는 B/L."""
    bl = BLFields(
        bl_no="HG290309",
        shipper="GAE WOON CO., LTD.",
        consignee="DHHJ FRANCHISING CO., LTD.",
        notify_party="TRY ENERGY CO., LTD.",
        vessel="MSC BIANCA",
        voyage_no="V.112",
        port_of_loading="BUSAN, KOREA",
        port_of_discharge="TOKYO, JAPAN",
        description_of_goods="SAW MACHINE FOB",
        gross_weight="884 KG",
        measurement="349.64 CBM",
        date_of_issue="2026-06-01",
        # 발행지. D021 이 요구한다 — 정상 서류 픽스처는 서식의 필수 기재를
        # 빠짐없이 채워야, 룰이 늘 때 '정상인데 위반'이 나지 않는다.
        place_of_issue="PUSAN",
        on_board_date="2026-06-01",
        total_freight="$1,741.56",
        # 원본 통수. D032 가 요구한다 — 위 place_of_issue 주석과 같은 이유.
        no_of_original_bl="THREE (3)",
    )
    for name, value in overrides.items():
        setattr(bl, name, value)
    return bl


def clean_lc(**overrides) -> LCTerms:
    lc = LCTerms(
        lc_no="LC-2026-001",
        port_of_loading="PUSAN",
        port_of_discharge="TOKYO",
        consignee="DHHJ FRANCHISING CO., LTD.",
        description_of_goods="SAW MACHINE",
        latest_shipment_date="2026-06-30",
        expiry_date="2026-12-31",
        max_gross_weight_kg=1000.0,
        freight_amount=1741.56,
        incoterms="FOB",
    )
    for name, value in overrides.items():
        setattr(lc, name, value)
    return lc


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


class TestCatalog:
    def test_카탈로그가_로드된다(self, engine):
        assert len(engine) >= 20
        assert "D002" in engine.rule_ids

    def test_모든_룰에_조문_근거가_있다(self, engine):
        # S4 의 '항목별 조문 근거 펼침'과 F4 리포트가 이걸 그대로 출력한다.
        # 비면 화면이 근거 없는 판정을 보여주게 된다.
        missing = [r["id"] for r in engine.rules if not r.get("source")]
        assert missing == []

    def test_모든_룰에_수정_권고가_있다(self, engine):
        # F4 리포트의 '수정 권고(우선순위순)' 항목이 된다.
        missing = [
            r["id"] for r in engine.rules
            if r["severity"] != "info" and not r.get("remedy")
        ]
        assert missing == []

    def test_id가_중복되면_거부한다(self):
        rules = [
            {"id": "X1", "title": "a", "severity": "critical", "check": "required",
             "source": "s", "message": "m", "fields": ["bl_no"]},
            {"id": "X1", "title": "b", "severity": "critical", "check": "required",
             "source": "s", "message": "m", "fields": ["vessel"]},
        ]
        with pytest.raises(RuleCatalogError, match="중복"):
            RuleEngine(rules=rules)

    def test_모르는_check는_거부한다(self):
        # 실행 시점까지 끌고 가면 룰이 조용히 건너뛰어져 '하자 없음'이 된다.
        rules = [{"id": "X1", "title": "a", "severity": "critical",
                  "check": "존재하지_않는_검사", "source": "s", "message": "m"}]
        with pytest.raises(RuleCatalogError, match="알 수 없는 check"):
            RuleEngine(rules=rules)

    def test_모르는_severity는_거부한다(self):
        rules = [{"id": "X1", "title": "a", "severity": "치명적", "check": "required",
                  "source": "s", "message": "m", "fields": ["bl_no"]}]
        with pytest.raises(RuleCatalogError, match="severity"):
            RuleEngine(rules=rules)

    def test_필수항목이_빠지면_거부한다(self):
        rules = [{"id": "X1", "check": "required", "fields": ["bl_no"]}]
        with pytest.raises(RuleCatalogError, match="필수 항목"):
            RuleEngine(rules=rules)

    def test_weight_범위를_검사한다(self):
        rules = [{"id": "X1", "title": "a", "severity": "info", "check": "required",
                  "source": "s", "message": "m", "fields": ["bl_no"], "weight": 1.5}]
        with pytest.raises(RuleCatalogError, match="weight"):
            RuleEngine(rules=rules)

    def test_빈_카탈로그는_거부한다(self):
        with pytest.raises(RuleCatalogError, match="하나도 없습니다"):
            RuleEngine(rules=[])

    def test_yaml에서_직접_읽는다(self):
        assert len(load_rules()) >= 20


class TestCleanDocument:
    def test_정상_서류는_위반이_없다(self, engine):
        verdict = engine.verify(clean_bl(), clean_lc(), as_of=AS_OF)

        assert verdict.violations == []
        assert verdict.defect_probability == 0.0
        assert not verdict.has_critical

    def test_항구_이명을_같은_것으로_본다(self, engine):
        # BUSAN 과 PUSAN 은 같은 항구다. 표기 차이로 하자를 내면 오탐이다.
        verdict = engine.verify(
            clean_bl(port_of_loading="PUSAN, KOREA"), clean_lc(), as_of=AS_OF
        )

        assert not any(v.rule_id == "D003" for v in verdict.violations)

    def test_법인격_표기_차이를_흡수한다(self, engine):
        # "CO., LTD." 유무로 불일치를 내면 오탐이 폭증한다.
        verdict = engine.verify(
            clean_bl(consignee="DHHJ FRANCHISING"), clean_lc(), as_of=AS_OF
        )

        assert not any(v.rule_id == "D005B" for v in verdict.violations)


class TestThreeStateOutcome:
    def test_LC조건이_없으면_평가불가로_남긴다(self, engine):
        # 통과로 세면 조건이 적은 L/C 일수록 안전해 보이는 역전이 생긴다.
        verdict = engine.verify(clean_bl(), LCTerms(), as_of=AS_OF)

        skipped_ids = {s.rule_id for s in verdict.skipped}
        assert "D003" in skipped_ids
        assert "D002" in skipped_ids
        assert verdict.violations == []

    def test_평가불가에_사유가_붙는다(self, engine):
        verdict = engine.verify(clean_bl(), LCTerms(), as_of=AS_OF)

        d003 = next(s for s in verdict.skipped if s.rule_id == "D003")
        assert "명시" in d003.reason

    def test_날짜를_못_읽으면_형식_오류_위반이다(self, engine):
        # 통과나 평가불가로 처리하면 OCR 이 나쁠수록 하자가 적어 보이거나
        # (통과) 조용히 숨겨진다(평가불가) — format_error 가 위반으로 드러낸다.
        verdict = engine.verify(
            clean_bl(on_board_date="60-55-2708", date_of_issue="60-55-2708"),
            clean_lc(),
            as_of=AS_OF,
        )

        d002 = next(v for v in verdict.violations if v.rule_id == "D002")
        assert "해석할 수 없습니다" in d002.message
        assert d002.severity is Severity.WARNING

    def test_평가한_건수만_센다(self, engine):
        verdict = engine.verify(clean_bl(), clean_lc(), as_of=AS_OF)

        assert verdict.evaluated_count + len(verdict.skipped) == len(engine)

    def test_룰이_터져도_나머지가_돈다(self):
        # 예외가 통과로 집계되면 안 된다.
        def boom(bl, lc, rule):
            raise RuntimeError("의도적 실패")

        from ruleEngine.checks import REGISTRY

        REGISTRY["_boom"] = boom
        try:
            rules = [
                {"id": "BOOM", "title": "터짐", "severity": "critical",
                 "check": "_boom", "source": "s", "message": "m"},
                {"id": "OK", "title": "정상", "severity": "critical",
                 "check": "required", "source": "s", "message": "m",
                 "fields": ["bl_no"]},
            ]
            verdict = RuleEngine(rules=rules).verify(clean_bl())

            assert verdict.evaluated_count == 1
            boom_skip = next(s for s in verdict.skipped if s.rule_id == "BOOM")
            assert "오류" in boom_skip.reason
        finally:
            REGISTRY.pop("_boom")


class TestDefectDetection:
    @pytest.mark.parametrize(
        "rule_id, bl_over, lc_over",
        [
            ("D003", {"port_of_loading": "SHANGHAI, CHINA"}, {}),
            ("D004", {"port_of_discharge": "HAMBURG, GERMANY"}, {}),
            ("D005B", {"consignee": "WRONG COMPANY INC."}, {}),
            ("D002", {"on_board_date": "2026-07-15"}, {}),
            # D008 은 발행일이 아니라 제시 시점(as_of) 기준으로 L/C 유효기일을
            # 본다 — bl_over 가 아니라 lc_over 로 유효기일을 as_of 이전으로
            # 당겨야 위반이 난다.
            ("D008", {}, {"expiry_date": "2026-01-01"}),
            ("D007", {"gross_weight": "1500 KG"}, {}),
            ("D017", {"total_freight": "$5,000.00"}, {}),
            ("D001", {"bl_no": None}, {}),
            ("D006", {}, {"description_of_goods": "SAW MACHINE, SPARE PARTS"}),
        ],
    )
    def test_주입한_하자를_해당_룰이_잡는다(self, engine, rule_id, bl_over, lc_over):
        verdict = engine.verify(clean_bl(**bl_over), clean_lc(**lc_over), as_of=AS_OF)

        assert rule_id in {v.rule_id for v in verdict.violations}

    def test_분할선적_금지_위반(self, engine):
        verdict = engine.verify(
            clean_bl(description_of_goods="SAW MACHINE FOB PARTIAL SHIPMENT"),
            clean_lc(partial_shipment="PROHIBITED"),
            as_of=AS_OF,
        )

        assert "D013" in {v.rule_id for v in verdict.violations}

    def test_분할선적_허용이면_검사하지_않는다(self, engine):
        # UCP 600 Art.31(a): 금지하지 않으면 허용이 기본이다.
        verdict = engine.verify(
            clean_bl(description_of_goods="SAW MACHINE FOB PARTIAL SHIPMENT"),
            clean_lc(partial_shipment="ALLOWED"),
            as_of=AS_OF,
        )

        assert "D013" not in {v.rule_id for v in verdict.violations}
        assert "D013" in {s.rule_id for s in verdict.skipped}

    def test_제시기간_경과를_잡는다(self, engine):
        verdict = engine.verify(
            clean_bl(on_board_date="2026-05-01"), clean_lc(), as_of=AS_OF
        )

        assert "D018" in {v.rule_id for v in verdict.violations}

    def test_누락은_한_번만_센다(self, engine):
        # required 와 match 룰이 둘 다 세면 이중 계상된다.
        verdict = engine.verify(clean_bl(consignee=None), clean_lc(), as_of=AS_OF)

        ids = [v.rule_id for v in verdict.violations]
        assert "D005" in ids           # 누락 룰
        assert "D005B" not in ids      # 불일치 룰은 평가불가


class TestViolationContent:
    def test_위반에_조문_근거가_실린다(self, engine):
        verdict = engine.verify(
            clean_bl(port_of_loading="SHANGHAI, CHINA"), clean_lc(), as_of=AS_OF
        )

        d003 = next(v for v in verdict.violations if v.rule_id == "D003")
        assert "UCP 600" in d003.source
        assert d003.remedy

    def test_메시지에_실제_값이_치환된다(self, engine):
        verdict = engine.verify(
            clean_bl(port_of_loading="SHANGHAI, CHINA"), clean_lc(), as_of=AS_OF
        )

        d003 = next(v for v in verdict.violations if v.rule_id == "D003")
        assert "SHANGHAI, CHINA" in d003.message
        assert "PUSAN" in d003.message
        assert "{" not in d003.message

    def test_값이_없으면_물음표로_둔다(self, engine):
        # None 이 그대로 노출되면 사용자가 읽을 수 없다.
        verdict = engine.verify(clean_bl(bl_no=None), clean_lc(), as_of=AS_OF)

        d001 = next(v for v in verdict.violations if v.rule_id == "D001")
        assert "None" not in d001.message

    def test_필드명이_실려_편집기로_점프할_수_있다(self, engine):
        # S4 의 '해당 필드로 바로가기'가 쓴다.
        verdict = engine.verify(
            clean_bl(port_of_loading="SHANGHAI, CHINA"), clean_lc(), as_of=AS_OF
        )

        d003 = next(v for v in verdict.violations if v.rule_id == "D003")
        assert "port_of_loading" in d003.fields


class TestVerdictAggregation:
    def test_확률은_1을_넘지_않는다(self, engine):
        broken = BLFields(port_of_loading="X", port_of_discharge="Y")
        verdict = engine.verify(broken, clean_lc(), as_of=AS_OF)

        assert 0.0 <= verdict.defect_probability <= 1.0

    def test_심각한_순으로_정렬한다(self, engine):
        broken = clean_bl(
            port_of_loading="SHANGHAI, CHINA", vessel=None, notify_party=None
        )
        verdict = engine.verify(broken, clean_lc(), as_of=AS_OF)

        ranks = [v.severity for v in verdict.sorted_violations()]
        order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
        assert [order[s] for s in ranks] == sorted(order[s] for s in ranks)

    def test_모델_표기가_남는다(self, engine):
        # 화면이 룰 가중치 합산을 학습된 모델의 확률로 표기하면 안 된다.
        verdict = engine.verify(clean_bl(), clean_lc(), as_of=AS_OF)

        assert verdict.model == "rules-v1"

    def test_직렬화에_평가불가가_포함된다(self, engine):
        # 검사하지 못한 항목을 침묵으로 넘기면 '검사했고 문제없다'로 읽힌다.
        payload = engine.verify(clean_bl(), LCTerms(), as_of=AS_OF).to_dict()

        assert payload["skipped_count"] > 0
        assert payload["skipped"]


class TestInputTypes:
    def test_dict도_받는다(self, engine):
        # S3 편집기에서 사람이 고친 값은 dict 로 온다.
        verdict = engine.verify(
            {"bl_no": "ABC1234", "consignee": "DHHJ FRANCHISING CO., LTD."},
            LCTerms(consignee="DHHJ FRANCHISING CO., LTD."),
            as_of=AS_OF,
        )

        assert not any(v.rule_id == "D005B" for v in verdict.violations)

    def test_잘못된_형은_예외를_낸다(self, engine):
        # 조용히 '전 필드 누락'으로 처리하면 없는 하자가 날조된다.
        with pytest.raises(TypeError, match="dict 또는 BLFields"):
            engine.verify("문자열이 들어옴")

    def test_as_of를_주입하면_결과가_고정된다(self, engine):
        bl = clean_bl(on_board_date="2026-05-01")

        early = engine.verify(bl, clean_lc(), as_of=datetime(2026, 5, 10))
        late = engine.verify(bl, clean_lc(), as_of=datetime(2026, 7, 10))

        assert "D018" not in {v.rule_id for v in early.violations}
        assert "D018" in {v.rule_id for v in late.violations}

    def test_제시기간_경과는_CRITICAL_이다(self):
        # UCP 600 Art.14(c) 위반은 은행이 수리를 거절하는 하자다.
        # warning 으로 두면 has_critical 로 재는 모든 지표에서 이 유형이
        # 통째로 미검출로 집계된다.
        bl = clean_bl(on_board_date="2026-05-01")

        verdict = RuleEngine().verify(bl, clean_lc(), as_of=datetime(2026, 7, 10))

        assert verdict.has_critical
        d018 = next(v for v in verdict.violations if v.rule_id == "D018")
        assert d018.severity is Severity.CRITICAL


class TestMT700:
    def test_태그로_LC를_만든다(self, engine):
        lc = LCTerms.from_tags(
            {"44E": "BUSAN", "44F": "TOKYO", "44C": "2026-06-30", "31D": "2026-12-31"},
            lc_no="LC-001",
        )

        assert lc.port_of_loading == "BUSAN"
        assert lc.latest_shipment_date == "2026-06-30"
        assert lc.expiry_date == "2026-12-31"

    def test_모르는_태그는_무시한다(self):
        lc = LCTerms.from_tags({"44E": "BUSAN", "99Z": "정체불명"})

        assert lc.port_of_loading == "BUSAN"

    def test_금지조건_기본값은_허용이다(self):
        # UCP 600 상 명시가 없으면 분할선적·환적은 허용이 기본이다.
        # 금지로 기본값을 잡으면 명시 없는 정상 건이 전부 하자가 된다.
        lc = LCTerms()

        assert lc.partial_shipment == "ALLOWED"
        assert lc.transhipment == "ALLOWED"


class TestISBP:
    """ISBP 821 근거 룰 — 기획안 5절 "위반 예상 조항(UCP600·ISBP)"."""

    def test_발행일이_미래면_잡는다(self, engine):
        bl = clean_bl(date_of_issue="2026-08-01")

        verdict = engine.verify(bl, clean_lc(), as_of=datetime(2026, 6, 10))

        d019 = next(v for v in verdict.violations if v.rule_id == "D019")
        assert "ISBP" in d019.source
        # 고정 문구가 아니라 실제 차이 일수가 들어가야 한다.
        assert "52일" in d019.message

    def test_발행일_미래는_LC_없이도_평가된다(self, engine):
        # 서류 하나로 판정되는 내부 정합성 검사다. L/C 없이 돌릴 때
        # 대부분의 룰이 평가불가로 빠지는데, 이런 룰이 검사 범위를 넓힌다.
        bl = clean_bl(date_of_issue="2026-07-01")

        verdict = engine.verify(bl, LCTerms(), as_of=datetime(2026, 6, 10))

        assert "D019" in {v.rule_id for v in verdict.violations}
        assert "D019" not in {s.rule_id for s in verdict.skipped}

    def test_통지처_불일치를_잡는다(self, engine):
        bl = clean_bl(notify_party="WRONG NOTIFY CO., LTD.")
        lc = clean_lc(notify_party="TRY ENERGY CO., LTD.")

        verdict = engine.verify(bl, lc, as_of=AS_OF)

        d020 = next(v for v in verdict.violations if v.rule_id == "D020")
        assert "ISBP" in d020.source

    def test_발행지_누락을_잡는다(self, engine):
        bl = clean_bl(place_of_issue=None)

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        assert "D021" in {v.rule_id for v in verdict.violations}

    def test_정상_서류는_새_룰에도_걸리지_않는다(self, engine):
        verdict = engine.verify(clean_bl(), clean_lc(), as_of=AS_OF)

        assert verdict.violations == []

    def test_발행일_누락을_잡는다(self, engine):
        # D021 의 조문 근거가 발행지와 발행일을 함께 요구하는데 발행일을
        # 검사하는 룰이 없었다.
        bl = clean_bl(date_of_issue=None)

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        d022 = next(v for v in verdict.violations if v.rule_id == "D022")
        assert "ISBP" in d022.source
        assert d022.severity is Severity.CRITICAL

    def test_발행일이_없으면_날짜_룰이_전부_평가불가로_빠진다(self, engine):
        # D022 를 둔 이유가 이것이다. 발행일을 빼면 서류 날짜를 보는 룰이
        # 전부 침묵하므로, 잡는 룰이 없으면 위반 0건 = '하자 없음' 이 된다.
        # D008 은 여기 없다 — 발행일이 아니라 제시 시점(as_of) 기준으로
        # L/C 유효기일만 보므로 발행일 공백의 영향을 받지 않는다.
        bl = clean_bl(date_of_issue=None, on_board_date=None)

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        skipped_ids = {s.rule_id for s in verdict.skipped}
        assert {"D018", "D019"} <= skipped_ids
        assert "D022" in {v.rule_id for v in verdict.violations}

    def test_항구가_지역으로_기재되면_잡는다(self, engine):
        bl = clean_bl(port_of_discharge="ANY EUROPEAN PORT")

        verdict = engine.verify(bl, clean_lc(port_of_discharge=None), as_of=AS_OF)

        d025 = next(v for v in verdict.violations if v.rule_id == "D025")
        assert "ISBP" in d025.source
        assert "EUROPEAN PORT" in d025.message

    def test_항구_미특정은_LC_없이도_평가된다(self, engine):
        # 문면상 하자는 L/C 를 보지 않는다. 조건부 룰로 만들면 L/C 없이
        # 돌릴 때 통째로 검사되지 않는다.
        bl = clean_bl(port_of_loading="ANY MAIN PORT IN KOREA")

        verdict = engine.verify(bl, LCTerms(), as_of=AS_OF)

        assert "D025" in {v.rule_id for v in verdict.violations}

    def test_운임_후불이_C조건과_저촉되면_잡는다(self, engine):
        bl = clean_bl(total_freight="FREIGHT COLLECT")

        verdict = engine.verify(bl, clean_lc(incoterms="CIF"), as_of=AS_OF)

        d026 = next(v for v in verdict.violations if v.rule_id == "D026")
        assert "ISBP" in d026.source

    def test_운임_후불이_화물명세에_있어도_잡는다(self, engine):
        # 운임란에 금액이 있으면 첫 필드에서 멈추던 경로. 값이 있을수록
        # 검사가 줄어드는 역전이 생긴다.
        bl = clean_bl(
            total_freight="$1,741.56",
            description_of_goods="SAW MACHINE CIF FREIGHT COLLECT",
        )

        verdict = engine.verify(bl, clean_lc(incoterms="CIF"), as_of=AS_OF)

        assert "D026" in {v.rule_id for v in verdict.violations}

    def test_F조건에_운임_선불은_하자가_아니다(self, engine):
        # 매도인이 편의상 선지급한 것일 수 있고 은행이 그것으로 거절하지
        # 않는다. 대칭으로 만들면 정상 건이 하자로 잡힌다.
        bl = clean_bl(total_freight="FREIGHT PREPAID")

        verdict = engine.verify(bl, clean_lc(incoterms="FOB"), as_of=AS_OF)

        assert "D026" not in {v.rule_id for v in verdict.violations}
        assert "D026" in {s.rule_id for s in verdict.skipped}


class TestFaceOfDocument:
    """문면상 하자 — L/C 를 보지 않고 서류 자체로 판정하는 룰."""

    def test_고장_문언을_잡는다(self, engine):
        bl = clean_bl(description_of_goods="SAW MACHINE FOB, 3 CARTONS DAMAGED")

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        d023 = next(v for v in verdict.violations if v.rule_id == "D023")
        assert d023.severity is Severity.CRITICAL
        assert "DAMAGED" in d023.message

    def test_낱말_경계로_본다(self, engine):
        # 부분 일치로 두면 WETSUIT 이 고장 문언(WET)으로 잡힌다. 오탐 하나가
        # 정상 서류를 반려시키는 룰이라 좁게 잡는다.
        bl = clean_bl(description_of_goods="NEOPRENE WETSUIT FOB")

        verdict = engine.verify(bl, clean_lc(description_of_goods=None), as_of=AS_OF)

        assert "D023" not in {v.rule_id for v in verdict.violations}

    def test_예정_선박_표시를_잡는다(self, engine):
        bl = clean_bl(vessel="INTENDED VESSEL MSC BIANCA")

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        d024 = next(v for v in verdict.violations if v.rule_id == "D024")
        assert d024.severity is Severity.WARNING

    def test_대상_필드가_비면_평가불가다(self, engine):
        # '문언이 없다'와 '볼 것이 없다'는 다르다. 누락은 required 룰이 잡는다.
        bl = clean_bl(description_of_goods=None)

        verdict = engine.verify(bl, clean_lc(), as_of=AS_OF)

        assert "D023" in {s.rule_id for s in verdict.skipped}


class TestSourceVerification:
    """조문 인용의 실무 검증 상태 — 기획안 9절 "멘토 기업 실무 검증"."""

    def test_기본값은_미검증이다(self, engine):
        # 일부에만 verified: false 를 달면 나머지가 검증된 것처럼 읽힌다.
        # 확인을 거친 룰이 없으므로 전건이 미검증이어야 한다.
        assert len(engine.unverified_rules()) == len(engine.rules)

    def test_명시한_룰만_검증으로_센다(self):
        rules = load_rules()
        rules[0]["verified"] = True

        assert len(RuleEngine(rules).unverified_rules()) == len(rules) - 1

    def test_모든_룰에_조문_근거가_있다(self, engine):
        # 근거 없는 룰은 리포트에서 인용할 것이 없다.
        assert all(r.get("source") for r in engine.rules)


class TestCatalogFingerprint:
    """판정 재현성 — 어떤 카탈로그로 냈는지 (기획안 5.3 · 5.8)."""

    def test_판정에_카탈로그_신원이_실린다(self, engine):
        verdict = engine.verify(clean_bl(), LCTerms(), as_of=AS_OF)

        assert verdict.catalog == engine.fingerprint.to_dict()
        assert verdict.to_dict()["catalog"]["label"] == engine.fingerprint.label

    def test_선언된_버전을_그대로_읽는다(self, engine):
        rules, declared = read_catalog()

        assert engine.fingerprint.version == declared
        assert len(rules) == len(engine.rules)

    def test_다이제스트는_12자_16진수다(self, engine):
        digest = engine.fingerprint.digest

        assert len(digest) == 12
        assert all(ch in "0123456789abcdef" for ch in digest)

    def test_룰을_고치면_버전이_그대로여도_다이제스트가_바뀐다(self):
        # 이 테스트가 이 기능의 존재 이유다. 8번(ISBP 룰 보강)에서 룰이
        # 24건에서 29건이 되는 동안 version 은 1 이었다. version 만 남기면
        # 서로 다른 카탈로그로 낸 판정이 같은 기준을 쓴 것으로 기록된다.
        rules, declared = read_catalog()
        changed = [dict(r) for r in rules]
        changed[0]["severity"] = "info"

        before = RuleEngine(rules, version=declared).fingerprint
        after = RuleEngine(changed, version=declared).fingerprint

        assert before.version == after.version
        assert before.digest != after.digest

    def test_버전만_올려도_다이제스트는_그대로다(self):
        rules = load_rules()

        assert (
            RuleEngine(rules, version="1").fingerprint.digest
            == RuleEngine(rules, version="2").fingerprint.digest
        )

    def test_키_순서는_신원을_바꾸지_않는다(self):
        # YAML 에서 키를 재배열한 것은 카탈로그가 달라진 것이 아니다.
        rules = load_rules()
        reordered = [dict(reversed(list(r.items()))) for r in rules]

        assert (
            RuleEngine(rules).fingerprint.digest
            == RuleEngine(reordered).fingerprint.digest
        )

    def test_버전을_선언하지_않은_카탈로그(self):
        # 코드에서 주입한 룰에는 선언된 버전이 없다. 빈 값이 아니라
        # 명시적인 표기가 남아야 버전 자리가 비었다는 사실이 읽힌다.
        engine = RuleEngine(load_rules())

        assert engine.fingerprint.version == UNDECLARED_VERSION
        assert engine.fingerprint.label.startswith("v0+")

    def test_서류_간_카탈로그는_신원이_따로다(self):
        # 두 카탈로그는 별도 파일이라 별도로 개정된다. 신원을 합치면
        # 어느 쪽이 바뀌었는지 되짚을 수 없다.
        cross = CrossDocumentEngine()

        assert cross.fingerprint.digest != RuleEngine().fingerprint.digest
        assert cross.verify(DocumentSet()).catalog == cross.fingerprint.to_dict()

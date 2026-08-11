"""실물 말뭉치 경로 테스트.

라벨 데이터셋은 저장소에 없다(용량·이용조건). 그래서 여기서는 **말뭉치를
직접 만들어** 경로를 검사한다. 실제 데이터가 있는 환경에서만 도는 테스트를
쓰면 CI 에서는 이 경로가 통째로 검사되지 않는다.
"""

from __future__ import annotations

import pytest

from mlModel import corpus
from mlModel.corpus import BLRecord, CorpusSampler
from mlModel.synth import SyntheticGenerator
from ocr.types import BL_FIELD_NAMES
from ruleEngine import RuleEngine


def record(**overrides) -> BLRecord:
    """말뭉치 레코드 하나. 실물에서 관측된 성질을 흉내낸다."""
    values = {name: None for name in BL_FIELD_NAMES}
    values.update({
        "bl_no": "MSCU246413",
        "shipper": "GAE WOON CO., LTD.",
        "consignee": "TRY ENERGY CO., LTD.",
        "notify_party": "SAME AS CONSIGNEE",
        "vessel": "MSC BIANCA",
        "port_of_loading": "BUSAN, KOREA",
        "port_of_discharge": "HAMBURG, GERMANY",
        # 실물에서 흔한 형태 — 품명 뒤에 포장·면책 문구가 붙는다.
        "description_of_goods": "RECEIVER ASSY-KEYLESS ENTRY / 18 PKG",
        "gross_weight": "348.84 KG",
        "measurement": "12.5 CBM",
        # 실물의 표기 형식 다양성. 표준 형식으로 바꾸면 이 성질이 사라진다.
        "date_of_issue": "16-AUG-2009",
        "place_of_issue": "BUSAN",
        "on_board_date": "SEP 06, 2006",
        "total_freight": None,          # 실측 41.7% 가 비어 있다
    })
    values.update(overrides)
    return BLRecord(
        source_id="IMG_OCR_6_T_BL_000002",
        values=values,
        confidence={n: 1.0 for n, v in values.items() if v},
        provenance={n: "region" for n, v in values.items() if v},
    )


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


class TestRecord:
    def test_필드로_복원된다(self):
        fields = record().to_fields()

        assert fields.bl_no == "MSCU246413"
        assert fields.total_freight is None
        assert fields.confidence["bl_no"] == 1.0

    def test_복원할_때마다_새_객체다(self):
        # 하자 주입이 필드를 덮어쓴다. 하나를 돌려쓰면 앞 표본의 주입이
        # 뒤 표본으로 샌다.
        rec = record()
        first = rec.to_fields()
        first.consignee = "덮어씀"

        assert rec.to_fields().consignee == "TRY ENERGY CO., LTD."

    def test_캐시_왕복이_동일하다(self, tmp_path):
        path = str(tmp_path / "corpus.json")
        corpus.save_cache([record(), record(bl_no="HG290309")], path)

        loaded = corpus.load_cache(path)

        assert [r.values["bl_no"] for r in loaded] == ["MSCU246413", "HG290309"]

    def test_캐시_버전이_다르면_거부한다(self, tmp_path):
        # 형식이 바뀐 캐시를 조용히 읽으면 학습 데이터가 말없이 달라진다.
        path = tmp_path / "corpus.json"
        path.write_text('{"version": 999, "records": []}', encoding="utf-8")

        with pytest.raises(ValueError, match="버전"):
            corpus.load_cache(str(path))


class TestCleanBaseFilter:
    def test_핵심_필드가_있으면_쓸_수_있다(self):
        assert corpus.usable_as_clean_base(record())

    @pytest.mark.parametrize("missing", corpus.REQUIRED_FOR_CLEAN_BASE)
    def test_required_critical_이_비면_제외한다(self, missing):
        # 비어 있으면 하자 주입 전부터 치명 위반이 잡힌다.
        assert not corpus.usable_as_clean_base(record(**{missing: None}))

    def test_warning_필드_결측은_남긴다(self):
        # 실물의 결측 분포가 말뭉치를 쓰는 이유다. 전부 버리면 그게 사라진다.
        assert corpus.usable_as_clean_base(record(voyage_no=None, total_freight=None))


class TestGeneratorWithCorpus:
    def test_말뭉치가_없으면_기존_경로로_돈다(self):
        generator = SyntheticGenerator(seed=42)

        assert not generator.uses_corpus
        assert len(generator.generate(20)) == 20

    def test_말뭉치를_주면_실물_값이_나온다(self):
        generator = SyntheticGenerator(seed=42, corpus=[record()])

        samples = generator.generate(20)

        assert generator.uses_corpus
        assert any(s.bl.consignee == "TRY ENERGY CO., LTD." for s in samples)

    def test_하자를_주입하지_않은_표본에는_위반이_없다(self, engine):
        # 이게 이 경로의 핵심 계약이다. 실물이라 룰에 걸리는 서류가 섞여
        # 있는데, 그걸 '하자 없는 기준'으로 쓰면 라벨 0 에 위반이 붙어
        # 정밀도가 데이터 탓으로 떨어지고 원인이 보이지 않는다.
        generator = SyntheticGenerator(seed=7, corpus=[record()])

        for sample in generator.generate(40):
            if sample.injected:
                continue
            verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
            assert verdict.violations == [], f"{sample.bl.bl_no}: {verdict.violations}"

    def test_날짜_표기_형식을_보존한다(self):
        # 값은 기준 시각 근처로 옮기되 형식은 그대로 둔다. 표준 형식으로
        # 바꾸면 parse_date 의 형식 목록을 시험하는 성질이 사라진다.
        generator = SyntheticGenerator(seed=42, corpus=[record()])

        sample = next(s for s in generator.generate(20) if not s.injected)

        assert sample.bl.date_of_issue is not None
        # `16-AUG-2009` → `%d-%b-%Y`
        assert sample.bl.date_of_issue.count("-") == 2
        assert sample.bl.date_of_issue.endswith("2026")

    def test_날짜를_기준_시각_근처로_옮긴다(self):
        # 실물 날짜는 2002~2017 에 흩어져 있어 그대로 쓰면 전건이
        # D018(제시기간 경과)에 걸린다.
        from ruleEngine.checks import parse_date
        from mlModel.synth import BASE_DATE

        generator = SyntheticGenerator(seed=42, corpus=[record()])

        for sample in generator.generate(20):
            if sample.injected or not sample.bl.on_board_date:
                continue
            shipped = parse_date(sample.bl.on_board_date)
            assert shipped is not None
            assert 0 <= (BASE_DATE - shipped).days <= 21

    def test_LC_는_서류에서_읽을_수_없는_조건을_지어내지_않는다(self):
        # 없는 한도를 만들어 넣으면 룰이 실제보다 많이 평가되어
        # skipped_ratio 가 실물 분포에서 멀어진다.
        generator = SyntheticGenerator(seed=42, corpus=[record(total_freight=None)])

        sample = next(s for s in generator.generate(20) if not s.injected)

        assert sample.lc.freight_amount is None

    def test_LC_항구는_서류_표기를_그대로_복사하지_않는다(self):
        # 같게 두면 match_place 의 토큰 비교·항구 이명 흡수가 한 번도
        # 실제로 동작하지 않는 데이터가 된다.
        generator = SyntheticGenerator(seed=42, corpus=[record()])

        sample = next(s for s in generator.generate(20) if not s.injected)

        assert sample.lc.port_of_loading == "BUSAN"
        assert sample.bl.port_of_loading == "BUSAN, KOREA"

    def test_LC_명세는_서류에_그대로_있는_구간이다(self):
        # 낱말을 골라 이어붙이면 원문에 없는 문자열이 되어, 서류가 자기
        # 명세와 불일치하는 L/C 가 만들어진다.
        generator = SyntheticGenerator(seed=42, corpus=[record()])

        sample = next(s for s in generator.generate(20) if not s.injected)

        assert sample.lc.description_of_goods in sample.bl.description_of_goods.upper()


class TestSampler:
    def test_빈_말뭉치는_거부한다(self):
        import random

        with pytest.raises(ValueError, match="비어"):
            CorpusSampler([], random.Random(0))

    def test_말뭉치보다_많이_뽑을_수_있다(self):
        # 복원추출이다. 비복원이면 말뭉치 크기가 생성 가능 건수의 상한이 된다.
        generator = SyntheticGenerator(seed=42, corpus=[record(), record(bl_no="X")])

        assert len(generator.generate(50)) == 50

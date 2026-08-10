"""하자 확률 예측 테스트 — 피처, 합성 데이터, 예측기, 평가 하네스."""

from __future__ import annotations

from datetime import datetime

import pytest

from mlModel.evaluate import Metrics, evaluate
from mlModel.features import (
    FEATURE_NAMES,
    NO_DEADLINE,
    RAW_FEATURE_NAMES,
    RULE_DERIVED_FEATURES,
    extract_features,
    select,
)
from mlModel.predictor import DefectPredictor
from mlModel.synth import DEFECT_KINDS, SyntheticGenerator
from ocr.types import BLFields
from ruleEngine import LCTerms, RuleEngine, Verdict

AS_OF = datetime(2026, 6, 10)

xgboost = pytest.importorskip("xgboost", reason="XGBoost 미설치 시 건너뜀")


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


def features_of(engine, bl, lc, as_of=AS_OF):
    verdict = engine.verify(bl, lc, as_of=as_of)
    return extract_features(bl, lc, verdict, as_of), verdict


class TestFeatures:
    def test_피처_개수가_이름과_맞는다(self, engine):
        vector, _ = features_of(engine, BLFields(bl_no="A1234"), LCTerms())

        assert len(vector) == len(FEATURE_NAMES)

    def test_이름으로_조회된다(self, engine):
        vector, _ = features_of(engine, BLFields(bl_no="A1234"), LCTerms())

        assert set(vector.as_dict()) == set(FEATURE_NAMES)

    def test_위반이_늘면_해당_피처가_는다(self, engine):
        clean = BLFields(
            bl_no="A1234", consignee="X CO., LTD.",
            port_of_loading="BUSAN", port_of_discharge="TOKYO",
            date_of_issue="2026-06-01",
        )
        lc = LCTerms(consignee="X CO., LTD.")
        broken = BLFields(bl_no=None, consignee=None)

        clean_v, _ = features_of(engine, clean, lc)
        broken_v, _ = features_of(engine, broken, lc)

        assert broken_v.as_dict()["critical_count"] > clean_v.as_dict()["critical_count"]

    def test_평가불가_비율이_피처에_들어간다(self, engine):
        # 룰이 침묵하는 영역을 모델이 볼 수 있게 하는 핵심 피처다.
        _, verdict = features_of(engine, BLFields(bl_no="A1234"), LCTerms())
        vector, _ = features_of(engine, BLFields(bl_no="A1234"), LCTerms())

        assert vector.as_dict()["skipped_ratio"] > 0

    def test_기한이_없으면_큰_양수를_쓴다(self, engine):
        # 0 을 쓰면 '오늘이 마감'으로 읽혀 위험이 과대평가된다.
        vector, _ = features_of(engine, BLFields(bl_no="A1234"), LCTerms())

        assert vector.as_dict()["days_to_shipment_deadline"] == NO_DEADLINE

    def test_기한까지_남은_일수를_센다(self, engine):
        lc = LCTerms(latest_shipment_date="2026-06-30")
        vector, _ = features_of(engine, BLFields(bl_no="A1234"), lc)

        assert vector.as_dict()["days_to_shipment_deadline"] == pytest.approx(20, abs=1)

    def test_신뢰도_피처가_반영된다(self, engine):
        bl = BLFields()
        bl.set_field("bl_no", "A1234", 0.40, "region")
        bl.set_field("consignee", "X CO., LTD.", 0.95, "anchor")

        vector, _ = features_of(engine, bl, LCTerms())
        values = vector.as_dict()

        assert values["mean_confidence"] == pytest.approx(0.675, abs=0.01)
        assert values["anchor_derived_ratio"] == pytest.approx(0.5)

    def test_dict_입력에서_전_필드_누락으로_계산하지_않는다(self, engine):
        # getattr 로 읽으면 dict 의 모든 필드가 None 이 되어
        # 정상 서류가 최고 위험으로 분류된다.
        as_dict = {"bl_no": "A1234", "consignee": "X CO., LTD.",
                   "port_of_loading": "BUSAN", "vessel": "MSC BIANCA"}

        vector, _ = features_of(engine, as_dict, LCTerms())

        assert vector.as_dict()["field_missing_ratio"] < 1.0


class TestFeatureGroups:
    def test_원시_특징에는_룰_출력이_없다(self):
        # 하나라도 새면 비교군이 '룰과 무관'하다고 말할 수 없게 된다.
        assert not (set(RAW_FEATURE_NAMES) & RULE_DERIVED_FEATURES)

    def test_두_그룹이_전체를_덮는다(self):
        assert set(RAW_FEATURE_NAMES) | RULE_DERIVED_FEATURES == set(FEATURE_NAMES)
        assert len(RAW_FEATURE_NAMES) + len(RULE_DERIVED_FEATURES) == len(FEATURE_NAMES)

    def test_원시_특징이_비어_있지_않다(self):
        assert len(RAW_FEATURE_NAMES) >= 5

    def test_select가_이름에_맞는_열을_뽑는다(self):
        row = [float(i) for i in range(len(FEATURE_NAMES))]
        picked = select(row, ["mean_confidence", "critical_count"])

        assert picked == [
            float(FEATURE_NAMES.index("mean_confidence")),
            float(FEATURE_NAMES.index("critical_count")),
        ]

    def test_룰_출력_전부가_verdict에서_온다(self, engine):
        # 경계가 흐려지면 3열 비교의 의미가 사라진다. verdict 를 비우면
        # 룰 출력 피처만 변해야 한다.
        bl = BLFields(bl_no="A1234", consignee=None, port_of_loading="BUSAN")
        lc = LCTerms(consignee="X CO., LTD.", port_of_loading="TOKYO")

        vector, _ = features_of(engine, bl, lc)
        full = vector.as_dict()
        empty = extract_features(bl, lc, Verdict(model="rules-v1"), AS_OF).as_dict()

        changed = {n for n in FEATURE_NAMES if full[n] != empty[n]}
        assert changed, "위반이 나는 서류인데 룰 출력 피처가 하나도 안 변했습니다"
        assert changed <= RULE_DERIVED_FEATURES, (
            f"verdict 만 바꿨는데 원시 특징이 변했습니다: "
            f"{changed - RULE_DERIVED_FEATURES}"
        )


class TestSyntheticData:
    def test_시드가_같으면_같은_데이터가_나온다(self):
        a = SyntheticGenerator(seed=7).generate(50)
        b = SyntheticGenerator(seed=7).generate(50)

        assert [s.label for s in a] == [s.label for s in b]
        assert [s.bl.bl_no for s in a] == [s.bl.bl_no for s in b]

    def test_하자_비율을_따른다(self):
        samples = SyntheticGenerator(seed=1).generate(500, defect_ratio=0.3)
        injected = sum(1 for s in samples if s.injected)

        assert 0.2 < injected / len(samples) < 0.4

    def test_하자_없는_건은_룰을_통과한다(self):
        engine = RuleEngine()
        clean = [s for s in SyntheticGenerator(seed=3).generate(200) if not s.injected]

        for sample in clean[:30]:
            verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
            assert not verdict.has_critical, (
                f"정상 건인데 CRITICAL 이 났습니다: "
                f"{[v.rule_id for v in verdict.violations]}"
            )

    def test_주입한_하자는_룰에_걸린다(self):
        engine = RuleEngine()
        samples = SyntheticGenerator(seed=5).generate(200, defect_ratio=1.0)

        caught = sum(
            1 for s in samples
            if engine.verify(s.bl, s.lc, as_of=s.as_of).violations
        )
        assert caught / len(samples) > 0.9

    def test_라벨이_룰_결과와_완전히_같지는_않다(self):
        # 같으면 모델이 룰의 복제본이 되어 얹을 이유가 없다.
        engine = RuleEngine()
        samples = SyntheticGenerator(seed=11).generate(400)

        mismatched = sum(
            1 for s in samples
            if engine.verify(s.bl, s.lc, as_of=s.as_of).has_critical != bool(s.label)
        )
        assert mismatched > 0, "라벨이 룰의 결정론적 함수입니다 — 모델이 배울 게 없습니다"

    def test_모든_하자_유형이_주입_가능하다(self):
        generator = SyntheticGenerator(seed=2)
        seen = set()
        for sample in generator.generate(1000, defect_ratio=1.0):
            seen.update(sample.injected)

        assert seen == set(DEFECT_KINDS)

    def test_충돌하는_하자를_함께_주입하지_않는다(self):
        # late_shipment 와 stale_presentation 은 둘 다 on_board_date 를 쓴다.
        # 함께 주입하면 나중 것이 앞의 것을 덮어쓰는데 injected 에는 둘 다
        # 남아, 서류에 없는 하자를 라벨이 주장하게 된다.
        samples = SyntheticGenerator(seed=13).generate(500, defect_ratio=1.0)

        for sample in samples:
            kinds = set(sample.injected)
            assert not {"late_shipment", "stale_presentation"} <= kinds

    def test_주입한_제시기간_경과는_빠짐없이_걸린다(self):
        # 라벨과 서류가 어긋나면 유형별 재현율이 검출기가 아니라 생성기의
        # 결함을 재게 된다.
        engine = RuleEngine()
        stale = [
            s for s in SyntheticGenerator(seed=17).generate(600, defect_ratio=1.0)
            if "stale_presentation" in s.injected
        ]
        assert stale, "표본에 제시기간 경과 건이 없습니다"

        for sample in stale:
            verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
            assert "D018" in {v.rule_id for v in verdict.violations}, (
                f"제시기간 경과를 주입했는데 D018 이 걸리지 않았습니다: "
                f"injected={sample.injected}, on_board={sample.bl.on_board_date}"
            )

    def test_학습_검증을_나눈다(self):
        train, valid = SyntheticGenerator(seed=4).split(100, train_ratio=0.7)

        assert len(train) == 70
        assert len(valid) == 30


class TestPredictor:
    def test_모델이_없으면_룰_가중치로_대체한다(self, engine, tmp_path):
        # 학습 전에도 파이프라인 전체가 돌아야 한다.
        predictor = DefectPredictor(model_path=tmp_path / "없음.json")
        bl = BLFields(bl_no=None, consignee=None)
        verdict = engine.verify(bl, LCTerms(), as_of=AS_OF)

        prediction = predictor.predict(bl, LCTerms(), verdict, as_of=AS_OF)

        assert prediction.model == "rules-v1"
        assert prediction.probability == verdict.defect_probability

    def test_학습후_예측하면_모델을_쓴다(self, engine, tmp_path):
        train, _ = SyntheticGenerator(seed=13).split(300)
        rows, labels = [], []
        for sample in train:
            verdict = engine.verify(sample.bl, sample.lc, as_of=sample.as_of)
            rows.append(
                extract_features(sample.bl, sample.lc, verdict, sample.as_of).values
            )
            labels.append(sample.label)

        predictor = DefectPredictor(model_path=tmp_path / "m.json")
        predictor.train(rows, labels, rounds=30)

        bl = BLFields(bl_no="A1234", consignee="X CO., LTD.")
        verdict = engine.verify(bl, LCTerms(), as_of=AS_OF)
        prediction = predictor.predict(bl, LCTerms(), verdict, as_of=AS_OF)

        assert prediction.model == "xgboost-v1"
        assert 0.0 <= prediction.probability <= 1.0

    def test_저장하면_피처_순서도_함께_남는다(self, engine, tmp_path):
        rows = [[0.0] * len(FEATURE_NAMES), [1.0] * len(FEATURE_NAMES)]
        predictor = DefectPredictor(model_path=tmp_path / "m.json")
        predictor.train(rows, [0, 1], rounds=5)

        saved = predictor.save()

        assert saved.exists()
        assert saved.with_suffix(".meta.json").exists()

    def test_부분집합_모델도_전체_피처_행을_받는다(self, engine, tmp_path):
        # 호출부가 자르게 두면 학습과 추론에서 다르게 자를 수 있고,
        # 그 오류는 예외 없이 조용히 틀린 확률로 나온다.
        samples = SyntheticGenerator(seed=21).generate(200)
        rows, labels = [], []
        for s in samples:
            v = engine.verify(s.bl, s.lc, as_of=s.as_of)
            rows.append(extract_features(s.bl, s.lc, v, s.as_of).values)
            labels.append(s.label)

        predictor = DefectPredictor(
            model_path=tmp_path / "raw.json", feature_names=RAW_FEATURE_NAMES
        )
        predictor.train(rows, labels, rounds=20)
        probabilities = predictor.predict_batch(rows)

        assert len(probabilities) == len(rows)
        assert all(0.0 <= p <= 1.0 for p in probabilities)

    def test_부분집합_모델은_룰_출력을_보지_않는다(self, engine, tmp_path):
        samples = SyntheticGenerator(seed=23).generate(300)
        rows, labels = [], []
        for s in samples:
            v = engine.verify(s.bl, s.lc, as_of=s.as_of)
            rows.append(extract_features(s.bl, s.lc, v, s.as_of).values)
            labels.append(s.label)

        predictor = DefectPredictor(
            model_path=tmp_path / "raw.json", feature_names=RAW_FEATURE_NAMES
        )
        predictor.train(rows, labels, rounds=20)

        assert not (set(predictor.feature_importance()) & RULE_DERIVED_FEATURES)

    def test_잘못된_열_수는_예외를_낸다(self, tmp_path):
        predictor = DefectPredictor(
            model_path=tmp_path / "raw.json", feature_names=RAW_FEATURE_NAMES
        )

        with pytest.raises(ValueError, match="열 수가"):
            predictor.train([[0.0] * len(RAW_FEATURE_NAMES)], [1], rounds=5)

    def test_피처_순서가_바뀌면_로드를_거부한다(self, tmp_path):
        # 순서가 어긋나면 모델은 조용히 틀린 답을 낸다.
        import json

        model_path = tmp_path / "m.json"
        predictor = DefectPredictor(model_path=model_path)
        predictor.train([[0.0] * len(FEATURE_NAMES)], [0], rounds=5)
        predictor.save()

        model_path.with_suffix(".meta.json").write_text(
            json.dumps({"feature_names": ["뒤바뀐", "순서"]}), encoding="utf-8"
        )

        with pytest.raises(RuntimeError, match="피처 순서"):
            DefectPredictor(model_path=model_path).predict_batch(
                [[0.0] * len(FEATURE_NAMES)]
            )

    def test_학습_전_배치예측은_거부한다(self, tmp_path):
        predictor = DefectPredictor(model_path=tmp_path / "없음.json")

        with pytest.raises(RuntimeError, match="학습된 모델이 없습니다"):
            predictor.predict_batch([[0.0] * len(FEATURE_NAMES)])


class TestMetrics:
    def test_혼동행렬을_센다(self):
        m = Metrics()
        m.add(True, True)      # TP
        m.add(True, False)     # FP
        m.add(False, True)     # FN
        m.add(False, False)    # TN

        assert (m.true_positive, m.false_positive) == (1, 1)
        assert (m.false_negative, m.true_negative) == (1, 1)
        assert m.precision == 0.5
        assert m.recall == 0.5
        assert m.f1 == 0.5

    def test_예측이_없으면_0으로_둔다(self):
        # 0 나눗셈으로 죽으면 평가 자체가 안 돈다.
        m = Metrics()

        assert m.precision == 0.0
        assert m.f1 == 0.0


class TestEvaluationHarness:
    def test_기획안_목표를_달성한다(self):
        # 기획안 8.1: 합성 검증셋 기준 주입 하자 검출 F1 >= 0.85
        report = evaluate(count=600, seed=42)

        assert report.meets_target, (
            f"F1 {report.best_f1} < 목표 {report.target_f1}\n{report.to_text()}"
        )

    def test_룰_단독과_모델_결합을_나눠_보고한다(self):
        # 합쳐서 하나만 내면 모델의 기여를 알 수 없다.
        report = evaluate(count=400, seed=42)

        assert report.rules_only.f1 > 0
        assert report.rules_plus_model is not None
        assert report.rules_plus_model.f1 > 0

    def test_원시_특징만_학습한_비교군을_함께_낸다(self):
        # 기획안 8.2 — "모델이 룰의 복제본인가"에 수치로 답하려면
        # 룰 없이 어디까지 가는지가 나란히 있어야 한다.
        report = evaluate(count=600, seed=42)

        assert report.raw_features_only is not None
        assert report.raw_features_only.f1 > 0
        assert not (set(report.raw_feature_importance) & RULE_DERIVED_FEATURES)

    def test_비교군은_목표_달성_판정에_끼지_않는다(self):
        # 진단용 축이 기획안 목표 판정을 밀어 올리면 안 된다.
        report = evaluate(count=600, seed=42)

        assert report.best_f1 == max(
            report.rules_only.f1, report.rules_plus_model.f1
        )

    def test_독립성_비교표가_렌더링된다(self):
        text = evaluate(count=400, seed=42).to_text()

        assert "룰·모델 독립성" in text
        assert "원시 특징만" in text
        assert "모델이 더한 F1" in text

    def test_모델을_끄면_룰만_평가한다(self):
        report = evaluate(count=200, seed=42, train_model=False)

        assert report.rules_plus_model is None
        assert report.raw_features_only is None
        assert report.rules_only.total == 60

    def test_유형별_재현율이_유형을_구분한다(self):
        """놓치는 유형이 생기면 그 유형만 떨어져야 한다.

        이전 판은 "전 유형이 1.000 이면 진단 도구 구실을 못 한다"며 값이
        서로 다를 것을 요구했다. 룰 보강으로 전 유형이 1.000 이 되면서 그
        단언은 **검출력이 완성된 상태를 실패로 부르게** 됐다.

        재고 싶은 것은 값의 다양성이 아니라 지표의 분해능이다. 룰 하나를
        일부러 낮춰 그 유형만 떨어지는지 본다.
        """
        from mlModel.evaluate import _per_defect_recall
        from ruleEngine.engine import load_rules

        samples = SyntheticGenerator(seed=42).generate(600, defect_ratio=1.0)
        full = _per_defect_recall(RuleEngine(), samples)

        assert set(full) == set(DEFECT_KINDS)

        # 제시기간 룰을 warning 으로 낮춘다. 판정이 has_critical 이므로
        # 이 유형만 미검출로 잡혀야 한다.
        rules = load_rules()
        for rule in rules:
            if rule["id"] == "D018":
                rule["severity"] = "warning"
        degraded = _per_defect_recall(RuleEngine(rules), samples)

        assert degraded["stale_presentation"] < full["stale_presentation"]
        assert degraded["port_mismatch"] == full["port_mismatch"]

    def test_텍스트_리포트가_렌더링된다(self):
        report = evaluate(count=200, seed=42, train_model=False)
        text = report.to_text()

        assert "F3 하자 검출 성능 평가" in text
        assert "룰엔진 단독" in text

    def test_JSON으로_직렬화된다(self):
        payload = evaluate(count=200, seed=42, train_model=False).to_dict()

        assert "best_f1" in payload
        assert "rules_only" in payload
        assert payload["rules_only"]["confusion"]["tp"] >= 0

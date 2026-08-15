"""조문 인용 검토표 테스트 (기획안 9절 "멘토 기업 실무 검증").

검토표가 룰과 어긋나면 실무자에게 잘못된 것을 보여주게 된다. 그 실패는
조용하다 — 표는 멀쩡히 나오고, 빠진 항목은 그냥 검토되지 않을 뿐이다.
"""

from __future__ import annotations

import review_sheet
from ruleEngine.checks import REGISTRY
from ruleEngine.cross_doc import CROSS_REGISTRY


class Test빠짐없음:
    def test_모든_검사에_사람이_읽을_설명이_있다(self):
        # 빠뜨리면 `presentation_period` 같은 함수 이름이 그대로 실무자에게
        # 나가고, 그 칸은 판단할 수 없어 조용히 건너뛰어진다.
        registered = set(REGISTRY) | set(CROSS_REGISTRY)
        missing = registered - set(review_sheet.CHECK_TEXT)

        assert not missing, f"설명이 없는 검사: {sorted(missing)}"

    def test_쓰이지_않는_설명은_남기지_않는다(self):
        # 룰이 사라졌는데 설명만 남으면 다음 사람이 그 검사가 아직 있는 줄 안다.
        registered = set(REGISTRY) | set(CROSS_REGISTRY)
        stale = set(review_sheet.CHECK_TEXT) - registered

        assert not stale, f"등록되지 않은 검사의 설명: {sorted(stale)}"

    def test_모든_룰이_표에_들어간다(self):
        rules = review_sheet.load_rules()
        text = review_sheet.render_markdown(rules)

        for rule in rules:
            assert rule["title"] in text, f"{rule['id']} 가 표에 없다"

    def test_서류_간_룰도_함께_싣는다(self):
        # 서류 간 룰 10건도 조문을 인용한다. 빠지면 그 인용은 검증되지 않는다.
        ids = {r["id"] for r in review_sheet.load_rules()}

        assert "X001" in ids and "D001" in ids


class Test읽기_쉬움:
    def test_함수_이름이_그대로_나가지_않는다(self):
        text = review_sheet.render_markdown(review_sheet.load_rules())

        for name in set(REGISTRY) | set(CROSS_REGISTRY):
            assert f"| {name} |" not in text, f"함수 이름이 노출됐다: {name}"

    def test_메시지_치환자를_읽을_수_있게_바꾼다(self):
        # `{detail}` 이 그대로 나가면 문장이 끊겨 읽힌다.
        out = review_sheet.readable_message("선적일로부터 {detail}일이 지났습니다.")

        assert "{" not in out
        assert "〈해당 값〉" in out

    def test_치환자가_남지_않는다(self):
        text = review_sheet.render_markdown(review_sheet.load_rules())

        for token in review_sheet.PLACEHOLDER_TEXT:
            assert token not in text, f"치환자가 남았다: {token}"


class Test조문_단위:
    def test_같은_조문은_한_번만_묻는다(self):
        # 룰 단위로 늘어놓으면 같은 질문을 여러 번 하게 되고, 검토가 길어지면
        # 끝까지 못 간다.
        rules = review_sheet.load_rules()
        grouped = review_sheet.group_by_article(rules)

        assert len(grouped) < len(rules)
        # 실제로 여러 룰이 한 조문을 공유하는 경우가 있어야 묶은 의미가 있다.
        assert any(len(v) > 1 for v in grouped.values())

    def test_조문과_해석을_나눈다(self):
        article, interpretation = review_sheet.split_source(
            "UCP 600 Art.14(c) — 서류는 선적일 후 21일 이내에 제시되어야 한다."
        )

        assert article == "UCP 600 Art.14(c)"
        assert interpretation.startswith("서류는 선적일")

    def test_구분자가_없으면_해석은_빈다(self):
        # 지어내지 않는다. 해석이 없는 것과 있는 것은 다르다.
        article, interpretation = review_sheet.split_source("실무관행")

        assert article == "실무관행"
        assert interpretation == ""

    def test_치명_룰을_가진_조문이_먼저_온다(self):
        # 확인이 중간에 끊겨도 중요한 것은 끝나야 한다.
        rules = review_sheet.load_rules()
        text = review_sheet.render_markdown(rules)
        first = text.split("### 1. ")[1].split("\n")[0]
        grouped = review_sheet.group_by_article(rules)

        assert any(r.get("severity") == "critical" for r in grouped[first])

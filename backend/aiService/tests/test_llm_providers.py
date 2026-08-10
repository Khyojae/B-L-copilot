"""LLM 프로바이더 어댑터 테스트.

실제 API 를 부르지 않는다. 확인하려는 것은 응답 품질이 아니라 **실패해도
리포트가 나오는가**이므로, 호출은 가짜로 두고 경계 동작만 본다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from report import apply_narrative, build_report
from report.llm_providers import (
    DEFAULT_GEMINI_MODEL,
    GeminiCompletion,
    LLMError,
    _extract_gemini_text,
    build_completion,
)
from report.narrative import LLMNarrator, TemplateNarrator, default_narrator
from ruleEngine import LCTerms, RuleEngine

AS_OF = datetime(2026, 5, 25)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """환경 변수가 테스트 간에 새지 않게 한다."""
    for key in ("LLM_PROVIDER", "GEMINI_API_KEY", "LLM_MODEL",
                "LLM_MAX_TOKENS", "LLM_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)


def sample_bl() -> dict:
    return {
        "bl_no": "MAEU123456789",
        "consignee": "TO ORDER OF KEB HANA BANK",
        "port_of_loading": "BUSAN, KOREA",
        "port_of_discharge": "LOS ANGELES, USA",
        "on_board_date": "2026-05-20",
        "date_of_issue": "2026-05-22",
    }


def sample_report():
    lc = LCTerms(lc_no="LC-1", latest_shipment_date="2026-05-15",
                 port_of_discharge="NEW YORK, USA")
    verdict = RuleEngine().verify(sample_bl(), lc, as_of=AS_OF)
    return build_report(verdict, sample_bl(), lc, as_of=AS_OF)


class Test팩토리:
    def test_키가_없으면_None(self):
        assert build_completion("gemini") is None

    def test_키가_changeme_면_None(self, monkeypatch):
        """`.env.example` 을 그대로 복사해 둔 상태를 키 있음으로 오인하면
        전 요청이 403 으로 실패한다."""
        monkeypatch.setenv("GEMINI_API_KEY", "changeme")
        assert build_completion("gemini") is None

    def test_모르는_프로바이더는_None(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
        assert build_completion("openai") is None

    def test_키가_있으면_생성된다(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
        completion = build_completion("gemini")
        assert isinstance(completion, GeminiCompletion)
        assert completion.model == DEFAULT_GEMINI_MODEL

    def test_모델과_한도는_환경변수로_바뀐다(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
        monkeypatch.setenv("LLM_MODEL", "gemini-2.5-pro")
        monkeypatch.setenv("LLM_MAX_TOKENS", "1200")
        completion = build_completion("gemini")
        assert completion.model == "gemini-2.5-pro"
        assert completion.max_tokens == 1200

    def test_빈_키로는_생성_자체가_막힌다(self):
        with pytest.raises(LLMError):
            GeminiCompletion(api_key="")


class Test응답_파싱:
    def test_정상_응답에서_본문을_꺼낸다(self):
        data = {"candidates": [{"content": {"parts": [
            {"text": "한 줄 요약\n"}, {"text": "문단입니다."}]}}]}
        assert _extract_gemini_text(data) == "한 줄 요약\n문단입니다."

    def test_후보가_없으면_예외(self):
        """안전 필터에 걸리면 candidates 가 빈다. 빈 문자열로 넘기면
        리포트 요약이 통째로 사라진다."""
        with pytest.raises(LLMError, match="후보가 없습니다"):
            _extract_gemini_text({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}})

    def test_본문이_비면_예외(self):
        data = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
        with pytest.raises(LLMError, match="본문이 비었습니다"):
            _extract_gemini_text(data)


class Test요청_본문:
    def test_시스템과_사용자_메시지가_분리되어_실린다(self, monkeypatch):
        captured = {}

        def fake_post(url, payload, headers, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            return {"candidates": [{"content": {"parts": [{"text": "요약"}]}}]}

        monkeypatch.setattr("report.llm_providers._post_json", fake_post)
        GeminiCompletion(api_key="AIza-x")("시스템 지시", "사실 목록")

        assert "시스템 지시" in json.dumps(captured["payload"]["system_instruction"],
                                        ensure_ascii=False)
        assert captured["payload"]["contents"][0]["parts"][0]["text"] == "사실 목록"
        assert captured["headers"]["x-goog-api-key"] == "AIza-x"
        assert DEFAULT_GEMINI_MODEL in captured["url"]

    def test_온도는_낮게_고정한다(self, monkeypatch):
        """같은 리포트에서 매번 다른 문장이 나오면 사용자가 내용이 바뀐 것으로
        오해한다."""
        captured = {}
        monkeypatch.setattr(
            "report.llm_providers._post_json",
            lambda url, payload, headers, timeout: (
                captured.update(payload=payload),
                {"candidates": [{"content": {"parts": [{"text": "x"}]}}]},
            )[1],
        )
        GeminiCompletion(api_key="AIza-x")("s", "u")
        assert captured["payload"]["generationConfig"]["temperature"] <= 0.3


class Test리포트_통합:
    def test_LLM_요약이_리포트에_반영된다(self, monkeypatch):
        monkeypatch.setattr(
            "report.llm_providers._post_json",
            lambda *a, **k: {"candidates": [{"content": {"parts": [
                {"text": "치명 하자가 있습니다.\n제출 전 정정을 권합니다."}]}}]},
        )
        report = apply_narrative(sample_report(), LLMNarrator(GeminiCompletion(api_key="AIza-x")))

        assert report.headline == "치명 하자가 있습니다."
        assert report.narrative == "제출 전 정정을 권합니다."
        assert report.narrative_source == "llm"

    def test_API가_죽어도_리포트는_완성된다(self, monkeypatch):
        """발표 중 한도 초과·네트워크 단절을 상정한 테스트."""
        def boom(*a, **k):
            raise LLMError("HTTP 429: 호출 한도를 초과했습니다.")

        monkeypatch.setattr("report.llm_providers._post_json", boom)
        report = apply_narrative(sample_report(), LLMNarrator(GeminiCompletion(api_key="AIza-x")))

        assert report.headline, "요약이 비었습니다"
        assert report.narrative
        assert report.narrative_source == "template"

    def test_키가_없으면_템플릿_요약기가_선택된다(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert isinstance(default_narrator(), TemplateNarrator)

    def test_키가_있으면_LLM_요약기가_선택된다(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
        assert isinstance(default_narrator(), LLMNarrator)

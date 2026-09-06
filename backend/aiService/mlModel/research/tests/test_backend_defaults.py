"""백엔드 기본값이 오프라인인지 검사 (설계서 §5.5, 계획서 0단계).

conftest.py 의 autouse 픽스처가 `config.REVIEWER_BACKEND` 를 이미 고정하므로,
모듈 속성을 그대로 읽으면 **픽스처가 넣은 값을 검사하는 무의미한 테스트**가 된다.
따라서 환경변수를 지운 상태로 config 를 다시 로드해 *디스크에 쓰인 기본값*을 본다.
"""

from __future__ import annotations

import importlib

import pytest

_BACKEND_ENV_VARS = ("DEFECT_MODEL_REVIEWER_BACKEND", "DEFECT_MODEL_LLM_FEATURE_BACKEND")


def _reload_config_without_env(monkeypatch: pytest.MonkeyPatch):
    """백엔드 환경변수를 지운 상태로 config 를 재로드한다."""
    for name in _BACKEND_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return importlib.reload(importlib.import_module("f3_research.config"))


def test_reviewer_backend_default_is_constant_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수가 없으면 심사 백엔드는 오프라인(constant_table)이어야 한다."""
    config = _reload_config_without_env(monkeypatch)
    assert config.REVIEWER_BACKEND == "constant_table"


def test_llm_feature_backend_default_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수가 없으면 LLM 피처 백엔드(Group 7)는 오프라인(offline)이어야 한다.

    (계획서 8단계) `null` 이 아니라 `offline` 이 기본값이다 — Group 7 피처가
    항상 NaN 인 채로 남지 않고 결정론적 휴리스틱으로 실제 계산되는 것이 기본
    동작이어야, gen-data 를 그냥 돌렸을 때 LLM 피처가 죽어 있는 걸 놓치지 않는다.
    """
    config = _reload_config_without_env(monkeypatch)
    assert config.LLM_FEATURE_BACKEND == "offline"


def test_api_key_env_vars_are_scrubbed() -> None:
    """autouse 픽스처가 실제로 API 키를 지웠는지 확인한다.

    이 테스트가 깨지면 테스트 스위트가 유료 호출을 할 수 있는 상태라는 뜻이다.
    """
    import os

    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        assert name not in os.environ, f"{name} 가 지워지지 않았다 — 유료 호출 위험"

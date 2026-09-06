"""유료 API 호출 방지 고정 장치.

모든 테스트에서 API 키 환경변수를 삭제하고 심사 백엔드를 constant_table 로 고정해
유료 API 호출이 구조적으로 불가능하게 한다. 백엔드 인자를 깜빡 넘기지 않아도,
목(mock) 주입을 잊어도 네트워크로 나갈 수 없다.

주의: pytest 는 conftest.py 에서 테스트를 수집하지 않는다. 백엔드 기본값 검사는
test_backend_defaults.py 에 둔다.
"""

from __future__ import annotations

import pytest

_API_KEY_ENV_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
)


@pytest.fixture(autouse=True)
def prevent_paid_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """API 키를 지우고 심사 백엔드를 오프라인으로 고정한다(매 테스트, 자동 복원)."""
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)

    from f3_research import config

    monkeypatch.setattr(config, "REVIEWER_BACKEND", "constant_table")
    monkeypatch.setattr(config, "LLM_FEATURE_BACKEND", "offline")

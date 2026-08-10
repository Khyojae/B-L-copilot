"""리포트 공유 링크 (기획안 5절 "PDF 출력·공유 가능").

## 왜 서명 토큰인가

`api/main.py` 가 "저장은 하지 않는다"를 설계로 잡고 있다. 공유를 위해
리포트를 저장하기 시작하면 그 원칙이 깨지고, AI 모듈이 저장소 수명주기
(만료·삭제·권한)까지 떠안게 된다.

그래서 **링크 자체가 입력을 싣는다.** 토큰을 풀면 리포트를 만들 재료가
그대로 나오므로, 서버는 받은 즉시 같은 리포트를 다시 조립한다. 저장소도
DB 도 없고, 재시작해도 링크가 살아 있다(비밀키를 고정한 경우).

대가는 두 가지다. 아래 "한계"를 읽고 쓸 것.

## 한계

**1. 토큰은 암호문이 아니다.** 서명은 위조를 막을 뿐 내용을 가리지 않는다.
링크를 가진 사람은 base64 를 풀어 B/L 원문을 읽을 수 있다. 링크를 받을
사람은 어차피 리포트를 볼 사람이므로 의도상 문제는 아니지만, **링크가
새면 서류가 샌다.** 브라우저 기록·리퍼러·메신저 미리보기로 흐를 수 있으니
만료를 짧게 잡는 것이 유일한 완화책이다.

**2. 링크가 길다.** 입력을 싣기 때문이다. zlib 으로 줄이지만 서류가 크면
2KB 를 넘길 수 있다. `MAX_TOKEN_BYTES` 를 넘으면 만들지 않고 거절한다 —
일부 프록시가 긴 URL 을 잘라 조용히 깨지는 것보다 낫다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import zlib
from typing import Any, Dict, Optional

# 토큰 형식 표지. 서명 방식이 바뀌면 올려서 옛 링크를 명확히 거절한다.
VERSION = "v1"

# 기본 만료. 짧게 잡는 이유는 위 "한계" 1번이다.
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7일

# URL 길이 한계. 브라우저·프록시가 실무상 견디는 선을 보수적으로 잡는다.
MAX_TOKEN_BYTES = 6000

SECRET_ENV = "REPORT_SHARE_SECRET"
_process_secret: Optional[bytes] = None


class ShareTokenError(Exception):
    """토큰을 신뢰할 수 없다."""


class ExpiredShareToken(ShareTokenError):
    """서명은 맞지만 기한이 지났다."""


class ShareTokenTooLarge(ShareTokenError):
    """입력이 커서 링크로 만들 수 없다."""


def share_secret() -> bytes:
    """서명 비밀키.

    환경변수가 없으면 프로세스마다 새로 만든다. 고정 기본값을 두면 소스를
    읽은 누구나 토큰을 위조할 수 있으므로, **재시작 시 링크가 죽는 쪽**을
    택한다. 링크를 오래 살리려면 `REPORT_SHARE_SECRET` 를 설정할 것.
    """
    global _process_secret
    configured = os.getenv(SECRET_ENV)
    if configured:
        return configured.encode("utf-8")
    if _process_secret is None:
        _process_secret = secrets.token_bytes(32)
    return _process_secret


def secret_is_ephemeral() -> bool:
    """비밀키가 프로세스 임시값인지. 기동 로그와 응답 경고에 쓴다."""
    return not os.getenv(SECRET_ENV)


def encode(
    payload: Dict[str, Any],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: Optional[float] = None,
    secret: Optional[bytes] = None,
) -> str:
    """리포트 입력을 서명 토큰으로 만든다."""
    issued = int(now if now is not None else time.time())
    body = {"exp": issued + int(ttl_seconds), "iat": issued, "data": payload}

    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)
    packed = _b64encode(zlib.compress(raw.encode("utf-8"), 9))
    signed = f"{VERSION}.{packed}"
    token = f"{signed}.{_b64encode(_sign(signed, secret or share_secret()))}"

    if len(token) > MAX_TOKEN_BYTES:
        raise ShareTokenTooLarge(
            f"공유 링크가 너무 깁니다 ({len(token)} > {MAX_TOKEN_BYTES}자). "
            "서류 항목을 줄이거나 PDF 를 직접 내려받아 전달하세요."
        )
    return token


def decode(
    token: str,
    now: Optional[float] = None,
    secret: Optional[bytes] = None,
) -> Dict[str, Any]:
    """토큰을 검증하고 원래 입력을 돌려준다.

    검증 순서가 중요하다. **서명을 먼저 확인하고 그 다음에 압축을 푼다.**
    반대로 하면 서명 없는 입력을 zlib 에 먹이게 되어, 압축폭탄이 서명 검사
    앞에서 터진다.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ShareTokenError("토큰 형식이 올바르지 않습니다.")

    version, packed, signature = parts
    if version != VERSION:
        raise ShareTokenError(f"지원하지 않는 토큰 버전입니다: {version}")

    expected = _sign(f"{version}.{packed}", secret or share_secret())
    try:
        provided = _b64decode(signature)
    except Exception as exc:  # noqa: BLE001
        raise ShareTokenError("서명을 해석할 수 없습니다.") from exc
    if not hmac.compare_digest(expected, provided):
        raise ShareTokenError("서명이 일치하지 않습니다.")

    try:
        body = json.loads(zlib.decompress(_b64decode(packed)).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ShareTokenError("토큰 본문을 해석할 수 없습니다.") from exc

    current = now if now is not None else time.time()
    if current > body.get("exp", 0):
        raise ExpiredShareToken("공유 링크가 만료되었습니다. 새로 발급하세요.")

    return body["data"]


def expires_at(token: str, secret: Optional[bytes] = None) -> int:
    """만료 시각(epoch). 발급 응답이 언제까지 유효한지 알리는 데 쓴다."""
    packed = token.split(".")[1]
    body = json.loads(zlib.decompress(_b64decode(packed)).decode("utf-8"))
    return int(body["exp"])


# ── 내부 ─────────────────────────────────────────────────────────

def _sign(message: str, secret: bytes) -> bytes:
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).digest()


def _b64encode(raw: bytes) -> str:
    """URL 안전 base64. 패딩(`=`)은 뺀다 — URL 에서 인코딩되어 지저분해진다."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

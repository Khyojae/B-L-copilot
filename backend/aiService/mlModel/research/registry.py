"""레지스트리와 롤백 (설계서 8절).

`model_version` 테이블 운용. `src/smart_e_bl/models/verdicts.py` 의 ORM 을
지연 import 한다 — DB 가 없는 환경에서도 학습(`train.py`)이 돌아가야 하므로,
이 모듈의 함수들은 실제로 호출될 때만 `smart_e_bl` 을 import 한다.

기획안 5.3: 재학습 후 검증셋 성능이 하락하면 이전 모델로 자동 롤백한다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any


def build_version_string(
    feature_schema_version: str,
    fingerprint: dict[str, Any],
    trained_on: date | None = None,
) -> str:
    """{FEATURE_SCHEMA_VERSION}-{YYYYMMDD}-{짧은해시} (설계서 8절).

    해시는 `fingerprint`(데이터셋 매니페스트 + 하이퍼파라미터)와
    `feature_schema_version` 으로만 결정된다 — 프로세스 임의성(`id(object())`)에
    의존하지 않으므로 동일 입력이면 항상 동일 버전 문자열이 나온다(재현성).
    """
    trained_on = trained_on or date.today()
    stamp = trained_on.strftime("%Y%m%d")
    payload = json.dumps(
        {"feature_schema_version": feature_schema_version, "fingerprint": fingerprint},
        sort_keys=True,
        default=str,
    )
    salt = hashlib.sha256(payload.encode()).hexdigest()[:6]
    return f"{feature_schema_version}-{stamp}-{salt}"


def get_active_version(session: Any) -> Any | None:
    """현재 활성 model_version 행(또는 None)을 반환한다."""
    from sqlalchemy import select

    from smart_e_bl.models.verdicts import ModelVersion

    return session.execute(
        select(ModelVersion).where(ModelVersion.is_active.is_(True))
    ).scalar_one_or_none()


def register(
    session: Any,
    version: str,
    metrics: dict[str, float],
    label_count: int,
    note: str | None = None,
) -> Any:
    """model_version 을 is_active=false 로 등록한다."""
    from smart_e_bl.models.verdicts import ModelVersion

    row = ModelVersion(
        version=version,
        training_label_count=label_count,
        metric_f1=metrics.get("f1"),
        metric_roc_auc=metrics.get("roc_auc"),
        metric_brier=metrics.get("brier"),
        is_active=False,
        note=note,
    )
    session.add(row)
    session.flush()
    return row


def activate(session: Any, version: str) -> None:
    """기존 활성 모델을 해제하고 지정 버전을 활성화한다(단일 트랜잭션)."""
    from sqlalchemy import update

    from smart_e_bl.models.verdicts import ModelVersion

    session.execute(update(ModelVersion).values(is_active=False).where(ModelVersion.is_active.is_(True)))
    session.execute(update(ModelVersion).values(is_active=True).where(ModelVersion.version == version))
    session.commit()


def rollback(session: Any, to_version: str, reason: str) -> None:
    """`rolled_back_from` 에 직전(현재) 활성 버전을 기록하고 to_version 을 활성화한다."""
    current = get_active_version(session)
    from sqlalchemy import update

    from smart_e_bl.models.verdicts import ModelVersion

    session.execute(update(ModelVersion).values(is_active=False).where(ModelVersion.is_active.is_(True)))
    session.execute(
        update(ModelVersion)
        .values(is_active=True, rolled_back_from=current.version if current else None, note=reason)
        .where(ModelVersion.version == to_version)
    )
    session.commit()


def should_activate(new_f1: float | None, active_f1: float | None) -> bool:
    """기획안 5.3: 재학습 후 검증셋 성능이 하락하면 활성화하지 않는다.

    활성 모델이 아직 없으면(최초 등록) 항상 활성화한다.
    """
    if active_f1 is None:
        return True
    if new_f1 is None:
        return False
    return new_f1 >= active_f1

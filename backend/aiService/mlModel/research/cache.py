"""범용 append-only JSONL 캐시 (계획서 8단계 Task 1).

원래 `synth/review.py` 안에 `ReviewCache` 로만 있던 것을 일반화해 여기로
옮긴다. Claude 심사 캐시(`synth/review.py`)와 LLM 피처 캐시(`llm_features.py`)가
이 구현 하나를 공유한다 — 둘 다 "콘텐츠 해시 → 판정/피처" 라는 같은 모양의
캐시가 필요하고(설계서 5.5 "판정 캐시가 재현성 아티팩트다"), 로직을 두 번
베끼면 한쪽만 고치고 잊는 사고가 난다.

`synth/review.py::ReviewCache = JsonlCache` 별칭으로 하위 호환을 유지한다 —
`tests/test_review_claude.py::test_review_cache_round_trip` 가 이 이름으로
참조한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlCache:
    """콘텐츠 해시 키의 append-only JSONL 캐시.

    레코드는 `key_field`(기본 `"hash"`) 키를 가진 dict 여야 한다. 생성 시점에
    파일이 있으면 전부 메모리로 읽어들이고, `put()` 은 메모리와 파일 양쪽에
    추가한다(덮어쓰기가 아니라 append — 캐시 파일 자체가 재현성 아티팩트라
    저장소에 커밋해 제3자가 API 호출 없이도 동일 산출물을 재생성할 수 있게
    한다, 설계서 5.5).
    """

    def __init__(self, path: Path, *, key_field: str = "hash") -> None:
        self.path = path
        self.key_field = key_field
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = record.get(self.key_field)
            if key:
                self._entries[key] = record

    def get(self, key: str) -> dict[str, Any] | None:
        return self._entries.get(key)

    def put(self, record: dict[str, Any]) -> None:
        key = record[self.key_field]
        self._entries[key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

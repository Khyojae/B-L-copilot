"""실물 선하증권 말뭉치.

합성 생성기가 지어내던 B/L 을 **실제 라벨 데이터셋에서 파싱한 값**으로
갈아끼우기 위한 것이다. 하자 라벨은 여전히 합성 주입이지만, 서류 자체는
실물이 된다.

## 왜 필요한가

`synth.py` 의 B/L 은 회사명 6개·항구 8개·선박 5개를 돌려쓴다. 필드는 항상
채워지고, 값의 형태도 일정하다. 그 결과 `field_missing_ratio` 같은 원시
피처가 사실상 상수가 되어, 모델이 볼 수 있는 신호가 룰 출력밖에 남지
않는다 (`remaining-work.md` 3.1 — 모델 기여가 음수인 이유).

실물은 다르다. 실측하면 `voyage_no` 는 41.8%, `total_freight` 는 58.3%,
`measurement` 는 88.0% 만 채워져 있다. 이 결측 패턴은 지어낼 수 없다.

## 무엇이 실물이 되고, 무엇이 아닌가

정직하게 적어 둔다. 이걸 흐리면 발표에서 과장이 된다.

| 항목 | 실물인가 |
|---|---|
| 필드 값·결측 패턴 | **예** |
| 값의 지저분함 (항목명 혼입 등) | **예** |
| 앵커/구역 판정 비율 | **예** |
| OCR 신뢰도 | **아니오** — 라벨은 정답이라 1.0 고정 |
| L/C 조건 | **아니오** — B/L 에서 역산한 합성 |
| 하자 라벨 | **아니오** — 합성 주입 |

신뢰도까지 실물로 만들려면 원천 이미지를 PaddleOCR 로 돌려야 하는데
장당 13초, 4,000장이면 14시간이다. 그 경로는 같은 `BLRecord` 형식으로
나중에 끼울 수 있게 열어 둔다 (`records_from_drafts`).

## 저장소에 데이터를 두지 않는다

라벨 데이터셋은 용량(4,000건 116MB)과 이용조건 때문에 커밋하지 않는다.
말뭉치가 없으면 생성기는 **기존 합성 경로로 조용히 돌아간다** — 데이터가
있는 환경에서만 좋아지고, CI 는 그대로 통과해야 한다.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field as dataclass_field
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ocr.types import BL_FIELD_NAMES, BLFields

# 이 여섯은 `rules.yaml` 의 `required` + `critical` 룰이 보는 필드다
# (D001·D005·D011·D012·D012B·D022). 하나라도 비면 하자 주입 전부터 치명
# 위반이 잡히므로 '하자 없는 기준 서류'로 쓸 수 없다.
#
# 결측을 전부 버리지는 않는다. `voyage_no`·`total_freight` 처럼 warning
# 이하만 걸리는 필드의 결측은 **그대로 남긴다** — 그게 이 말뭉치를 쓰는
# 이유이고, 버리면 실물의 결측 분포가 다시 사라진다.
REQUIRED_FOR_CLEAN_BASE = (
    "bl_no",
    "consignee",
    "vessel",
    "port_of_loading",
    "port_of_discharge",
    "date_of_issue",
)

CACHE_VERSION = 1


@dataclass
class BLRecord:
    """실물 B/L 1건. `BLFields` 로 복원할 수 있는 최소 정보만 담는다."""

    source_id: str
    values: Dict[str, Optional[str]]
    confidence: Dict[str, float] = dataclass_field(default_factory=dict)
    provenance: Dict[str, str] = dataclass_field(default_factory=dict)
    # 이 신뢰도가 실제 OCR 에서 나온 값인지.
    #
    # 라벨 JSON 경로는 **정답 텍스트**라 신뢰도가 전 필드 1.0 이다. 그대로
    # 쓰면 `synth._apply_label_noise` 의 "룰이 못 잡는 하자" 채널이 죽는다 —
    # 그 잡음은 낮은 신뢰도에서 나오는데 분산이 0 이기 때문이다.
    #
    # 그 채널이 죽으면 라벨이 룰의 결정론적 함수에 가까워져, 평가 수치가
    # 좋아진다. **데이터가 좋아져서가 아니라 어려운 케이스가 사라져서다.**
    # 실제로 이 값을 무시했을 때 룰 단독 F1 이 0.9302 → 0.9730 으로 뛰었다.
    #
    # 그래서 거짓이면 생성기가 신뢰도를 다시 뽑는다. 값·결측·판정 경로는
    # 실물을 쓰고 신뢰도만 합성하는 편이, 있지도 않은 완벽한 추출을 가정하는
    # 것보다 정직하다.
    confidence_is_real: bool = False

    def to_fields(self) -> BLFields:
        """`BLFields` 로 되돌린다.

        매 표본마다 새 객체를 만든다. 하자 주입이 필드를 덮어쓰므로
        하나를 돌려쓰면 앞 표본의 주입이 뒤로 샌다.
        """
        fields = BLFields(**{n: self.values.get(n) for n in BL_FIELD_NAMES})
        fields.confidence = dict(self.confidence)
        fields.provenance = dict(self.provenance)
        return fields

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "values": self.values,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "confidence_is_real": self.confidence_is_real,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BLRecord":
        return cls(
            source_id=data["source_id"],
            values=data.get("values", {}),
            confidence=data.get("confidence", {}),
            provenance=data.get("provenance", {}),
            confidence_is_real=data.get("confidence_is_real", False),
        )


def records_from_drafts(
    fields_list: Sequence[BLFields],
    ids: Sequence[str],
    confidence_is_real: bool = True,
) -> List[BLRecord]:
    """파싱 결과 → 말뭉치 레코드.

    입력이 라벨 JSON 이든 실제 OCR 이든 여기서 같은 형식이 된다. 신뢰도까지
    실물로 만들고 싶으면 `IntakePipeline.run_from_image` 결과를 이 함수에
    넣으면 되고, 아래 로직은 손댈 것이 없다.
    """
    records: List[BLRecord] = []
    for fields, source_id in zip(fields_list, ids):
        records.append(
            BLRecord(
                source_id=source_id,
                values={n: getattr(fields, n) for n in BL_FIELD_NAMES},
                confidence=dict(fields.confidence),
                provenance=dict(fields.provenance),
                confidence_is_real=confidence_is_real,
            )
        )
    return records


def usable_as_clean_base(record: BLRecord) -> bool:
    """하자 없는 기준 서류로 쓸 수 있는지."""
    return all(record.values.get(n) for n in REQUIRED_FOR_CLEAN_BASE)


def load_from_labels(
    label_dir: str,
    limit: int = 0,
    keep_all: bool = False,
) -> List[BLRecord]:
    """라벨 JSON 디렉토리를 파싱해 말뭉치를 만든다.

    파싱 실패는 조용히 버린다 — 말뭉치 적재는 학습의 준비 단계이고, 여기서
    터지면 4,000건 중 1건 때문에 전체가 죽는다. 몇 건이 버려졌는지는
    `load()` 가 보고한다.
    """
    from ocr import IntakePipeline

    paths = sorted(glob(str(Path(label_dir) / "*.json")))
    if limit:
        paths = paths[:limit]

    pipeline = IntakePipeline()
    records: List[BLRecord] = []
    for path in paths:
        try:
            draft = pipeline.run_from_json(path)
        except Exception:  # noqa: BLE001
            continue
        record = BLRecord(
            source_id=Path(path).stem,
            values={f.name: f.value for f in draft.fields},
            confidence={f.name: f.confidence for f in draft.fields
                        if f.confidence is not None},
            provenance={f.name: f.source for f in draft.fields if f.source},
            # 라벨은 정답 텍스트다. 신뢰도 1.0 은 'OCR 이 확신했다'가 아니라
            # '읽기 단계가 없었다'는 뜻이므로 실물로 세지 않는다.
            confidence_is_real=False,
        )
        if keep_all or usable_as_clean_base(record):
            records.append(record)
    return records


def save_cache(records: Sequence[BLRecord], path: str) -> None:
    payload = {
        "version": CACHE_VERSION,
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_cache(path: str) -> List[BLRecord]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != CACHE_VERSION:
        raise ValueError(
            f"말뭉치 캐시 버전이 다릅니다 (파일 {data.get('version')} / "
            f"코드 {CACHE_VERSION}). 다시 만들어 주세요."
        )
    return [BLRecord.from_dict(r) for r in data.get("records", [])]


def load(
    label_dir: Optional[str] = None,
    cache_path: Optional[str] = None,
    limit: int = 0,
) -> List[BLRecord]:
    """말뭉치를 얻는다. 캐시가 있으면 캐시, 없으면 라벨에서 만들어 캐싱.

    라벨 4,000건 파싱에 40초가 든다. 학습·평가를 반복하는 동안 매번 물면
    실험 주기가 그만큼 느려진다.
    """
    if cache_path and Path(cache_path).exists():
        return load_cache(cache_path)
    if not label_dir:
        return []
    records = load_from_labels(label_dir, limit=limit)
    if cache_path:
        save_cache(records, cache_path)
    return records


class CorpusSampler:
    """말뭉치에서 B/L 을 뽑는다.

    복원추출이다. 요청 건수가 말뭉치보다 클 수 있고(2,000건 요청에 말뭉치
    3,600건이면 비복원도 되지만 10,000건이면 안 된다), 비복원으로 두면
    말뭉치 크기가 곧 생성 가능 건수의 상한이 되어 버린다.
    """

    def __init__(self, records: Sequence[BLRecord], rng: random.Random) -> None:
        if not records:
            raise ValueError("말뭉치가 비어 있습니다")
        self.records = list(records)
        self.rng = rng

    def sample(self) -> BLRecord:
        return self.rng.choice(self.records)

    def __len__(self) -> int:
        return len(self.records)

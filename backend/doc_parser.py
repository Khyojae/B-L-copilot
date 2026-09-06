"""
서류 종류 공통 파서 (앵커 전용).

`doc_types.SPECS` 에 선언된 서류를 뽑는다. 선하증권은 좌표 교정본이 있어
`field_parser.FieldParser` 가 따로 처리한다 — 이유는 `doc_types` 도입부에
적었다.

## 앵커 하나만 쓴다

항목명을 찾고 그 오른쪽·아래를 값으로 읽는다. 좌표 구역을 쓰지 않으므로
서식 레이아웃에 덜 민감한 대신, 항목명 표기가 다르면 놓친다.

놓치는 쪽이 지어내는 쪽보다 낫다. 값이 없으면 초안이 빈칸으로 두고 사람에게
묻지만, 엉뚱한 구역에서 집어온 값은 그럴듯해서 그대로 검증까지 흘러간다.

## 신뢰도

앵커로 찾은 값은 전부 `ANCHOR_CONFIDENCE_PENALTY` 를 곱한다. 좌표로 찾은
값과 같은 신뢰도를 주면 초안 편집기가 확인을 유도하지 않는다.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .doc_types import DocumentSpec
from .types import ANCHOR_CONFIDENCE_PENALTY, BBox, OCRResult

# 값으로 읽을 bbox 최대 개수. 넘기면 옆 칸 내용까지 딸려 온다.
_MAX_VALUE_BOXES = 6

# 항목명 오른쪽을 같은 줄로 볼 세로 허용치 (줄 높이 배수).
_SAME_LINE_TOLERANCE = 0.7

# 다음 항목명으로 볼 최소 길이. draft._MIN_LABEL_LENGTH 와 같은 이유로
# 짧은 조각은 제외한다 — "TO", "QTY" 는 값에도 흔히 들어간다.
_MIN_LABEL_LENGTH = 6

# 항목명 아래를 값으로 볼 범위 (줄 높이 배수).
_BELOW_MIN = 0.3
_BELOW_MAX = 2.5


class DocumentFields:
    """서류 한 건에서 뽑은 값.

    선하증권의 `BLFields` 와 달리 필드가 서류 종류마다 다르므로 dict 로 둔다.
    고정 dataclass 로 만들면 종류를 추가할 때마다 클래스가 늘어난다.
    """

    def __init__(self, spec: DocumentSpec) -> None:
        self.spec = spec
        self.values: Dict[str, Optional[str]] = {f: None for f in spec.fields}
        self.confidence: Dict[str, float] = {}
        self.provenance: Dict[str, str] = {}
        self.bbox: Dict[str, List[BBox]] = {}

    def set_field(
        self,
        name: str,
        value: Optional[str],
        confidence: float,
        source: str,
        bboxes: Optional[List[BBox]] = None,
    ) -> None:
        self.values[name] = value
        if value:
            self.confidence[name] = round(confidence, 4)
            self.provenance[name] = source
            if bboxes:
                self.bbox[name] = bboxes

    def get(self, name: str) -> Optional[str]:
        return self.values.get(name)

    def missing_critical_fields(self) -> List[str]:
        return [f for f in self.spec.critical if not self.values.get(f)]

    def to_dict(self) -> Dict[str, Optional[str]]:
        return dict(self.values)


class DocumentParser:
    """OCRResult → DocumentFields (앵커 전용)."""

    def parse(self, ocr: OCRResult, spec: DocumentSpec) -> DocumentFields:
        fields = DocumentFields(spec)
        bboxes = sorted(ocr.bboxes, key=lambda b: (b.center_y, b.x_min))

        for name in spec.fields:
            found = self._find(bboxes, spec.anchors.get(name, []), spec)
            if found is None:
                continue
            value, confidence, picked = found
            cleaned = _clean(value)
            if cleaned:
                fields.set_field(name, cleaned, confidence, "anchor", picked)

        return fields

    # ── 내부 ─────────────────────────────────────────────────────

    def _find(
        self, bboxes: List[BBox], candidates: List[str], spec: DocumentSpec
    ) -> Optional[tuple]:
        anchor = self._locate(bboxes, candidates)
        if anchor is None:
            return None

        line_height = max(anchor.y_max - anchor.y_min, 20)
        values = [
            b
            for b in bboxes
            if b is not anchor
            and (
                (abs(b.center_y - anchor.center_y) <= line_height * _SAME_LINE_TOLERANCE
                 and b.x_min >= anchor.x_max)
                or (anchor.center_y + line_height * _BELOW_MIN
                    < b.center_y
                    < anchor.center_y + line_height * _BELOW_MAX
                    and anchor.x_min - line_height
                    <= b.x_min
                    <= anchor.x_max + line_height * 4)
            )
        ]
        if not values:
            return None

        picked = _stop_at_next_label(values, spec)[:_MAX_VALUE_BOXES]
        if not picked:
            return None
        mean = sum(b.confidence for b in picked) / len(picked)
        return " ".join(b.text for b in picked), mean * ANCHOR_CONFIDENCE_PENALTY, picked

    @staticmethod
    def _locate(bboxes: List[BBox], candidates: List[str]) -> Optional[BBox]:
        """항목명 bbox 를 찾는다.

        후보를 **긴 것부터** 본다. `INVOICE NO` 와 `INVOICE DATE` 가 한 지면에
        같이 있을 때 `INVOICE` 로 먼저 걸리면 어느 쪽인지 알 수 없다.

        **짧은 후보는 낱말 경계로만 맞춘다.** 부분 문자열로 찾으면 `TO`(매수인
        후보)가 `SANTOS` 안에서 걸린다. 실제로 그렇게 잡힌 값이 매수인 자리에
        `SANTOS EXPRESS 24-Dec-2019 V.928` 로 들어갔다 — 선사명·날짜·항차를
        매수인으로 읽은 것이다.

        틀린 값이 들어가는 대가는 빈칸보다 크다. 빈칸은 사람에게 묻지만,
        그럴듯한 오값은 **LLM 보충 대상에서도 빠져** 그대로 검증까지 흘러간다.
        """
        for cand in sorted(candidates, key=len, reverse=True):
            target = _normalize(cand)
            if not target:
                continue
            for bbox in bboxes:
                if _label_matches(target, _normalize(bbox.text)):
                    return bbox
        return None


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", " ", text.upper()).strip()


def _label_matches(target: str, text: str) -> bool:
    """항목명 후보가 이 칸의 글자와 맞는지.

    긴 후보는 부분 문자열로도 인정한다 — `INVOICE NO` 는 `COMMERCIAL INVOICE NO.`
    안에 있어도 그 항목명이 맞다. 짧은 후보는 **낱말 단위로 정확히** 맞아야
    한다. `_stop_at_next_label` 이 경계 판정에 쓰는 기준과 같은 길이를 쓴다.
    """
    if not target or not text:
        return False
    if len(target) >= _MIN_LABEL_LENGTH:
        return target in text
    return target in text.split()


def _stop_at_next_label(boxes: List[BBox], spec: DocumentSpec) -> List[BBox]:
    """다음 항목명이 나오면 거기서 값 수집을 끊는다.

    항목명 아래·오른쪽을 값으로 읽는 방식은 **다음 칸의 항목명까지 함께
    집어온다.** 실제로 송장에서 `INVOICE NO` 의 값이
    "INV-2026-0417 INVOICE DATE" 로 나왔다.

    그 상태는 초안 편집기가 잡아 주기는 하지만(`LABEL_ECHOED`), 애초에
    안 집어오는 편이 낫다 — 확인 대기열은 사람이 봐야 고쳐지는 비용이고,
    파서가 스스로 끊을 수 있는 경계라면 끊는 것이 맞다.
    """
    labels = {
        _normalize(phrase)
        for group in spec.anchors.values()
        for phrase in group
    }
    # 긴 항목명은 값 안에 섞여 있어도 경계로 본다. 짧은 것은 **칸 전체가
    # 그 항목명일 때만** 본다 — `DATE`(4자)는 포장명세서의 실제 항목명이지만,
    # 부분 일치까지 허용하면 값에 들어간 같은 글자에도 끊긴다.
    long_labels = {label for label in labels if len(label) >= _MIN_LABEL_LENGTH}

    kept: List[BBox] = []
    for box in boxes:
        text = _normalize(box.text)
        if text in labels or any(label in text for label in long_labels):
            break
        kept.append(box)
    return kept


def _clean(text: str) -> Optional[str]:
    """값 양끝의 구분 기호를 걷어낸다.

    마침표는 **끝에서만, 그것도 뒤에 공백이 붙은 경우가 아니면 남긴다** —
    `GAE WOON CO., LTD.` 의 마지막 점은 구분 기호가 아니라 상호의 일부다.
    지우면 서류 간 상호 대조에서 표기가 갈린다.
    """
    value = re.sub(r"\s+", " ", text).strip()
    return value.strip(" :;,-·") or None

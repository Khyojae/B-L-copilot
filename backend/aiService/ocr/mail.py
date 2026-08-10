"""
이메일 입력 (기획안 5절 "이메일·엑셀·PDF 등 비정형 선적 서류").

## 첨부가 서류다

무역 실무에서 이메일로 서류를 받으면 **본문은 대개 안내문이고 첨부가 서류**다.
"Please find attached the B/L for shipment ..." 같은 본문에서 필드를 뽑으면
선하증권이 아니라 인사말을 파싱하게 된다.

그래서 첨부를 먼저 본다. 지원하는 첨부가 있으면 그쪽을 서류로 삼고, 없을
때만 본문을 읽는다. 어느 쪽을 읽었는지는 `OCRResult.source` 에 남는다
(`email-pdf` / `email-excel` / `email-image` / `email-body`).

## 본문을 읽을 때 — 한 줄을 둘로 쪼갠다

본문 서류는 대개 `B/L NO: SMBL2026080001` 형태다. 한 줄을 BBox 하나로 만들면
라벨과 값이 같은 상자에 들어가고, 앵커 탐색은 "라벨 오른쪽 상자"를 찾으므로
아무것도 못 찾는다. 그래서 첫 콜론에서 갈라 좌우 두 상자로 놓는다.

## 신뢰도

본문 텍스트는 1.0 이다. 글자를 그대로 읽었을 뿐 추측하지 않았다. 첨부를
읽은 경우 신뢰도는 그 경로(PDF 텍스트 레이어·OCR·엑셀)의 것을 따른다.
"""

from __future__ import annotations

import email
from dataclasses import dataclass, field
from email import policy
from pathlib import Path
from typing import List, Optional, Tuple

from .types import BBox, OCRResult

_CANVAS_WIDTH = 1654
_CANVAS_HEIGHT = 2340

# 본문 한 줄의 높이. 캔버스를 이 줄 수로 나눈다. 실제 줄이 적어도 이 값을
# 쓰는 이유는 spreadsheet 와 같다 — 줄이 세 개인 본문에서 한 줄이 지면
# 3분의 1을 차지하면 앵커의 '같은 줄' 판정이 무너진다.
_MIN_LINES = 40

# 라벨과 값을 가르는 x 좌표. 실제 이메일에 열 개념이 없으므로 임의로 정한다.
# 앵커 탐색은 "값이 라벨 오른쪽에 있다"만 보므로 경계 위치 자체는 중요하지 않고,
# 라벨과 값이 겹치지 않는 것만 지키면 된다.
_LABEL_RIGHT = int(_CANVAS_WIDTH * 0.38)
_LABEL_GUTTER = int(_CANVAS_WIDTH * 0.02)

# 첨부 우선순위. PDF 가 가장 앞인 이유는 텍스트 레이어를 가질 가능성이 높아
# OCR 없이 정확하게 읽히기 때문이다. 이미지가 마지막이다 — 유일하게 추측이
# 들어가는 경로다.
ATTACHMENT_PRIORITY = (
    ("pdf", (".pdf",)),
    ("excel", (".xlsx", ".xlsm")),
    ("image", (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")),
)

MAX_BODY_LINES = 300


@dataclass
class Attachment:
    """이메일 첨부 하나."""

    filename: str
    payload: bytes
    kind: str  # "pdf" | "excel" | "image"

    @property
    def suffix(self) -> str:
        return Path(self.filename).suffix.lower() or f".{self.kind}"


@dataclass
class EmailContent:
    """이메일에서 뽑아낸 것."""

    subject: str = ""
    body: str = ""
    attachments: List[Attachment] = field(default_factory=list)

    def best_attachment(self) -> Optional[Attachment]:
        """서류로 삼을 첨부. 우선순위가 높은 것부터 고른다."""
        for kind, _ in ATTACHMENT_PRIORITY:
            for item in self.attachments:
                if item.kind == kind:
                    return item
        return None


def parse_email(path: str) -> EmailContent:
    """`.eml` 파일을 읽는다."""
    with open(path, "rb") as handle:
        message = email.message_from_binary_file(handle, policy=policy.default)

    content = EmailContent(subject=str(message.get("Subject") or ""))

    body_part = message.get_body(preferencelist=("plain",))
    if body_part is not None:
        content.body = body_part.get_content()

    for part in message.iter_attachments():
        filename = part.get_filename() or ""
        kind = _classify(filename)
        if kind is None:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            content.attachments.append(Attachment(filename, payload, kind))

    return content


def _classify(filename: str) -> Optional[str]:
    suffix = Path(filename).suffix.lower()
    for kind, suffixes in ATTACHMENT_PRIORITY:
        if suffix in suffixes:
            return kind
    return None


def body_to_result(content: EmailContent, image_id: str) -> OCRResult:
    """본문 텍스트를 OCRResult 로. 첨부가 없을 때만 쓴다."""
    bboxes = _body_bboxes(content)
    if not bboxes:
        raise ValueError("본문이 비어 있고 읽을 수 있는 첨부도 없습니다.")

    return OCRResult(
        image_id=image_id,
        image_width=_CANVAS_WIDTH,
        image_height=_CANVAS_HEIGHT,
        form_type="선하증권",
        bboxes=bboxes,
        source="email-body",
    )


def _body_bboxes(content: EmailContent) -> List[BBox]:
    lines = [ln.strip() for ln in content.body.splitlines()]
    lines = [ln for ln in lines if ln][:MAX_BODY_LINES]
    if content.subject:
        # 제목에 B/L 번호가 실리는 일이 흔하다. 첫 줄로 넣는다.
        lines.insert(0, content.subject)
    if not lines:
        return []

    line_h = _CANVAS_HEIGHT / max(len(lines), _MIN_LINES)

    bboxes: List[BBox] = []
    for index, line in enumerate(lines):
        y_min = int(index * line_h)
        y_max = int((index + 1) * line_h)
        for text, x_min, x_max in _split_line(line):
            bboxes.append(
                BBox(text=text, x_min=x_min, y_min=y_min,
                     x_max=x_max, y_max=y_max, confidence=1.0)
            )
    return bboxes


def _split_line(line: str) -> List[Tuple[str, int, int]]:
    """`라벨: 값` 을 좌우 두 상자로. 콜론이 없으면 한 상자다."""
    label, sep, value = line.partition(":")
    label, value = label.strip(), value.strip()

    if not sep or not label or not value:
        return [(line, 0, _CANVAS_WIDTH)]

    # 라벨 상자를 여백만큼 줄인다. 딱 붙이면 라벨의 x_max 와 값의 x_min 이
    # 같아지는데, 앵커 탐색은 값이 라벨보다 **엄격히** 오른쪽일 것을 요구한다
    # (`b.x_min > anchor.x_max`). 붙어 있으면 라벨-값 관계로 인식되지 않는다.
    return [
        (label, 0, _LABEL_RIGHT - _LABEL_GUTTER),
        (value, _LABEL_RIGHT, _CANVAS_WIDTH),
    ]


__all__ = [
    "Attachment",
    "EmailContent",
    "parse_email",
    "body_to_result",
    "ATTACHMENT_PRIORITY",
]

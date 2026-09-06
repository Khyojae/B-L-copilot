"""F1 서류 인테이크·초안 작성.

이미지 또는 라벨 JSON → OCR → 필드 추출 → B/L 초안.
"""

from .draft import BLDraft, DraftField, ReviewReason, build_draft
from .extractor import OCRExtractor
from .field_parser import FieldParser
from .pipeline import IntakePipeline
from .types import (
    BL_FIELD_NAMES,
    CONFIRMED_THRESHOLD,
    CRITICAL_FIELD_NAMES,
    LOW_CONFIDENCE_THRESHOLD,
    REVIEW_REQUIRED_THRESHOLD,
    BBox,
    BLFields,
    ConfidenceGrade,
    OCRResult,
    grade_for,
    review_required_fields,
)

__all__ = [
    "BBox",
    "BLDraft",
    "BLFields",
    "BL_FIELD_NAMES",
    "CONFIRMED_THRESHOLD",
    "CRITICAL_FIELD_NAMES",
    "ConfidenceGrade",
    "DraftField",
    "FieldParser",
    "IntakePipeline",
    "LOW_CONFIDENCE_THRESHOLD",
    "OCRExtractor",
    "OCRResult",
    "REVIEW_REQUIRED_THRESHOLD",
    "ReviewReason",
    "build_draft",
    "grade_for",
    "review_required_fields",
]

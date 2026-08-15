"""
F3 하자 예측 공용 타입.

이 파일이 정의하는 `Verdict` 는 F3 의 출력이자 F4(리포트)와 S4(검증 결과
화면)의 입력이다. 세 축이 같은 구조를 보므로 여기가 바뀌면 셋 다 바뀐다.

설계상 못 박아 둔 것 하나: 룰은 **통과 / 위반 / 평가불가** 세 상태를 갖는다.
이항으로 만들면 날짜를 파싱하지 못한 룰이 '통과'로 집계되어, 입력이 나쁠수록
하자가 적어 보이는 역전이 생긴다. 하자 예측 시스템에서 이 역전은 치명적이라
평가불가를 1급 상태로 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Severity(str, Enum):
    """위반 심각도. 기획안 S4 의 심각도별 목록에 그대로 대응한다."""

    CRITICAL = "critical"   # 은행이 거의 확실히 하자로 잡는다
    WARNING = "warning"     # 심사역에 따라 갈린다
    INFO = "info"           # 하자는 아니나 관행 이탈

    @property
    def label(self) -> str:
        return {"critical": "치명", "warning": "경고", "info": "참고"}[self.value]


class Outcome(str, Enum):
    """룰 1건의 평가 결과."""

    PASSED = "passed"
    VIOLATED = "violated"
    NOT_EVALUATED = "not_evaluated"  # 입력 부족·파싱 실패로 판단 불가


@dataclass
class Violation:
    """위반 1건.

    `fields` 는 S4 의 '해당 필드로 바로가기'가 쓴다. 화면이 필드명을 알아야
    편집기로 점프할 수 있으므로 메시지에 녹이지 않고 별도로 남긴다.
    """

    rule_id: str
    severity: Severity
    title: str
    message: str
    fields: List[str] = field(default_factory=list)
    # 근거 조문. S4 의 '항목별 조문 근거 펼침'이 그대로 출력한다.
    source: str = ""
    # 수정 권고. F4 리포트의 '수정 권고(우선순위순)' 항목이 된다.
    remedy: str = ""
    weight: float = 0.0
    # 룰이 실제로 본 값. "왜 걸렸는지"를 사람이 확인할 때 쓴다.
    observed: Dict[str, Optional[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "severity_label": self.severity.label,
            "title": self.title,
            "message": self.message,
            "fields": self.fields,
            "source": self.source,
            "remedy": self.remedy,
            "observed": self.observed,
        }


@dataclass
class SkippedRule:
    """평가하지 못한 룰.

    리포트에 반드시 실어야 한다. 검사하지 못한 항목을 침묵으로 넘기면
    사용자는 '검사했고 문제없다'로 읽는다.
    """

    rule_id: str
    title: str
    reason: str

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "title": self.title, "reason": self.reason}


@dataclass
class Verdict:
    """하자 검증 결과 1건 (서류 세트 하나)."""

    violations: List[Violation] = field(default_factory=list)
    skipped: List[SkippedRule] = field(default_factory=list)
    evaluated_count: int = 0

    # 확률 산출 주체. 지금은 룰 가중치 합산이고, 실전 라벨이 쌓이면
    # XGBoost 로 교체된다(기획안 3.1 ④ 피드백 플라이휠).
    # 화면·리포트가 근거를 정직하게 표기할 수 있도록 문자열로 남긴다.
    model: str = "rules-v1"

    # 판정에 쓴 룰 카탈로그의 신원(`engine.CatalogFingerprint.to_dict()`).
    # 기획안 5.8 '판정 재현성'이 요구하는 값이며, DB 스키마의
    # `verdict.rule_catalog_version` 이 받을 자리이기도 하다.
    #
    # dict 로 두는 이유는 방향 때문이다. 이 모듈은 엔진을 import 하지 않고
    # 엔진이 이 모듈을 import 한다 — `CatalogFingerprint` 를 형으로 받으면
    # 순환이 된다.
    catalog: Optional[dict] = None

    @property
    def defect_probability(self) -> float:
        """하자 확률.

        룰 가중치의 합을 1.0 에서 자른 값이다. 확률이라기보다 위험 점수에
        가까우므로 `model` 을 같이 읽어야 한다 — 화면에서 이걸 학습된
        모델의 확률로 표기하면 발표 자리에서 그대로 지적당한다.
        """
        if not self.violations:
            return 0.0
        return round(min(1.0, sum(v.weight for v in self.violations)), 4)

    def by_severity(self, severity: Severity) -> List[Violation]:
        return [v for v in self.violations if v.severity is severity]

    @property
    def counts(self) -> Dict[str, int]:
        return {s.value: len(self.by_severity(s)) for s in Severity}

    @property
    def has_critical(self) -> bool:
        return bool(self.by_severity(Severity.CRITICAL))

    def sorted_violations(self) -> List[Violation]:
        """심각도 내림차순 → 가중치 내림차순. 리포트 출력 순서."""
        order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
        return sorted(
            self.violations, key=lambda v: (order[v.severity], -v.weight, v.rule_id)
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "catalog": self.catalog,
            "defect_probability": self.defect_probability,
            "evaluated_count": self.evaluated_count,
            "skipped_count": len(self.skipped),
            "counts": self.counts,
            "has_critical": self.has_critical,
            "violations": [v.to_dict() for v in self.sorted_violations()],
            "skipped": [s.to_dict() for s in self.skipped],
        }


# ── L/C 조건 (MT700) ─────────────────────────────────────────────

# MT700 전문 태그 → 내부 필드명. 서류 대조 룰은 이 필드명을 참조한다.
#
# **이 표는 참조용이고 실제 변환은 `mt700._HANDLERS` 가 한다.** 값 정규화
# (YYMMDD→ISO, SWIFT 소수점 콤마, 46A 목록화)가 필요해 표 하나로는 부족하기
# 때문이다. 둘이 어긋나면 태그가 조용히 무시되므로 테스트가 대조한다
# (`test_mt700.py::test_참조표의_모든_태그에_처리기가_있다`).
MT700_TAGS: Dict[str, str] = {
    "31D": "expiry_date",               # Date and Place of Expiry
    "32B": "currency_amount",
    "39A": "tolerance_pct",             # Percentage Credit Amount Tolerance
    "43P": "partial_shipment",          # ALLOWED | PROHIBITED
    "43T": "transhipment",              # ALLOWED | PROHIBITED
    "44C": "latest_shipment_date",
    "44E": "port_of_loading",
    "44F": "port_of_discharge",
    "45A": "description_of_goods",
    "46A": "documents_required",
    "50": "applicant",
    "59": "beneficiary",
}

# UCP 600 Art.14(c). 신용장에 명시가 없을 때의 기본 제시기간.
DEFAULT_PRESENTATION_DAYS = 21

# UCP 600 Art.30(a). 39A 가 없을 때의 기본 허용 오차.
DEFAULT_TOLERANCE_PCT = 10.0


@dataclass
class LCTerms:
    """신용장 조건. B/L 을 여기에 대조하는 것이 F3 의 본체다.

    값이 `None` 인 조건은 **검증하지 않는다**. 신용장에 명시가 없는 항목을
    하자로 잡으면 정상 거래가 반려된다 — 기획안 9절의 '오탐' 리스크가 이것이다.
    """

    lc_no: Optional[str] = None
    currency_amount: Optional[str] = None       # 32B
    expiry_date: Optional[str] = None           # 31D
    latest_shipment_date: Optional[str] = None  # 44C
    port_of_loading: Optional[str] = None       # 44E
    port_of_discharge: Optional[str] = None     # 44F
    description_of_goods: Optional[str] = None  # 45A
    applicant: Optional[str] = None             # 50
    beneficiary: Optional[str] = None           # 59

    # 43P / 43T. 신용장이 침묵하면 UCP 600 상 '허용'이 기본값이다
    # (Art.31(a) 분할선적, Art.20(c) 환적). 금지로 기본값을 잡으면
    # 명시가 없는 정상 건이 전부 하자로 잡힌다.
    partial_shipment: str = "ALLOWED"
    transhipment: str = "ALLOWED"

    # 46A. 요구 서류 목록.
    documents_required: List[str] = field(default_factory=list)

    # 대조 대상은 아니지만 룰이 참조하는 수치 조건.
    consignee: Optional[str] = None
    # 통지처 지정. **비어 있는 것과 지정된 것은 의미가 다르다.**
    # L/C 가 통지처를 지정하면 서류에 그 통지처가 있어야 하지만, 지정이
    # 없으면 통지처 누락은 하자가 아니다(D010 이 이 구분을 쓴다).
    notify_party: Optional[str] = None
    incoterms: Optional[str] = None
    max_gross_weight_kg: Optional[float] = None
    max_measurement_cbm: Optional[float] = None
    freight_amount: Optional[float] = None
    currency: str = "USD"
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT
    presentation_days: int = DEFAULT_PRESENTATION_DAYS

    def get(self, name: str):
        return getattr(self, name, None)

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_tags(cls, tags: Dict[str, str], lc_no: Optional[str] = None) -> "LCTerms":
        """MT700 태그 dict 에서 생성. 모르는 태그는 조용히 버린다.

        정규화는 원문 파서(`mt700.terms_from_tags`)와 **같은 코드를 탄다.**
        태그 값을 필드에 그대로 꽂으면 46A 가 문자열로 들어가 문자 단위로
        순회되고, 44C 의 `260630` 은 날짜 룰이 못 읽는다. 문이 둘이면 한쪽만
        고치게 되므로 뒤를 합쳐 둔다.

        지역 import 는 순환을 피하기 위한 것이다 — `mt700` 이 이 모듈을 쓴다.
        """
        from .mt700 import terms_from_tags

        return terms_from_tags(tags, lc_no=lc_no)

    @classmethod
    def from_dict(cls, data: dict) -> "LCTerms":
        """알 수 없는 키는 무시한다."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


__all__ = [
    "DEFAULT_PRESENTATION_DAYS",
    "DEFAULT_TOLERANCE_PCT",
    "LCTerms",
    "MT700_TAGS",
    "Outcome",
    "Severity",
    "SkippedRule",
    "Verdict",
    "Violation",
]

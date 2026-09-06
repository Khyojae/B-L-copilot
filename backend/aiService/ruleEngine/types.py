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
class HeldRule:
    """판정을 보류한 룰 (기획안 v2 5.3 예외 조항).

    "필수 확인 필드가 남아 있는 상태에서의 검증 실행: 해당 필드 관련 룰은
    '판정 보류'로 표기하고 확률 산출에서 제외하되, 보류 건수를 리포트에
    명시한다."

    **`skipped` 와 합치지 않는다.** 둘 다 '평가하지 않았다'이지만 사용자가
    할 일이 다르다 — 평가불가는 자료가 없어서이므로 **서류나 L/C 를 더
    올려야** 풀리고, 보류는 값을 못 믿어서이므로 **그 필드를 확인해야**
    풀린다. 한 목록에 섞으면 화면이 둘을 같은 안내문으로 그리게 된다.

    `weight` 를 들고 다니는 이유는 리포트가 확률 대신 **범위**를 낼 때
    상한을 계산해야 하기 때문이다(5.4). 보류된 룰이 전부 위반이었을 때가
    상한이고, 그 값은 룰의 가중치를 알아야 나온다.
    """

    rule_id: str
    title: str
    fields: List[str] = field(default_factory=list)
    weight: float = 0.0

    @property
    def reason(self) -> str:
        return (
            f"필수 확인 상태인 필드({', '.join(self.fields)})를 참조하므로 "
            "판정을 보류했습니다."
        )

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "fields": self.fields,
            "reason": self.reason,
        }


@dataclass
class Verdict:
    """하자 검증 결과 1건 (서류 세트 하나)."""

    violations: List[Violation] = field(default_factory=list)
    skipped: List[SkippedRule] = field(default_factory=list)
    # 필수 확인 필드를 참조해 판정을 보류한 룰 (v2 5.3). `skipped` 와 나눠
    # 두는 이유는 `HeldRule` 주석에 있다.
    held: List[HeldRule] = field(default_factory=list)
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

    # 서류 간 정합성 카탈로그(`cross_rules.yaml`)의 신원. 서류 세트로 검증한
    # 경우에만 채워진다.
    #
    # **`catalog` 에 합치지 않고 자리를 따로 둔다.** `cross_doc` 이 신원을
    # 별도로 잡는 이유와 같다 — 하나로 뭉치면 어느 쪽 카탈로그를 고쳐서
    # 판정이 달라졌는지 되짚을 수 없다. 재현성이 요구하는 것은 '무엇으로
    # 판정했나'이고, 그 답은 카탈로그가 둘이면 둘이어야 한다.
    #
    # `None` 은 "서류 간 룰을 돌리지 않았다"는 뜻이다. "돌렸는데 위반이
    # 없었다"와 다르며, 그 구분은 리포트 부록이 쓴다.
    cross_catalog: Optional[dict] = None

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

    @property
    def probability_range(self) -> tuple:
        """보류를 감안한 하자 확률의 범위 (하한, 상한).

        하한은 보류된 룰이 **전부 통과**했을 때이므로 지금 확률 그대로이고,
        상한은 **전부 위반**이었을 때이므로 보류된 가중치를 더한 값이다.
        보류가 없으면 두 값이 같다.

        추정이 아니라 산술이다. 보류된 룰이 어느 쪽으로 떨어질지는 알 수
        없고, 알 수 없다는 사실을 폭으로 보이는 것이 이 값의 목적이다 —
        v2 5.4 가 "확률 대신 범위를 제시한다"고 쓴 자리다.
        """
        low = self.defect_probability
        high = round(min(1.0, low + sum(h.weight for h in self.held)), 4)
        return (low, high)

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

    def merge_cross(self, cross: "Verdict") -> "Verdict":
        """서류별 판정에 서류 간 판정을 얹어 하나로 만든다.

        `RuleEngine` 은 서류 1건을 L/C 에 대조하고 `CrossDocumentEngine` 은
        서류끼리 대조한다. 둘은 입력 형태가 달라 엔진이 나뉘어 있지만,
        사용자에게는 하나의 검증 결과다 — S4 화면도 리포트도 목록 하나를
        그린다. 그 합침을 여기서 한 번만 정의한다.

        비대칭인 것이 맞다. 서류별 판정이 본체이고 서류 간 판정은 얹히는
        쪽이다 — `model` 과 `catalog` 를 왼쪽 것으로 유지하고, 오른쪽의
        신원은 `cross_catalog` 로 옮긴다.

        **평가불가는 위반과 함께 온다.** `skipped` 를 합치지 않으면 "서류가
        없어서 못 본 것"이 사라져 위반 0건이 '하자 없음'으로 읽힌다. 서류를
        B/L 한 장만 올린 사용자에게 특히 그렇다.
        """
        return Verdict(
            violations=self.violations + cross.violations,
            skipped=self.skipped + cross.skipped,
            held=self.held + cross.held,
            evaluated_count=self.evaluated_count + cross.evaluated_count,
            model=self.model,
            catalog=self.catalog,
            cross_catalog=cross.catalog,
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "catalog": self.catalog,
            "cross_catalog": self.cross_catalog,
            "defect_probability": self.defect_probability,
            # 보류가 있으면 화면은 이 범위를 써야 한다. 점 확률만 그리면
            # 보류된 룰이 전부 통과한 것처럼 읽힌다.
            "probability_range": list(self.probability_range),
            "evaluated_count": self.evaluated_count,
            "skipped_count": len(self.skipped),
            "held_count": len(self.held),
            "counts": self.counts,
            "has_critical": self.has_critical,
            "violations": [v.to_dict() for v in self.sorted_violations()],
            "skipped": [s.to_dict() for s in self.skipped],
            "held": [h.to_dict() for h in self.held],
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

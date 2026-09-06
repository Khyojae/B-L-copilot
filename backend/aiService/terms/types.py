"""
F2 표준 용어 교정 공용 타입.

`ruleEngine/types.py` 가 F3 의 계약(`Verdict`·`Violation`)이듯 이 파일은
F2 의 계약이다. 같은 규약을 따른다 — `@dataclass` + 손으로 쓴 `to_dict()` +
정렬된 `__all__`. **Pydantic 을 쓰지 않는다.** 이 프로젝트는 Pydantic 을
`api/main.py` 경계(HTTP 스키마)에만 두고 안쪽 도메인 타입은 전부 순수
dataclass 다 — `terms` 가 HTTP 를 모르는 F6 에서도 `import` 만으로 재사용
되기 때문이다(`HANDOFF.md` §6.3).

`Suggestion`/`Notice`/`Unevaluated` 가 나뉘어 있는 이유는 §1 원칙("제안하지
않는 것이 틀리게 제안하는 것보다 낫다")이다 — 확신을 갖고 값을 바꾸자는
제안, 판단은 서지만 값을 단정하지 않는 안내, 판단 자체를 유보한 기록을 한
타입에 욱여넣으면 "적용해도 되는 값"인지를 호출부가 매번 조건문으로 가려
내야 하고, 그 조건문 하나가 빠지는 순간 유보된 값이 제안처럼 취급된다.

`Correction.decided_at` 은 서버가 `datetime.now()` 를 불러 채우지 않고
요청이 싣는다. `ruleEngine/checks.py` 가 `rule.get("_as_of") or
datetime.now()` 로 호출부가 기준 시각을 주입하게 한 것과 같은 이유다 —
F2 의 accept/reject 는 "무상태 유지, 순수 함수"라는 확정 결정(`HANDOFF.md`
§2)을 진다. 함수 내부에서 시스템 시계를 읽으면 그 순간 순수성이 깨져
같은 거절을 두 번 재현해도(게이트웨이 재시도, 감사 로그 재생) 시각이
달라진다. 그래서 시각은 호출부(게이트웨이)가 정해 보내고, 이 서비스는
그대로 기록만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _dump(value: Any) -> Any:
    """필드 값 하나를 응답 payload 에 쓸 형태로 바꾼다.

    `to_dict()` 는 손으로 쓰지만, 값 변환 규칙(중첩 dataclass 재귀·datetime
    직렬화·tuple→list)까지 클래스마다 따로 쓰면 새 필드가 늘 때마다 어느
    한 곳이 규칙을 빠뜨린다. 그 규칙만 여기 모은다.

    `None` 은 버리지 않고 그대로 둔다 — 게이트웨이가 키 존재를 기대한다.
    키 자체가 사라지면 "값이 없다"와 "이 서버가 이 필드를 모른다"가
    구분되지 않는다.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_dump(v) for v in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class FieldRef:
    """서류 안의 필드(또는 필드 값 안의 조각) 하나를 가리킨다.

    `frozen=True` 인 이유: `Suggestion.field`·`Suggestion.impact` 양쪽에
    같은 참조가 나타날 수 있는데, 가변 객체면 한쪽을 고쳤을 때 다른 쪽도
    조용히 바뀐다.

    `span` 은 **필드 전체가 아니라 값 문자열 안의 조각**을 가리킬 때 쓴다
    (문자 오프셋 `(start, end)`, 반열림 구간). 관행 문구·컨테이너 번호·
    HS 코드·상호 접미(`party_suffix`)는 자유서식 값의 일부이지 필드 전체가
    아니라서, span 없이는 `apply` 가 값의 어느 부분을 바꿀지 알 수 없다.
    예: `"GAE WOON CO.,LTD"` 에서 접미만 고치려면 span=(9,16) 이 있어야
    `"GAE WOON"` 을 바이트 단위로 보존하며 접미만 치환할 수 있다
    (`HANDOFF.md` §4.8).
    """

    doc: str
    field: str
    doc_id: Optional[str] = None
    span: Optional[Tuple[int, int]] = None

    def to_dict(self) -> dict:
        return {
            "doc": self.doc,
            "field": self.field,
            "doc_id": self.doc_id,
            "span": _dump(self.span),
        }


@dataclass
class Evidence:
    """제안 하나의 근거.

    `stage` 가 핵심이다 — §1의 세 번째 원칙("어느 경로로 나온 값인지가 값을
    따라다닌다")을 담는 필드이며, `report/narrative.py:Summary.source`·
    `ocr/draft.py:DraftField.source` 와 같은 자리다. `policy.STAGE_*`
    (`format`·`exact`·`alias`·`pattern`·`similarity`·`llm`) 중 캐스케이드가
    실제로 최종 확정에 쓴 값을 담는다. ⑤ LLM 호출이 실패하면 `stage` 는
    `"llm"` 이 **아니라** `"similarity"` 로 남는다 — 클래스 이름이 아니라
    실제 확정 경로를 적는다는 원칙이 실패 시에도 적용된다(`HANDOFF.md`
    §4.4, `LLMNarrator` 가 실패 시 `source="template"` 를 남기는 것과 같다).
    """

    authority: str
    term_id: Optional[str]
    glossary_version: str
    tier: str  # "standard" | "organization" | "shipment" — 어느 계층이 답했는지
    stage: str  # policy.STAGE_*
    verified: bool = False
    # 하위 계층(조직/선적)이 표준과 다른 canonical 로 덮어썼을 때 표준 쪽
    # 값을 여기 남긴다. None 이면 표준과 같거나 표준 계층에서 나온 값이다.
    diverges_from_standard: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "authority": self.authority,
            "term_id": self.term_id,
            "glossary_version": self.glossary_version,
            "tier": self.tier,
            "stage": self.stage,
            "verified": self.verified,
            "diverges_from_standard": self.diverges_from_standard,
        }


@dataclass
class Candidate:
    """④유사도·⑤LLM 단계에서 만든 후보 하나.

    `requires_choice=True` 인 `Suggestion.candidates` 가 이 타입의 리스트를
    담는다 — 사람이 고를 선택지 목록이다.
    """

    to_be: str
    term_id: Optional[str]
    authority: str
    score: float
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "to_be": self.to_be,
            "term_id": self.term_id,
            "authority": self.authority,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class Suggestion:
    """제안 카드 하나. 기획안 §5.2 에 1:1 대응한다(`HANDOFF.md` §4.5).

    **`requires_choice=True` 일 때 `to_be` 는 반드시 `None` 이어야 한다.**
    이 제약을 `__post_init__` 등으로 강제하지 않는 이유: 이 타입은 캐스케이드
    (T9)가 만들고 apply(T11)가 읽기만 하는 값 객체다. 강제 검증을 여기 두면
    판단 로직이 타입 정의와 T9 양쪽에서 이중 관리된다 — 값 객체는 형태만
    정의하고, 형태를 지키는 책임은 만드는 쪽(T9 테스트)이 진다. 값을 비우는
    이유 자체는 UI 가 채워진 `to_be` 를 기본값으로 오인해 "임의 선택 금지"
    요건이 조용히 깨지는 것을 막기 위해서다.

    `impact` 는 `suggestion_id` 해시에 넣지 않는다(`HANDOFF.md` §4.7) —
    요청에 실린 서류 수에 따라 달라지는 값이라, 넣으면 같은 판정도 서류
    묶음이 다르면 다른 id 가 된다.
    """

    suggestion_id: str
    field: FieldRef
    as_is: str
    to_be: Optional[str]
    term_class: str
    evidence: Evidence
    confidence: float
    impact: List[FieldRef] = field(default_factory=list)
    candidates: List[Candidate] = field(default_factory=list)
    requires_choice: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "suggestion_id": self.suggestion_id,
            "field": self.field.to_dict(),
            "as_is": self.as_is,
            "to_be": self.to_be,
            "term_class": self.term_class,
            "evidence": self.evidence.to_dict(),
            "confidence": self.confidence,
            "impact": [f.to_dict() for f in self.impact],
            "candidates": [c.to_dict() for c in self.candidates],
            "requires_choice": self.requires_choice,
            "message": self.message,
        }


@dataclass
class Notice:
    """제안이 아니라 안내. `kind` 는 네 가지다(`HANDOFF.md` §4.2·§4.4·§4.8).

    - `"lc_wording"` — 필드가 L/C 문언에 고정되어 사전 기반 교정을 건너
      뛰었다는 안내다(교정 제안이 아니다). 값이 L/C 와 어긋나는지는 F3 의
      `match_place` 가 이미 판정하므로, F2 가 같은 자리에 다른 판단을 내면
      화면에 모순되는 카드 두 장이 뜬다.
    - `"injection"` — 값 안 프롬프트 주입 패턴 경보. **처리를 멈추지
      않는다** — 정상 화물 명세에 우연히 걸릴 수 있고, 멈추면 주입 시도가
      곧 서비스 거부가 된다.
    - `"deterministic_error"` — 결정론 검증기(ISO 6346 체크디지트 등)가
      형식 오류를 잡았지만 교정 제안으로 확정할 근거는 부족한 경우.
    - `"not_covered"` — 사전/카탈로그가 값을 모른다. `qty_unit`·
      `volume_unit` 처럼 닫힌 코드 집합에서 미등록 값을 만났을 때, "비슷한
      단위"로 추측하지 않고 모른다고 말하는 것 자체가 §1 원칙의 실행이다.
    """

    kind: str  # lc_wording | injection | deterministic_error | not_covered
    severity: str  # ruleEngine.Severity 값과 같은 어휘: critical|warning|info
    field: FieldRef
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "field": self.field.to_dict(),
            "message": self.message,
        }


@dataclass
class Unevaluated:
    """판단을 유보한 값 1건.

    `ruleEngine.Outcome.NOT_EVALUATED` 를 1급 상태로 두는 것과 같은 이유로
    별도 타입을 둔다 — 판단 못 한 것을 조용히 넘기면 입력이 나쁠수록 제안이
    적어 보이는 역전이 생긴다. `score` 는 있으면 남긴다 — 예를 들어 ④유사도
    최고 점수가 `policy.SIMILARITY_FLOOR` 미만이라 후보를 못 만든 경우, 그
    점수를 같이 남겨야 "왜 유보됐는지"를 재구성할 수 있다. 판단 자체가
    없었던 경우(L/C 고정 필드 등)는 `None` 이다.
    """

    field: FieldRef
    reason: str
    score: Optional[float] = None
    as_is: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "field": self.field.to_dict(),
            "reason": self.reason,
            "score": self.score,
            "as_is": self.as_is,
        }


@dataclass
class Versions:
    """이 판정에 실제로 쓰인 버전 3종 + 랭커.

    `HANDOFF.md` §4.2 "판정 재현성" 이 요구하는 값이다 — 응답에 실으면
    게이트웨이가 저장했다가 재현 요청 시 되돌려보내 "그때와 같은 카탈로그·
    같은 캐스케이드 로직으로 다시 계산했다"를 증명할 수 있다.
    `ruleEngine.Verdict.catalog` 와 같은 역할이며, F2 는 카탈로그가
    셋(용어사전·캐스케이드·룰카탈로그)이라 각각을 남긴다.
    """

    glossary_version: str = ""
    cascade_version: str = ""
    # F3 룰 카탈로그 버전. L/C 문언 우선 판정이 ruleEngine.match_place 와
    # 어긋나지 않았음을 사후 대조하려고 함께 싣는다. F3 를 안 탄 요청은 None.
    rules_catalog_version: Optional[str] = None
    # ⑤단계에서 실제로 호출한 모델명. 안 탔으면 None(stats.llm_path=="not_called").
    llm_model: Optional[str] = None
    # similarity.Ranker 구현 이름. 임베딩 구현이 들어와도 이 필드로 "어느
    # 랭커가 돌았는지"가 응답에 남는다(`HANDOFF.md` §4.3).
    ranker: str = ""

    def to_dict(self) -> dict:
        return {
            "glossary_version": self.glossary_version,
            "cascade_version": self.cascade_version,
            "rules_catalog_version": self.rules_catalog_version,
            "llm_model": self.llm_model,
            "ranker": self.ranker,
        }


@dataclass
class Stats:
    """이번 판정 1회의 실행 통계. `evaluate.py`·`acceptance.py` 가 읽는다."""

    # 단계 문자열(policy.STAGE_*) → 그 단계에서 확정된 제안 수.
    by_stage: Dict[str, int] = field(default_factory=dict)
    # "not_called" | "called" | "failed". evidence.stage 만으로는 LLM 을
    # 아예 안 태운 것과 태웠는데 실패한 것을 구분 못 해(둘 다 최종 stage 가
    # "similarity") 별도로 남긴다.
    llm_path: str = "not_called"
    llm_calls: int = 0
    elapsed_ms: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "by_stage": dict(self.by_stage),
            "llm_path": self.llm_path,
            "llm_calls": self.llm_calls,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class NormalizeResult:
    """`POST /normalize` 응답 본체."""

    suggestions: List[Suggestion] = field(default_factory=list)
    notices: List[Notice] = field(default_factory=list)
    unevaluated: List[Unevaluated] = field(default_factory=list)
    versions: Versions = field(default_factory=Versions)
    stats: Stats = field(default_factory=Stats)

    def to_dict(self) -> dict:
        return {
            "suggestions": [s.to_dict() for s in self.suggestions],
            "notices": [n.to_dict() for n in self.notices],
            "unevaluated": [u.to_dict() for u in self.unevaluated],
            "versions": self.versions.to_dict(),
            "stats": self.stats.to_dict(),
        }


# `from_dict` 가 없으면 400 을 던져야 하는 필수 키.
# `from_dict` 가 없으면 거부하는 키.
#
# `lang`·`authority`·`version`·`effective_date` 는 카탈로그 스키마상 필수지만
# 여기서는 강제하지 않는다. 로더(`glossary.py`)가 원시 dict 단계에서
# **문제를 전부 모아 한 번에** 던지는 검증을 하고 있고, 여기서 먼저 예외를
# 내면 첫 항목에서 끊겨 그 규약이 깨진다. 이 셋만 막는 이유는 없으면
# 색인 단계에서 원인 불명의 KeyError 로 터지기 때문이다.
_GLOSSARY_TERM_REQUIRED = ("term_id", "category", "canonical")


@dataclass
class GlossaryTerm:
    """용어사전 항목 1건. `HANDOFF.md` §4.6 스키마 + 추가 5필드.

    기본 스키마(`rules.yaml` 규약 승계): `term_id`(고유 식별자)·
    `category`(`policy.CLASSES` 키)·`canonical`(비교용 표준 표기,
    `normalize_key` 로 색인)·`aliases`·`deprecated_by`(폐기 시 대체
    `term_id`).

    추가 5필드:

    - `display` — 사람이 읽을 표기. 없으면 `canonical` 을 그대로 쓴다.
      `canonical` 은 비교 키를 만들 원문(대개 대문자)이고, `display` 는
      그걸로 못 만드는 표기(Title Case 항구명, Incoterms 장소 병기 등)다.
    - `country` — ISO2. 항구 클래스 동음이의 판별에 쓴다. 동음이의
      항구쌍은 양쪽 다 이 값이 있어야 한다는 게 로더(T4)의 검증 규칙이다 —
      이 타입 자체는 강제하지 않는다(§검증 판단 참고).
    - `verified` — 표준 표기·별칭을 실무자가 실제로 확인했는지.
      `rules.yaml` 의 `verified` 규약을 승계한다. 기본 미검증인 이유도
      같다 — 일부만 켜 두면 나머지가 검증된 것으로 오독된다.
    - `tier` — 3계층(`GlossaryStack`) 중 어디서 왔는지:
      `"standard"`/`"organization"`/`"shipment"`. 조회 시 `GlossaryStack`
      이 채운다 — 표준 카탈로그 YAML 자체는 보통 명시하지 않는다.
    - `note` — 자유서식 부연. 화면에 노출하지 않는 내부 감사용이다.
    - `bl_form` — `category == "port"` 한정: 선하증권(B/L) 면에 실제로
      인쇄되는 표기(대문자 영문 항구명, 예: `"BUSAN"`). `canonical`
      (UN/LOCODE 코드, 예: `"KRPUS"`)은 EDIFACT·세관 매니페스트·DCSA eBL
      데이터 레이어에서만 쓰이고 선박회사가 발행하는 B/L 면에는 절대
      인쇄되지 않는다(UCP 600 제20조 — 서류는 L/C 문언과 일치해야 한다).
      비어 있으면(`None`) 캐스케이드는 이 항구를 조용히 코드로 제안하지
      않고 `Unevaluated` 로 남긴다(`cascade.py:_applied_form` 참고).

    ## 검증 판단

    `country` 필수 여부는 이 dataclass 가 아니라 로더가 카탈로그 전수
    검증에서 확인한다(`HANDOFF.md` §4.6: "문제를 전부 모아 한 번에
    던진다"). 여기서 조건부 필수를 강제하면 실패 메시지가 첫 항목에서
    예외로 끊겨 "전부 모아 한 번에"가 깨진다.
    """

    term_id: str
    category: str
    canonical: str
    # ── 기획안 §5.2 사전 스키마의 나머지 필수 4필드 ──
    #
    # 처음 이 dataclass 를 만들 때 빠져 있었다. YAML 로더는 이 넷을 필수 키로
    # 검사하는데 `from_dict` 가 모르는 키를 버리므로, 적재 후 값이 조용히
    # 사라지고 있었다 — 카탈로그에는 있는데 런타임에는 없는 상태다.
    #
    # `authority` 가 특히 중요하다. 제안 카드의 근거(`Evidence.authority`)가
    # **항목마다** 다르기 때문이다: 같은 `qty_unit` 이라도 `KGM` 은
    # UN/ECE Rec 20 이고 포장 단위는 업계 관행이며, 조직 사전 오버라이드는
    # `조직 사전` 이다. 클래스 기본값으로 대신하면 오버라이드가 표준과 같은
    # 출처를 인용하게 되고, 그건 리포트가 출처를 지어내는 것과 같다.
    #
    # `version`·`effective_date` 는 판정 재현성 요건이 요구한다. 카탈로그
    # 전체 버전과 별개로, 항목이 언제 판의 것인지가 `deprecated_by` 계보를
    # 따라갈 때 필요하다.
    lang: str = "en"                    # ko | en | code
    authority: str = ""                 # UN/LOCODE · ISBP 745 · 조직 사전 …
    version: str = ""                   # 이 항목이 들어온 카탈로그 버전
    effective_date: str = ""            # YYYY-MM-DD
    aliases: List[str] = field(default_factory=list)
    deprecated_by: Optional[str] = None
    display: Optional[str] = None
    country: Optional[str] = None
    verified: bool = False
    tier: str = "standard"
    note: str = ""
    bl_form: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "term_id": self.term_id,
            "category": self.category,
            "canonical": self.canonical,
            "lang": self.lang,
            "authority": self.authority,
            "version": self.version,
            "effective_date": self.effective_date,
            "aliases": list(self.aliases),
            "deprecated_by": self.deprecated_by,
            "display": self.display,
            "country": self.country,
            "verified": self.verified,
            "tier": self.tier,
            "note": self.note,
            "bl_form": self.bl_form,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlossaryTerm":
        """카탈로그 YAML 항목 1건 또는 요청 `overrides` 항목 1건을 만든다.

        모르는 키는 조용히 무시한다 — 편집자가 주석 대신 쓰는 여분의 키
        (예: `source_url`)까지 스키마 오류로 막으면 사전 유지보수가
        불필요하게 빡빡해진다. 반대로 필수 키 누락은 `ValueError` 다 —
        조용히 받아 주면 색인 단계에서 원인 불명의 `KeyError` 로 터진다.
        """
        missing = [k for k in _GLOSSARY_TERM_REQUIRED if not data.get(k)]
        if missing:
            raise ValueError(f"GlossaryTerm 필수 키 누락: {', '.join(missing)}")
        known = set(cls.__dataclass_fields__)
        kept = {k: v for k, v in data.items() if k in known}

        # PyYAML 은 따옴표 없는 `2026-01-01` 을 `datetime.date` 로 파싱한다.
        # 그대로 두면 `to_dict()` 가 JSON 직렬화 불가 객체를 내보내 응답에서
        # 터지고, `suggestion_id` 해시 재료로도 못 쓴다. 카탈로그 편집자가
        # 따옴표를 붙이는지에 판정 재현성이 걸리게 둘 수는 없으므로 여기서
        # 문자열로 고정한다.
        for key in ("effective_date", "version"):
            value = kept.get(key)
            if value is not None and not isinstance(value, str):
                kept[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)

        return cls(**kept)


@dataclass
class Correction:
    """`/normalize/reject` 가 만들어 내는 거절 기록.

    영속성은 게이트웨이의 몫이다(`HANDOFF.md` §2 "무상태 유지"). 이 서비스는
    저장하지 않고 반환만 한다. `decided_at` 을 요청이 싣는 이유는 모듈
    docstring 을 보라.
    """

    suggestion_id: str
    field: FieldRef
    as_is: str
    to_be: Optional[str]
    term_class: str
    decision: str  # "accepted" | "rejected"
    decided_at: datetime
    # ── 기획안 §5.8 공통 도메인 객체의 나머지 2필드 ──
    #
    # 기획안은 `correction` 을 "변경 필드, 이전 값, 새 값, **영향 항목**,
    # **승인자**, 시각"으로 정의하고 **F2·F5 가 공유**한다고 못박았다.
    # 처음 만들 때 둘이 빠져 있었다.
    #
    # `decided_by` 를 무상태라는 이유로 버리면 안 된다. 게이트웨이가 승인자를
    # 저장하려면 **우리가 돌려줘야** 하고, 요청으로 받은 값을 버리면 게이트웨이가
    # 스스로 다시 붙여야 해서 Correction 을 돌려주는 의미 자체가 없어진다.
    # 무상태는 "저장하지 않는다"이지 "받은 사실을 잃어버린다"가 아니다.
    #
    # `impact` 는 F5(정정 영향분석)의 입력이다. 어느 자리가 함께 바뀌었는지가
    # 없으면 F5 는 정합성 그래프를 역산할 시작점을 잃는다. **실제로 함께 바뀐
    # 자리만** 담는다 — 제안 시점의 후보 목록이 아니라 적용 결과다.
    decided_by: str = ""
    impact: List[FieldRef] = field(default_factory=list)
    # 거절 사유. enum 검증은 api/main.py 경계(Pydantic, 422)의 몫이다 —
    # 이 타입은 도메인 객체라 HTTP 스키마 오류 코드를 모른다.
    reason: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "suggestion_id": self.suggestion_id,
            "field": self.field.to_dict(),
            "as_is": self.as_is,
            "to_be": self.to_be,
            "term_class": self.term_class,
            "decision": self.decision,
            "decided_by": self.decided_by,
            "decided_at": _dump(self.decided_at),
            "impact": [ref.to_dict() for ref in self.impact],
            "reason": self.reason,
            "note": self.note,
        }


__all__ = [
    "Candidate",
    "Correction",
    "Evidence",
    "FieldRef",
    "GlossaryTerm",
    "Notice",
    "NormalizeResult",
    "Stats",
    "Suggestion",
    "Unevaluated",
    "Versions",
]

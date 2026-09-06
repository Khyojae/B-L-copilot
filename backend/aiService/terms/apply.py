"""
F2 제안 적용 — `suggestion_id` 파생 · 변조 대조 · accept/reject · span 치환.

`docs/f2/HANDOFF.md` §4.5(span 계약)·§4.7(`suggestion_id`),
`docs/ai-service/f2-standard-terms.md` §제안 ID 절의 구현이다.

## 이 파일이 지는 책임

`cascade.py`(T9)는 **값을 고치지 않는다** — 무엇을 어떻게 고칠지 `Suggestion`
으로 제안할 뿐이다. 실제 치환은 사람이 S3 에서 승인한 뒤 이 파일이 한다. 두
경로가 갈라져 있는 것 자체가 승인 게이트이므로, 여기서 캐스케이드 로직을
다시 판단하지 않는다 — 이미 만들어진 `Suggestion.as_is`/`to_be`/`field.span`
을 **그대로** 적용하거나, 적용할 수 없는 사정이 있으면 이유를 남기고
건너뛴다.

## span 계약 — 절대 어기지 않는다 (HANDOFF §4.5)

`span` 이 있으면 `as_is` 는 그 자리의 부분 문자열이고 `to_be` 는 그 자리만
대신한다 — `value[:start] + to_be + value[end:]`. `span` 이 `None` 이면
`as_is` 는 필드 값 전체이고 `to_be` 가 전체를 대신한다. 이 계약이 한 번
깨져 단위 값이 복제된 채 승인 화면까지 간 사고가 있었다(HANDOFF §4.5) — 그래서
`_apply_group` 은 치환 직전에 **항상** `value[start:end] == as_is`(또는
`value == as_is`, span 없을 때)를 확인하고, 어긋나면 절대 치환하지 않고
`unapplied` 로 돌린다.

## `_suggestion_id` 이관 판단

`cascade.py` 끝의 `_suggestion_id()` 는 이미 "정본은 T11(`apply.py`)에 있고,
자신은 지연 임포트로 빌려 쓴다"는 전제로 짜여 있다(`from .apply import
suggestion_id as derive` 를 함수 **몸통 안에서** 호출 — 모듈 최상단이
아니다). 즉 순환 임포트 문제는 이미 cascade 쪽에서 "느슨한 방향"으로
해소돼 있다: `apply.py` 가 `cascade.py` 를 모듈 최상단에서 import 해도(이
파일이 `DocumentInput`/`CASCADE_VERSION` 을 그쪽에서 가져오므로 어차피
가져온다), `cascade.py` 는 `apply.py` 를 모듈 최상단에서 되돌아 import 하지
않으므로 순환이 생기지 않는다. 그래서 이 파일이 **정본**을 갖고, `cascade.py`
는 고치지 않는다(이관 작업 자체가 이미 끝나 있었다) — 파생식은 여기 한 벌만
있고 `cascade.py` 는 실패해도(`apply.py` 가 아직 없던 시절에도) `/normalize`
가 죽지 않도록 빈 문자열로 폴백한다.

## 의존성

`hashlib`·`json`·`copy`·`dataclasses`·`datetime`·`typing` 뿐이다. 새 의존성을
추가하지 않는다(`HANDOFF.md` §3).
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .cascade import DocumentInput
from .keys import normalize_key
from .policy import CASCADE_VERSION
from .types import Correction, FieldRef, Suggestion

# `share.py` 의 `VERSION = "v1"` 과 같은 이유의 접두다 — 파생식(재료 구성·해시
# 함수)이 바뀌면 이 접두를 올려 옛 id 와 새 id 를 한눈에 구분한다.
SUGGESTION_ID_PREFIX = "sg1"

# ── unapplied 사유 — 자유 문자열이 아니라 상수로 고정한다 ──────────────
#
# 호출부(게이트웨이·테스트)가 문자열을 비교해 분기할 수 있어야 하므로, 같은
# 상황은 항상 같은 문자열을 낸다. 값 자체는 태스크 계약서에 박힌 문구를
# 그대로 쓴다.
_REASON_TAMPERED = "제안이 변조되었거나 사전 버전이 다릅니다"
_REASON_REQUIRES_CHOICE = "사용자 선택이 필요한 제안입니다"
_REASON_STALE = "제안의 as_is 값이 더 이상 문서 값과 일치하지 않습니다"
_REASON_OVERLAP = "다른 제안과 자리가 겹칩니다"
_REASON_WHOLE_VS_SPAN = "같은 필드에 전체 치환 제안이 있어 부분 치환을 적용할 수 없습니다"
# 서류·필드를 못 찾은 사유는 상수로 두지 않는다 — 무엇을 찾다 실패했는지
# (어느 doc_id 를 찾았고 요청에 무엇이 실려 있었는지)를 함께 담아야
# 연동하는 쪽이 고칠 수 있기 때문이다. `apply_suggestions` 안에서 만든다.


# ════════════════════════════════════════════════════════════════
# suggestion_id — 저장 없는 결정론적 파생
# ════════════════════════════════════════════════════════════════


def suggestion_id(s: Suggestion) -> str:
    """제안 카드 하나를 결정론적으로 식별하는 id 를 만든다.

    **HMAC 이 아니라 순수 해시다.** `f4_report/share.py` 의 서명키는
    `secret_is_ephemeral` 규약대로 프로세스마다 달라질 수 있어 재현성이
    깨진다. 이 함수의 목적은 위조 방지가 아니라 **같은 입력에 같은 이름**
    이므로 표준 라이브러리 `hashlib` 만 쓴다(위조 자체는 `verify_suggestion_id`
    가 재파생 대조로 잡는다 — "같은 이름" 원칙이 있으면 변조는 자동으로
    드러난다).

    재료(payload)에 무엇이 들어가고 무엇이 안 들어가는지가 핵심이다:

    - `evidence.glossary_version`·`CASCADE_VERSION` 이 들어간다. 사전을
      올리거나 캐스케이드 로직이 바뀌면 같은 입력도 다른 id 를 받는다 —
      옛 결정(승인/거절 이력)이 새 제안에 조용히 재사용되면 안 되므로,
      바뀌었을 때 **시끄럽게** 깨지는 쪽을 택한다.
    - `field.span` 이 들어간다. 같은 필드 안에서도 어느 조각을 가리키는지가
      다르면 다른 제안이다.
    - `as_is` 는 `normalize_key` 를 거친다 — 표기가 살짝 달라도(공백·대소문자)
      "같은 오류"를 가리키면 같은 id 를 받아야 재현 요청이 옛 결정을 찾는다.
    - `impact` 는 **넣지 않는다.** 요청에 실린 서류 수에 따라 달라지는
      값이라, 넣으면 같은 판정이 서류 묶음 크기에 따라 다른 id 를 갖게 되고,
      그러면 게이트웨이가 "같은 제안"인지 대조할 수 없다.
    """
    payload = json.dumps(
        [
            s.evidence.glossary_version,
            CASCADE_VERSION,
            s.field.doc,
            s.field.doc_id or "",
            s.field.field,
            list(s.field.span or ()),
            normalize_key(s.as_is),
            s.to_be or "",
            s.evidence.term_id or "",
            s.evidence.stage,
            s.term_class,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.blake2s(payload.encode("utf-8"), digest_size=12).hexdigest()
    return f"{SUGGESTION_ID_PREFIX}_{digest}"


def verify_suggestion_id(s: Suggestion) -> bool:
    """받은 제안의 `suggestion_id` 를 재료에서 재파생해 대조한다.

    저장소가 없으므로(무상태) "이 id 가 진짜 우리가 낸 제안인가"를 확인할
    유일한 방법은 재파생뿐이다. 어긋나는 경우는 둘 중 하나다 — 본문이
    변조됐거나, 요청과 응답 사이에 사전 버전이 바뀌었다(`HANDOFF.md`
    §4.7). 어느 쪽이든 이 함수 입장에서는 "믿을 수 없다"로 같다 —
    원인을 구분하는 것은 이 함수의 책임이 아니다.
    """
    return s.suggestion_id == suggestion_id(s)


# ════════════════════════════════════════════════════════════════
# 결과 타입
# ════════════════════════════════════════════════════════════════


@dataclass
class ApplyOutcome:
    """`apply_suggestions` 1회 호출의 결과.

    `documents` 는 **입력을 변형하지 않은** 깊은 복사본이다 — 게이트웨이가
    적용 후 어느 값이 바뀌었는지 원본과 대조하거나, 이후 단계가 실패했을 때
    원본으로 되돌릴 수 있어야 한다(`HANDOFF.md` §2 "무상태 유지, 순수 함수").
    """

    documents: List[DocumentInput]
    corrections: List[Correction]
    unapplied: List[dict]


class _Target:
    """그룹 처리 중에만 쓰는 내부 값 — 제안 하나가 건드리려는 자리 하나.

    `Suggestion` 자체는 공개 계약(`types.py`)이라 여기서 새 필드를 얹지
    않는다. 대신 "이 제안이 이 자리를 적용했는가"를 추적할 가변 상태가
    필요해서 얇은 내부 헬퍼를 둔다. `__slots__` 는 그룹 처리가 제안 수 ×
    (1 + impact 수) 만큼 인스턴스를 만들 수 있어 습관적으로 붙였다 — 이
    파일의 다른 어떤 판단에도 영향 없는 사소한 최적화다.
    """

    __slots__ = ("suggestion", "ref", "primary", "applied", "reason")

    def __init__(self, suggestion: Suggestion, ref: FieldRef, primary: bool) -> None:
        self.suggestion = suggestion
        self.ref = ref
        self.primary = primary  # True 면 suggestion.field 자체, False 면 impact 자리
        self.applied = False
        self.reason: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# 순수 헬퍼
# ════════════════════════════════════════════════════════════════


def _find_document(
    documents: List[DocumentInput], doc: str, doc_id: Optional[str]
) -> Optional[DocumentInput]:
    """`FieldRef.doc`/`doc_id` 로 서류를 찾는다.

    같은 종류의 서류가 한 요청에 둘 이상 실릴 수 있으므로(선하증권 2장)
    `doc` 만으로는 못 좁힌다 — `doc_id` 까지 같이 봐야 한다(`cascade.py`
    `DocumentInput` docstring과 같은 논거).
    """
    for d in documents:
        if d.doc == doc and d.doc_id == doc_id:
            return d
    return None


def _overlaps(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _apply_group(doc: DocumentInput, field_name: str, group: List[_Target]) -> None:
    """같은 (서류, 필드) 한 자리에 걸린 적용 대상들을 처리한다.

    한 자유서식 필드에 span 제안이 둘 이상 걸릴 수 있다(`MSKU 123456 5` 와
    `freight prepaid` 가 같은 `description_of_goods` 안에 있는 경우).
    앞에서부터 치환하면 `to_be` 길이가 `as_is` 와 달라 **뒤 제안의 span 이
    어긋난다.** 그래서 span 대상들을 **start 내림차순으로 정렬해 뒤에서부터**
    치환한다 — 이러면 아직 처리하지 않은(더 앞쪽) span 의 오프셋은 뒤쪽
    치환의 길이 변화에 영향받지 않는다(뒤쪽 치환은 자기 `end` 이후만
    바꾸므로 그보다 앞선 좌표는 그대로 유효하다).

    두 가지 충돌은 적용하지 않고 이유를 남긴다:

    - **span 겹침** — 두 제안의 span 이 겹치면 동시에 승인했을 때 어느
      쪽이든 다른 쪽의 치환을 덮어쓴다. 그룹에 들어온 순서(= 원본
      `suggestions` 리스트 순서, primary 가 그 제안의 impact 보다 먼저)
      기준으로 먼저 온 것을 남기고 **뒤엣것**을 `unapplied` 로 돌린다.
    - **span=None 과 span 이 같은 필드에 공존** — 전체 치환이 확정되면
      그 안의 부분 span 은 의미를 잃는다(치환 후 좌표 자체가 무효가 될 수
      있다). span 이 있는 대상은 전부 포기하고, span=None 대상만 처리한다.
    """
    span_none = [t for t in group if t.ref.span is None]
    span_some = [t for t in group if t.ref.span is not None]

    if span_none and span_some:
        for t in span_some:
            t.reason = _REASON_WHOLE_VS_SPAN
        span_some = []

    value = doc.fields[field_name]
    assert value is not None  # 호출부가 None 필드를 이미 걸러낸다.

    if span_none:
        # 전체 치환 대상이 둘 이상이면 서로 "전체를 덮는 겹침"이다 — 그룹
        # 진입 순서상 첫 번째만 남긴다.
        accepted = False
        for t in span_none:
            if accepted:
                t.reason = _REASON_OVERLAP
                continue
            if value != t.suggestion.as_is:
                t.reason = _REASON_STALE
                continue
            value = t.suggestion.to_be or ""
            t.applied = True
            accepted = True
        doc.fields[field_name] = value
        return

    # ── 1단계: 겹침 해소는 **리스트 순서**로 한다 ──────────────────────
    #
    # 겹침의 승자를 정하는 것과 치환 순서는 서로 다른 관심사다. 한 루프에서
    # 같이 처리하면 "start 가 뒤인 쪽"이 이겨서, 사용자가 먼저 고른 제안이
    # 문서 안 위치 때문에 밀린다. 승자는 **사람이 먼저 고른 것**이어야 한다 —
    # 그게 목록 순서다.
    survivors: List[_Target] = []
    claimed: List[Tuple[int, int]] = []
    for t in span_some:
        span = t.ref.span
        if any(_overlaps(span, acc) for acc in claimed):
            t.reason = _REASON_OVERLAP
            continue
        claimed.append(span)
        survivors.append(t)

    # ── 2단계: 치환은 start 내림차순(뒤에서부터) ──────────────────────
    #
    # `to_be` 길이가 `as_is` 와 다르므로 앞에서부터 치환하면 뒤 제안의 span 이
    # 어긋난다. 뒤에서부터 하면 아직 처리하지 않은(더 앞쪽) 좌표는 그대로
    # 유효하다 — 뒤쪽 치환은 자기 `end` 이후만 바꾸기 때문이다.
    for t in sorted(survivors, key=lambda x: -x.ref.span[0]):
        start, end = t.ref.span
        # span 계약의 핵심 검증 — 이 자리를 건드리기 **직전에** 불변식
        # `value[start:end] == as_is` 를 확인한다. 사람이 S3 에서 값을
        # 먼저 고쳤거나(오래된 제안) span 좌표가 이 문서 버전과 안 맞으면
        # 여기서 걸러진다. 통과 못 하면 절대 치환하지 않는다 — 이게
        # 깨졌을 때 수치가 복제된 채 승인 화면까지 간 사고가 실제로
        # 있었다(HANDOFF.md §4.5).
        if not (0 <= start <= end <= len(value)) or value[start:end] != t.suggestion.as_is:
            t.reason = _REASON_STALE
            continue
        value = value[:start] + (t.suggestion.to_be or "") + value[end:]
        t.applied = True
    doc.fields[field_name] = value


# ════════════════════════════════════════════════════════════════
# 공개 API
# ════════════════════════════════════════════════════════════════


def apply_suggestions(
    documents: List[DocumentInput],
    suggestions: List[Suggestion],
    *,
    scope: str,
    decided_by: str,
    decided_at: datetime,
) -> ApplyOutcome:
    """승인된 제안을 서류에 반영한다. 순수 함수 — 아무것도 저장하지 않는다.

    `documents` 를 변형하지 않는다. 항상 깊은 복사본을 만들어 그 위에서
    치환한다 — 이 함수가 도중에 예외를 던지거나 호출부가 응답을 버려야 할
    때, 게이트웨이가 원본을 그대로 갖고 있어야 한다.

    처리 순서(제안 1건당):

    1. **변조/사전 버전 불일치 검사.** `verify_suggestion_id` 로 재파생
       대조한다. 어긋나면 `unapplied(reason=` 제안이 변조되었거나 사전
       버전이 다릅니다 `)`. 호출부(`api/main.py`, T12)가 이 사유를 보고
       400 으로 바꾼다.
    2. **`requires_choice` 검사.** `to_be` 가 `None` 인 제안은 적용하지
       않는다 — 임의 선택 금지(`HANDOFF.md` §4.5)가 `scope="all"` 일괄
       적용에서도 뚫리면 안 되므로, scope 값과 무관하게 여기서 막는다.
    3. **적용 대상 결정.** `scope="field"` 는 `suggestion.field` 한 자리만.
       `scope="all"` 은 그 자리 + `suggestion.impact` 전부. impact 자리도
       **같은 검증**(as_is 일치)을 거친다 — 사람이 그 자리만 먼저 고쳤을
       수 있기 때문이다.
    4. **필드 단위로 묶어 치환.** 같은 (서류, 필드) 를 건드리는 대상들을
       모아 `_apply_group` 에 넘긴다 — span 오프셋이 서로 영향을 주는
       단위가 필드이기 때문이다(제안이 아니라).

    제안 하나의 **주 필드**(`suggestion.field`, scope 와 무관하게 항상
    시도된다)가 성공적으로 적용됐을 때만 그 제안에 대한 `Correction`
    (`decision="accepted"`)을 만든다. `scope="all"` 에서 impact 자리 일부가
    실패해도 주 결정 자체는 "승인됐다"이므로 `Correction` 은 그대로 만들고,
    실패한 impact 자리는 별도 `unapplied` 항목으로 함께 돌려준다 — 하나를
    위해 다른 하나를 감추지 않는다.

    `decided_by` 와 `impact` 는 `Correction` 에 그대로 실린다. 기획안 §5.8 이
    `correction` 을 "변경 필드, 이전 값, 새 값, 영향 항목, 승인자, 시각"으로
    정의하고 F2·F5 가 공유한다고 못박았기 때문이다. 무상태라는 이유로 승인자를
    버리면 안 된다 — 게이트웨이가 저장하려면 우리가 돌려줘야 하고, 버리면
    게이트웨이가 스스로 다시 붙여야 해서 `Correction` 을 돌려주는 의미가 없다.
    무상태는 "저장하지 않는다"이지 "받은 사실을 잃어버린다"가 아니다.
    """
    if scope not in ("field", "all"):
        # `scope` 는 이 함수의 파라미터이지 사용자가 채우는 HTTP 필드가
        # 아니다(그건 `api/main.py` 의 Pydantic enum 이 막는다) — 여기서
        # 걸리면 호출부(게이트웨이/T12)의 배선 실수다.
        raise ValueError(f"알 수 없는 scope: {scope!r} ('field' 또는 'all' 만 허용)")

    docs_copy = copy.deepcopy(documents)

    unapplied: List[dict] = []
    targets: List[_Target] = []

    def _reject_whole(s: Suggestion, reason: str) -> None:
        unapplied.append(
            {"suggestion_id": s.suggestion_id, "reason": reason, "field": s.field.to_dict()}
        )

    for s in suggestions:
        if not verify_suggestion_id(s):
            _reject_whole(s, _REASON_TAMPERED)
            continue
        if s.requires_choice:
            _reject_whole(s, _REASON_REQUIRES_CHOICE)
            continue
        targets.append(_Target(s, s.field, True))
        if scope == "all":
            for impact_ref in s.impact:
                targets.append(_Target(s, impact_ref, False))

    # (서류, 필드) 별로 묶는다 — dict 는 삽입 순서를 보존하므로(3.7+) 그룹
    # 순회도 결정론적이고, `evaluate.py`/테스트가 같은 입력에 같은 출력을
    # 기대할 수 있다.
    groups: Dict[Tuple[str, Optional[str], str], List[_Target]] = {}
    for t in targets:
        key = (t.ref.doc, t.ref.doc_id, t.ref.field)
        groups.setdefault(key, []).append(t)

    for (doc_name, doc_id, field_name), group in groups.items():
        doc = _find_document(docs_copy, doc_name, doc_id)
        if doc is None:
            # **무엇을 찾다 실패했는지 말한다.** 가장 흔한 원인은 `doc_id`
            # 불일치다 — `/normalize` 를 `bl` 로 부르면 제안이 `doc_id=None`
            # 을 가리키는데, `/normalize/apply` 에 `doc_id` 를 붙여 보내면
            # 전 제안이 조용히 미적용으로 떨어진다. 200 에 일반적인 문구만
            # 돌려주면 연동하는 쪽은 무엇을 고쳐야 할지 알 수 없다
            # (없는 사전 버전에 가용 목록을 붙이는 것과 같은 논리).
            available = sorted({(d.doc, d.doc_id) for d in docs_copy})
            for t in group:
                t.reason = (
                    f"제안이 가리키는 서류를 요청에서 찾을 수 없습니다: "
                    f"doc={doc_name!r} doc_id={doc_id!r} "
                    f"(요청에 실린 서류: {available})"
                )
            continue
        if doc.fields.get(field_name) is None:
            for t in group:
                t.reason = (
                    f"서류 {doc_name!r} 에 필드 {field_name!r} 가 없거나 비어 있습니다"
                )
            continue
        _apply_group(doc, field_name, group)

    primary_applied: Dict[str, bool] = {}
    # 기획안 `correction` 의 "영향 항목"은 **실제로 함께 바뀐 자리**다.
    # 제안 시점의 `Suggestion.impact`(같은 값이 쓰인 후보 목록)를 그대로
    # 옮기면, `scope="field"` 로 한 자리만 고쳤는데도 여러 자리가 바뀐 것처럼
    # 기록된다. F5(정정 영향분석)가 그걸 시작점으로 그래프를 역산하면 있지도
    # 않은 변경을 따라간다.
    applied_impact: Dict[str, List[FieldRef]] = {}
    for t in targets:
        if t.primary:
            primary_applied[t.suggestion.suggestion_id] = t.applied
        elif t.applied:
            applied_impact.setdefault(t.suggestion.suggestion_id, []).append(t.ref)
        if not t.applied:
            unapplied.append(
                {
                    "suggestion_id": t.suggestion.suggestion_id,
                    "reason": t.reason or _REASON_STALE,
                    "field": t.ref.to_dict(),
                }
            )

    corrections: List[Correction] = [
        Correction(
            suggestion_id=s.suggestion_id,
            field=s.field,
            as_is=s.as_is,
            to_be=s.to_be,
            term_class=s.term_class,
            decision="accepted",
            decided_by=decided_by,
            decided_at=decided_at,
            impact=applied_impact.get(s.suggestion_id, []),
            reason=None,
            note=None,
        )
        for s in suggestions
        if primary_applied.get(s.suggestion_id)
    ]

    return ApplyOutcome(documents=docs_copy, corrections=corrections, unapplied=unapplied)


def reject_suggestions(
    suggestions: List[Suggestion],
    *,
    reason: str,
    note: str,
    decided_by: str,
    decided_at: datetime,
) -> List[Correction]:
    """거절 사유를 기록할 `Correction` 목록을 만든다. 서류는 건드리지 않는다.

    거절은 값을 바꾸지 않으므로 span 계약도, 변조 대조도 관여하지 않는다 —
    사람이 "이 제안이 틀렸다/필요 없다"고 판단한 사실만 남긴다. 저장은
    게이트웨이가 한다(`HANDOFF.md` §2).

    `reason` 은 닫힌 집합(`in_house`|`counterparty`|`false_positive`|`other`)
    이지만 그 enum 검증은 여기서 하지 않는다 — 도메인 객체는 HTTP 상태
    코드(422)를 모른다. `api/main.py` 경계(Pydantic)의 몫이다.

    `decided_by` 는 `apply_suggestions` 와 같은 이유로 받기만 하고
    `Correction` 에 싣지 않는다 — 그 타입에 그런 필드가 없다.
    """
    return [
        Correction(
            suggestion_id=s.suggestion_id,
            field=s.field,
            as_is=s.as_is,
            to_be=s.to_be,
            term_class=s.term_class,
            decision="rejected",
            decided_by=decided_by,
            decided_at=decided_at,
            # 거절은 아무것도 바꾸지 않았으므로 함께 바뀐 자리도 없다.
            # `Suggestion.impact`(바뀌었을 뻔한 자리)를 여기 옮기면 거절
            # 기록이 변경 기록처럼 읽힌다.
            impact=[],
            reason=reason,
            note=note,
        )
        for s in suggestions
    ]


__all__ = [
    "ApplyOutcome",
    "SUGGESTION_ID_PREFIX",
    "apply_suggestions",
    "reject_suggestions",
    "suggestion_id",
    "verify_suggestion_id",
]

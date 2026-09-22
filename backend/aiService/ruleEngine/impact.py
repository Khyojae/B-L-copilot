"""
정정 영향분석 (기획안 F5, 축소 구현).

보고서(`붙임3_...개발보고서 수정17`) 원문: "정합성 그래프 역산(EQ·SUM·REF)",
"룰 카탈로그 40개에서 제약 자동 도출", "EQ 제약을 탐색 깊이 1로 역산해 영향
체크리스트 산출".

## 새 데이터를 만들지 않는다

`rules.yaml`의 `lc_field:` 키(서류 필드 ↔ L/C 필드)와 `cross_rules.yaml`의
`left`/`right`(서류 필드 ↔ 서류 필드)가 이미 그래프의 간선이다. 이 모듈은
카탈로그를 다시 읽지 않고, 엔진이 이미 읽어 검증한 `rules`/`cross_rules`
리스트를 그대로 받아 그 안에서 간선만 뽑아낸다. 카탈로그가 하나 더
생기면(예: SUM·REF 계열) 이 모듈도 따로 손대야 하지만, 지금 있는 39건에서는
룰을 하나도 새로 쓸 필요가 없다.

## EQ 만 쓰는 이유 (축소 범위)

"고치면 상대편도 확인해야 하는" 관계는 **양쪽이 같아야 하는** 룰뿐이다.
`required`(존재 검사)·`date_not_after`·`numeric_not_above`·`amount_not_above`
(부등식)·`contains_*`·`forbidden_*`(조건부 단일 필드)는 한쪽 필드를 고친다고
다른 서류의 특정 필드를 확인해야 하는 관계가 아니다 — 존재 여부나 상한선
검사이지 "같아야 하는 값"이 아니기 때문이다. SUM(합계 대조)·REF(참조 무결성
중 비대칭 것)는 카탈로그에 아직 없어 이번 범위 밖으로 남긴다.

## 깊이 1만 보는 이유

체인을 타고 들어가면(A=B, B=C 이므로 A 확인 시 C 도 노출) 축소 범위를 넘는
탐색이 된다. 지금 그래프에서 한 노드의 차수는 최대 2~3이라 깊이를 늘려도
체감 효과가 크지 않고, 늘리는 순간 "몇 단계까지 보여줄 것인가"라는 새
설계 질문이 생긴다. 보고서가 명시한 범위(깊이 1)를 그대로 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .cross_doc import BILL_OF_LADING, LC_DOC

# "정정하면 상대편도 확인해야 하는" 동치 계열 체크. checks.py/cross_doc.py의
# 함수 이름과 정확히 같은 문자열이어야 한다 — 카탈로그의 `check` 값이 곧 이 값이다.
EQ_CHECKS = frozenset({
    "match_place",
    "within_tolerance",
    "same_party",
    "same_reference",
    "goods_compatible",
    "same_quantity",
})

Node = Tuple[str, str]  # (서류 종류, 필드명)


@dataclass(frozen=True)
class ImpactItem:
    """영향 체크리스트 1행."""

    doc: str
    field: str
    rule_id: str
    source: str
    reason: str
    # 간선이 된 룰의 심각도(critical·warning·info). 이 이웃을 안 맞추면 그
    # 룰이 그 심각도로 위반이 되므로, 확인의 긴급도가 곧 룰의 심각도다.
    severity: str

    def to_dict(self) -> dict:
        return {
            "doc": self.doc,
            "field": self.field,
            "rule_id": self.rule_id,
            "source": self.source,
            "reason": self.reason,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class _Edge:
    other: Node
    rule_id: str
    source: str
    title: str
    severity: str


class ConsistencyGraph:
    """룰 카탈로그에서 자동 도출한 정합성 그래프.

    노드는 (서류 종류, 필드명), 간선은 EQ 계열 룰 1건이다. 무향 그래프로
    둔다 — "A 를 고치면 B 를 확인하라"는 어느 쪽에서 시작해도 성립한다.
    """

    def __init__(self) -> None:
        self._edges: Dict[Node, List[_Edge]] = {}

    def _add(
        self, a: Node, b: Node, *, rule_id: str, source: str, title: str, severity: str
    ) -> None:
        if a == b:
            return
        self._edges.setdefault(a, []).append(
            _Edge(other=b, rule_id=rule_id, source=source, title=title, severity=severity)
        )
        self._edges.setdefault(b, []).append(
            _Edge(other=a, rule_id=rule_id, source=source, title=title, severity=severity)
        )

    @classmethod
    def build(cls, rules: List[dict], cross_rules: List[dict]) -> "ConsistencyGraph":
        graph = cls()

        # rules.yaml: 서류 필드 ↔ L/C 필드. `lc_field` 가 있어야 상대 노드가
        # 정해진다 — 없는 룰(required 등)은 애초에 EQ_CHECKS 에도 없다.
        for rule in rules:
            if rule.get("check") not in EQ_CHECKS:
                continue
            lc_field = rule.get("lc_field")
            if not lc_field:
                continue
            for name in rule.get("fields") or ():
                graph._add(
                    (BILL_OF_LADING, name),
                    (LC_DOC, lc_field),
                    rule_id=rule["id"],
                    source=rule.get("source", ""),
                    title=rule.get("title", ""),
                    severity=rule["severity"],
                )

        # cross_rules.yaml: 서류 필드 ↔ 서류 필드.
        for rule in cross_rules:
            if rule.get("check") not in EQ_CHECKS:
                continue
            left = rule.get("left") or {}
            right = rule.get("right") or {}
            if not left.get("field") or not right.get("field"):
                continue
            graph._add(
                (left["doc"], left["field"]),
                (right["doc"], right["field"]),
                rule_id=rule["id"],
                source=rule.get("source", ""),
                title=rule.get("title", ""),
                severity=rule["severity"],
            )

        return graph

    def impacted(self, doc: str, field: str) -> List[ImpactItem]:
        """`(doc, field)` 에서 깊이 1의 이웃. 순서는 결정론(룰 ID 순)."""
        edges = self._edges.get((doc, field), [])
        items = [
            ImpactItem(
                doc=edge.other[0],
                field=edge.other[1],
                rule_id=edge.rule_id,
                source=edge.source,
                reason=f"{edge.title} ({edge.rule_id})",
                severity=edge.severity,
            )
            for edge in edges
        ]
        return sorted(items, key=lambda i: i.rule_id)


__all__ = ["ConsistencyGraph", "EQ_CHECKS", "ImpactItem"]

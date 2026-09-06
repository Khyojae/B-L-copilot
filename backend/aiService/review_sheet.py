"""조문 인용 검토표 생성 (기획안 9절 "멘토 기업 실무 검증").

룰 카탈로그의 `source` 가 실제 조문과 맞는지는 무역 실무 지식이 필요하다.
발표에서 조문이 틀리면 시스템 전체의 신뢰가 무너지므로, 코드 완성과 별개로
확인을 받아야 한다. 이 스크립트는 그 확인을 **받을 수 있는 형태**로 만든다.

실행:
    python -m review_sheet > 조문검토표.md
    python -m review_sheet --html > 조문검토표.html

## 조문 단위로 묶는다

룰은 39건이지만 서로 다른 조문은 그보다 적다. 같은 조문을 인용한 룰이 여럿이면
실무자는 그 조문을 **한 번만** 확인하면 된다. 룰 단위로 늘어놓으면 같은 질문을
여러 번 하게 되고, 검토가 길어지면 끝까지 못 간다.

## 코드를 보여주지 않는다

YAML 을 그대로 던지면 실무자는 읽지 않는다. 필요한 것은 세 가지뿐이다 —
**우리가 인용한 조문**, **우리가 그 조문을 어떻게 이해했는지**, 그리고
**실제로 무엇을 검사하는지**. 판단에 필요 없는 것(가중치, 검사 함수 이름,
필드명)은 빼거나 뒤로 민다.

## 검사 내용을 사람 말로 적는다

`check: presentation_period` 는 실무자에게 아무 뜻이 없다. 무엇을 어떤 조건에서
하자로 보는지를 풀어 써야 "그 해석이 맞다/틀리다"를 판단할 수 있다.
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from ruleEngine.cross_doc import read_cross_catalog
from ruleEngine.engine import read_catalog

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
SEVERITY_LABEL = {"critical": "치명", "warning": "경고", "info": "참고"}

# 검사 함수 → 사람이 읽을 설명. 실무자는 함수 이름으로 판단하지 못한다.
#
# **등록된 검사와 이 표가 어긋나면 안 된다.** 빠뜨리면 함수 이름이 그대로
# 실무자에게 나가고, 그 칸은 판단할 수 없어 조용히 건너뛰어진다.
# 테스트가 대조한다(`test_review_sheet.py`).
CHECK_TEXT: Dict[str, str] = {
    "required": "값이 비어 있으면 하자로 본다",
    "required_if_lc": "신용장이 그 조건을 지정했는데 서류에 값이 없으면 하자로 본다",
    "match_place": "서류의 지명·상호가 신용장 지정과 저촉하면 하자로 본다",
    "date_not_after": "서류 날짜가 신용장 기한을 넘으면 하자로 본다",
    "presentation_period": "선적일로부터 제시기간(기본 21일)이 지나면 하자로 본다",
    "date_not_in_future": "서류 날짜가 제시 시점보다 미래이면 하자로 본다",
    "numeric_not_above": "수치가 신용장 한도를 넘으면 하자로 본다",
    "within_tolerance": "수치가 허용 오차(신용장 39A, 없으면 ±10%)를 벗어나면 하자로 본다",
    "contains_forbidden": "정해진 문구가 들어 있으면 하자로 본다",
    "contains_keywords": "있어야 할 문구가 없으면 하자로 본다",
    "contains_incoterms": "가격 조건(Incoterms) 표기가 없으면 하자로 본다",
    "forbidden_when_prohibited": "신용장이 금지한 조건인데 서류에 그 정황이 있으면 하자로 본다",
    "freight_prepaid_required": "신용장이 운임 선불인데 서류에 후불 표시가 있으면 하자로 본다",
    "bl_in_documents_required": "신용장 요구 서류 목록에 선하증권이 없으면 알린다",
    # 서류 간
    "same_party": "두 서류의 당사자 표기가 저촉하면 하자로 본다",
    "goods_compatible": "두 서류의 물품 명세가 저촉하면 하자로 본다",
    "same_quantity": "두 서류의 수량·중량·용적이 다르면 하자로 본다",
    "same_reference": "두 서류의 참조 번호가 다르면 하자로 본다",
    "amount_not_above": "앞 서류의 금액이 뒤 서류를 넘으면 하자로 본다",
}

# 메시지 치환자 → 실무자가 읽을 표기. `{detail}` 같은 것이 그대로 나가면
# 문장이 끊겨 읽히고, 무엇을 묻는지가 흐려진다.
PLACEHOLDER_TEXT: Dict[str, str] = {
    "{bl}": "〈서류 값〉",
    "{lc}": "〈신용장 값〉",
    "{left}": "〈앞 서류 값〉",
    "{right}": "〈뒤 서류 값〉",
    "{detail}": "〈해당 값〉",
}


def readable_message(message: str) -> str:
    for token, text in PLACEHOLDER_TEXT.items():
        message = message.replace(token, text)
    return message


def split_source(source: str) -> Tuple[str, str]:
    """`조문 — 우리 해석` 을 나눈다. 구분자가 없으면 해석이 비어 있다."""
    for dash in (" — ", " - ", " – "):
        if dash in source:
            head, tail = source.split(dash, 1)
            return head.strip(), tail.strip()
    return source.strip(), ""


def load_rules() -> List[dict]:
    """서류별 룰과 서류 간 룰을 한 목록으로. 어디서 왔는지는 표시해 둔다."""
    rules, _ = read_catalog()
    cross, _ = read_cross_catalog()

    out = []
    for r in rules:
        out.append({**r, "_scope": "서류"})
    for r in cross:
        target = (
            f"{r['left']['doc']} ↔ {r['right']['doc']}"
            if r.get("left") and r.get("right") else "서류 간"
        )
        out.append({**r, "_scope": target})
    return out


def group_by_article(rules: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for rule in rules:
        article, _ = split_source(rule.get("source", ""))
        grouped[article or "(근거 없음)"].append(rule)
    return grouped


def _sorted_articles(grouped: Dict[str, List[dict]]) -> List[str]:
    """치명 룰을 가진 조문부터. 확인이 중간에 끊겨도 중요한 것은 끝난다."""
    def key(article: str):
        rules = grouped[article]
        worst = min(SEVERITY_ORDER.get(r.get("severity", "info"), 9) for r in rules)
        return (worst, -len(rules), article)

    return sorted(grouped, key=key)


def render_markdown(rules: List[dict]) -> str:
    grouped = group_by_article(rules)
    articles = _sorted_articles(grouped)

    lines = [
        "# 조문 인용 검토표",
        "",
        f"룰 **{len(rules)}건** · 서로 다른 조문 **{len(articles)}건**",
        "",
        "## 부탁드리는 것",
        "",
        "각 조문에 대해 **두 가지만** 봐 주십시오.",
        "",
        "1. **인용한 조문 번호가 맞는가** — 예: 제시기간 21일이 정말 UCP 600 14(c) 인가",
        "2. **우리 해석이 맞는가** — 그 조문을 우리가 이해한 대로 써도 되는가",
        "",
        "이 문장들은 화면과 리포트에 **그대로 인용되어 사용자에게 보입니다.** "
        "틀린 조문이 나가면 시스템 전체의 신뢰가 무너지므로, 애매하면 "
        "'모르겠다'로 남겨 주시는 편이 낫습니다.",
        "",
        "판정 로직이나 코드는 보실 필요 없습니다. 아래 '실제 검사' 열은 "
        "우리가 무엇을 하자로 잡는지를 풀어 쓴 것입니다.",
        "",
        "---",
        "",
        "## 조문별 검토",
        "",
    ]

    for index, article in enumerate(articles, start=1):
        items = sorted(
            grouped[article],
            key=lambda r: (SEVERITY_ORDER.get(r.get("severity", "info"), 9), r["id"]),
        )
        _, interpretation = split_source(items[0].get("source", ""))

        lines.append(f"### {index}. {article}")
        lines.append("")
        if interpretation:
            lines.append(f"> **우리 해석:** {interpretation}")
            lines.append("")

        lines.append("| 판정 | 검사 항목 | 심각도 | 실제 검사 | 사용자에게 보이는 문구 |")
        lines.append("|---|---|---|---|---|")
        for rule in items:
            check = CHECK_TEXT.get(rule.get("check", ""), rule.get("check", ""))
            scope = rule.get("_scope", "")
            title = rule.get("title", "")
            if scope and scope != "서류":
                title = f"{title} ({scope})"
            lines.append(
                f"| ☐ 맞음 ☐ 틀림 | {title} "
                f"| {SEVERITY_LABEL.get(rule.get('severity', ''), '')} "
                f"| {check} | {readable_message(rule.get('message', ''))} |"
            )
        lines.append("")
        lines.append("**의견:**")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend([
        "## 확인이 끝나면",
        "",
        "맞다고 확인된 항목을 알려 주시면 카탈로그에 `verified` 표시를 답니다. "
        "서버 기동 로그와 `GET /rules` 가 남은 건수를 계속 보고하므로 진척이 "
        "숫자로 보입니다.",
        "",
    ])
    return "\n".join(lines)


_STYLE = """
:root {
  --paper:      #F5F6F7;
  --card:       #FFFFFF;
  --ink:        #16202B;
  --ink-muted:  #5A6673;
  --rule:       #D8DDE3;
  --rule-soft:  #E8EBEF;
  --accent:     #1F4E79;
  --accent-dim: #E3ECF4;
  --sev-crit:   #B3261E;
  --sev-warn:   #8A5300;
  --sev-info:   #4B5563;
  --sev-crit-bg:#FBE9E7;
  --sev-warn-bg:#FBF1E0;
  --sev-info-bg:#EDEFF2;
  --serif: Georgia, 'Times New Roman', 'Nanum Myeongjo', 'Batang', serif;
  --sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic',
          'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
  --mono: ui-monospace, 'Cascadia Mono', Consolas, 'D2Coding', monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #11161B; --card: #1A2128; --ink: #E4E9ED; --ink-muted: #96A2AD;
    --rule: #2C3641; --rule-soft: #222B34; --accent: #8FBBE0;
    --accent-dim: #1D2B36;
    --sev-crit: #F1958C; --sev-warn: #E0AC63; --sev-info: #A8B3BE;
    --sev-crit-bg: #2E1A18; --sev-warn-bg: #2C2314; --sev-info-bg: #232A31;
  }
}
:root[data-theme="dark"] {
  --paper: #11161B; --card: #1A2128; --ink: #E4E9ED; --ink-muted: #96A2AD;
  --rule: #2C3641; --rule-soft: #222B34; --accent: #8FBBE0;
  --accent-dim: #1D2B36;
  --sev-crit: #F1958C; --sev-warn: #E0AC63; --sev-info: #A8B3BE;
  --sev-crit-bg: #2E1A18; --sev-warn-bg: #2C2314; --sev-info-bg: #232A31;
}

* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font-family: var(--sans); font-size: 16px; line-height: 1.65;
  -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 62rem; margin: 0 auto; padding: 3rem 1.5rem 5rem; }

header.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 1.5rem; }
.eyebrow {
  font-family: var(--mono); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: var(--ink-muted); margin: 0 0 .6rem;
}
h1 {
  font-family: var(--serif); font-weight: 600; font-size: clamp(1.9rem, 4vw, 2.6rem);
  line-height: 1.15; margin: 0; text-wrap: balance; letter-spacing: -.01em;
}
.tally { display: flex; flex-wrap: wrap; gap: 2rem; margin: 1.6rem 0 0; }
.tally div { display: flex; flex-direction: column; gap: .1rem; }
.tally b {
  font-family: var(--serif); font-size: 1.9rem; font-weight: 600; line-height: 1;
  font-variant-numeric: tabular-nums;
}
.tally span {
  font-family: var(--mono); font-size: .7rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted);
}

.brief { margin: 2.5rem 0 0; max-width: 60ch; }
.brief h2 {
  font-family: var(--serif); font-size: 1.15rem; font-weight: 600;
  margin: 0 0 .7rem;
}
.brief ol { margin: 0 0 1.1rem; padding-left: 1.2rem; }
.brief li { margin-bottom: .45rem; }
.brief p { margin: 0 0 .9rem; }
.brief strong { font-weight: 600; }
.warn {
  border-left: 3px solid var(--sev-crit); background: var(--sev-crit-bg);
  padding: .85rem 1.1rem; margin: 0; border-radius: 0 4px 4px 0;
}

.counter {
  position: sticky; top: 0; z-index: 5; margin: 2.5rem 0 0;
  background: var(--card); border: 1px solid var(--rule); border-radius: 6px;
  padding: .7rem 1.1rem; display: flex; align-items: center; gap: .9rem;
  font-family: var(--mono); font-size: .8rem;
}
.counter .bar {
  flex: 1; height: 5px; background: var(--rule-soft); border-radius: 3px;
  overflow: hidden;
}
.counter .bar i { display: block; height: 100%; width: 0; background: var(--accent);
  transition: width .25s ease; }
@media (prefers-reduced-motion: reduce) { .counter .bar i { transition: none; } }

article.item {
  margin-top: 2.2rem; background: var(--card);
  border: 1px solid var(--rule); border-radius: 6px; overflow: hidden;
}
article.item > .head {
  display: flex; gap: 1rem; align-items: baseline;
  padding: 1.1rem 1.4rem; border-bottom: 1px solid var(--rule-soft);
}
.seq {
  font-family: var(--mono); font-size: .78rem; color: var(--accent);
  background: var(--accent-dim); border-radius: 3px; padding: .18rem .5rem;
  font-variant-numeric: tabular-nums; flex: none;
}
.cite {
  font-family: var(--serif); font-size: 1.22rem; font-weight: 600; margin: 0;
  text-wrap: balance;
}
.gloss {
  margin: 0; padding: 1rem 1.4rem; color: var(--ink-muted);
  border-bottom: 1px solid var(--rule-soft); max-width: 68ch;
}
.gloss b {
  font-family: var(--mono); font-size: .68rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--accent); display: block;
  margin-bottom: .3rem; font-weight: 400;
}
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th {
  text-align: left; font-family: var(--mono); font-weight: 400;
  font-size: .68rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-muted); padding: .7rem 1.4rem; border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}
td { padding: .8rem 1.4rem; border-bottom: 1px solid var(--rule-soft);
     vertical-align: top; }
tr:last-child td { border-bottom: none; }
td.mark { white-space: nowrap; }
label.chk { display: inline-flex; align-items: center; gap: .35rem; cursor: pointer; }
label.chk + label.chk { margin-left: .7rem; }
input[type=radio] { accent-color: var(--accent); margin: 0; }
input:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.sev {
  font-family: var(--mono); font-size: .68rem; letter-spacing: .06em;
  padding: .12rem .45rem; border-radius: 3px; white-space: nowrap;
}
.sev.critical { color: var(--sev-crit); background: var(--sev-crit-bg); }
.sev.warning  { color: var(--sev-warn); background: var(--sev-warn-bg); }
.sev.info     { color: var(--sev-info); background: var(--sev-info-bg); }
.msg { color: var(--ink-muted); }
.note { padding: 1rem 1.4rem; border-top: 1px solid var(--rule); }
.note b {
  font-family: var(--mono); font-size: .68rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted); font-weight: 400;
}
.note .lines {
  margin-top: .5rem; height: 3.2rem; border-radius: 4px;
  background: repeating-linear-gradient(
    to bottom, transparent, transparent 1.55rem,
    var(--rule-soft) 1.55rem, var(--rule-soft) calc(1.55rem + 1px));
}
footer {
  margin-top: 3.5rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
  color: var(--ink-muted); font-size: .9rem; max-width: 62ch;
}
footer code {
  font-family: var(--mono); font-size: .85em; background: var(--rule-soft);
  padding: .1rem .35rem; border-radius: 3px;
}

@media print {
  body { background: #fff; }
  .counter { display: none; }
  article.item { break-inside: avoid; border-color: #999; }
}
"""

_SCRIPT = """
const boxes = () => Array.from(document.querySelectorAll('article.item'));
function refresh() {
  const items = boxes();
  const done = items.filter(a => a.querySelector('input:checked')).length;
  document.getElementById('done').textContent = done;
  document.getElementById('fill').style.width =
    (items.length ? done / items.length * 100 : 0) + '%';
}
document.addEventListener('change', e => {
  if (e.target.matches('input[type=radio]')) refresh();
});
refresh();
"""


def render_html(rules: List[dict]) -> str:
    """실무자에게 그대로 넘길 수 있는 검토 페이지.

    화면에서 체크하며 볼 수도 있고 인쇄해서 손으로 표시할 수도 있게 둘 다
    맞춘다. 어느 쪽으로 돌려받을지는 우리가 정하지 못한다.

    **저장되지 않는다는 것을 페이지가 스스로 밝힌다.** 체크가 남는 줄 알고
    창을 닫으면 검토가 통째로 날아간다.
    """
    e = html.escape
    grouped = group_by_article(rules)
    articles = _sorted_articles(grouped)
    critical = sum(1 for r in rules if r.get("severity") == "critical")

    out: List[str] = [
        "<title>조문 인용 검토표</title>",
        f"<style>{_STYLE}</style>",
        '<div class="wrap">',
        '<header class="masthead">',
        '<p class="eyebrow">B/L Copilot · 하자 검증 룰 카탈로그</p>',
        "<h1>조문 인용 검토표</h1>",
        '<div class="tally">',
        f"<div><b>{len(articles)}</b><span>검토할 조문</span></div>",
        f"<div><b>{len(rules)}</b><span>인용한 룰</span></div>",
        f"<div><b>{critical}</b><span>치명 등급</span></div>",
        "<div><b>0</b><span>확인 완료</span></div>",
        "</div></header>",
        '<section class="brief">',
        "<h2>부탁드리는 것</h2>",
        "<ol>",
        "<li><strong>인용한 조문 번호가 맞는지</strong> — 예를 들어 제시기간 21일이 "
        "정말 UCP 600 Art.14(c) 인지</li>",
        "<li><strong>우리 해석이 맞는지</strong> — 그 조문을 우리가 이해한 대로 "
        "써도 되는지</li>",
        "</ol>",
        '<p class="warn">아래 문장들은 <strong>화면과 리포트에 그대로 인용되어 '
        "사용자에게 보입니다.</strong> 틀린 조문이 나가면 시스템 전체의 신뢰가 "
        "무너지므로, 애매하면 판단을 비워 두고 의견란에 적어 주시는 편이 낫습니다.</p>",
        "<p>판정 로직이나 코드는 보실 필요 없습니다. ‘실제 검사’ 열은 우리가 무엇을 "
        "하자로 잡는지를 풀어 쓴 것입니다. 조문은 <strong>치명 등급을 가진 것부터</strong> "
        "놓았습니다 — 중간에 멈추셔도 중요한 것은 끝나도록.</p>",
        "</section>",
        '<div class="counter"><span><b id="done">0</b> / '
        f'{len(articles)} 조문</span><span class="bar"><i id="fill"></i></span>'
        "<span>표시는 저장되지 않습니다</span></div>",
    ]

    for index, article in enumerate(articles, start=1):
        items = sorted(
            grouped[article],
            key=lambda r: (SEVERITY_ORDER.get(r.get("severity", "info"), 9), r["id"]),
        )
        _, gloss = split_source(items[0].get("source", ""))

        out.append('<article class="item">')
        out.append(
            f'<div class="head"><span class="seq">{index:02d}</span>'
            f'<h2 class="cite">{e(article)}</h2></div>'
        )
        if gloss:
            out.append(f'<p class="gloss"><b>우리 해석</b>{e(gloss)}</p>')

        out.append('<div class="scroll"><table>')
        out.append(
            "<thead><tr><th>판정</th><th>검사 항목</th><th>등급</th>"
            "<th>실제 검사</th><th>사용자에게 보이는 문구</th></tr></thead><tbody>"
        )
        for rule in items:
            sev = rule.get("severity", "info")
            scope = rule.get("_scope", "")
            title = rule.get("title", "")
            if scope and scope != "서류":
                title = f"{title} <span class=\"msg\">({e(scope)})</span>"
            else:
                title = e(title)
            name = f"j{index}_{e(rule['id'])}"
            out.append(
                "<tr>"
                f'<td class="mark">'
                f'<label class="chk"><input type="radio" name="{name}" value="ok">'
                "맞음</label>"
                f'<label class="chk"><input type="radio" name="{name}" value="no">'
                "틀림</label></td>"
                f"<td>{title}</td>"
                f'<td><span class="sev {e(sev)}">'
                f"{SEVERITY_LABEL.get(sev, e(sev))}</span></td>"
                f"<td>{e(CHECK_TEXT.get(rule.get('check', ''), rule.get('check', '')))}</td>"
                f'<td class="msg">{e(readable_message(rule.get("message", "")))}</td>'
                "</tr>"
            )
        out.append("</tbody></table></div>")
        out.append('<div class="note"><b>의견</b><div class="lines"></div></div>')
        out.append("</article>")

    out.extend([
        "<footer>",
        "<p>확인이 끝난 항목을 알려 주시면 카탈로그에 <code>verified</code> 표시를 "
        "답니다. 서버 기동 로그와 <code>GET /rules</code> 가 남은 건수를 계속 "
        "보고하므로 진척이 숫자로 보입니다.</p>",
        "<p>이 표는 <code>python -m review_sheet --html</code> 로 룰 카탈로그에서 "
        "직접 생성됩니다. 룰이 바뀌면 다시 뽑으면 됩니다.</p>",
        "</footer></div>",
        f"<script>{_SCRIPT}</script>",
    ])
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="조문 인용 검토표 (기획안 9절)")
    parser.add_argument("--html", action="store_true", help="HTML 로 출력")
    args = parser.parse_args()

    rules = load_rules()
    out = render_html(rules) if args.html else render_markdown(rules)
    sys.stdout.write(out)


if __name__ == "__main__":
    main()

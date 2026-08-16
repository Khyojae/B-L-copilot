"""실물 말뭉치로 F1 → F3 → F4 를 흘려 본다.

실행:
    python -m corpus_check                    # 300건 표본
    python -m corpus_check --count 1000
    python -m corpus_check --all              # 21,232건 (건당 ~0.8초, 5시간대)
    python -m corpus_check --sheet 검토표.md   # 잡힌 하자를 사람이 볼 형태로

## 왜 pytest 가 아닌가

`.corpus/` 는 gitignore 다. 이 점검을 테스트 스위트에 넣으면 말뭉치가 있는
기계 한 대에서만 돌고 나머지 전부에서 **조용히 스킵**된다. 남는 것은 "실물
e2e 테스트가 있다"는 문장뿐이고 그걸 실제로 돌리는 사람은 없다. 초록불이
사실보다 많은 것을 주장하게 된다.

그래서 `api_check.py` · `acceptance.py` 와 같은 층에 둔다. 말뭉치가 없으면
스킵이 아니라 **대놓고 실패한다** — 안 돌았다는 사실이 숨지 않는다.

## as_of 를 서류마다 다시 잡는 이유

말뭉치 서류는 2006~2013년 것이다. 기준 시각을 오늘로 박으면 **전건이 D018
(서류제시기간 경과)로 덮인다.** 그러면 무슨 입력을 넣든 "위험 높음 · D018"
만 나와서 나머지 룰이 도는지를 볼 수 없다.

그래서 `on_board_date` 에 제시기간 안쪽의 며칠을 더해 기준 시각으로 쓴다.
날짜를 못 읽은 서류는 고정 시각으로 떨어지며, 그 수를 따로 센다 — 못 읽은
것을 통과로 세면 파서가 망가져도 이 점검은 초록불로 남는다.

## 하자 건수를 합격 기준으로 쓰지 않는다

정답 라벨이 없다. 실물에서 D011 이 25건 잡혔다는 사실은 그 자체로 좋지도
나쁘지도 않다 — 진짜 하자일 수도, 오탐일 수도 있고 그 판단에는 무역 실무
지식이 든다. 이 스크립트가 판정하는 것은 **경로가 살아 있는가**뿐이고,
잡힌 하자는 `--sheet` 로 사람에게 넘긴다.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
from datetime import timedelta
from pathlib import Path
from typing import Optional

os.environ.setdefault("LLM_STRUCTURED_EXTRACT", "false")

CORPUS = Path(__file__).parent / ".corpus" / "bl"

# 제시기간(21일) 안쪽이면서 0 이 아닌 값. 0 으로 두면 선적 당일이 되어
# '발행일이 선적일보다 빠른가' 류의 룰이 경계값에서만 평가된다.
_DAYS_AFTER_SHIPMENT = 7

# on_board_date 를 못 읽었을 때 쓰는 기준 시각. 말뭉치 서류가 전부 이보다
# 과거라 D018 이 붙는데, 그래도 임의의 오늘보다는 낫다 — 고정값이라 같은
# 표본이 같은 결과를 낸다.
_FALLBACK_AS_OF = "2013-07-01T00:00:00"


def _as_of(bl: dict) -> tuple[str, bool]:
    """서류의 선적일 기준 시각. (시각, 날짜를_읽었는가)."""
    from ruleEngine.checks import parse_date

    raw = bl.get("on_board_date") or bl.get("date_of_issue")
    if raw:
        parsed = parse_date(raw)
        if parsed:
            return (parsed + timedelta(days=_DAYS_AFTER_SHIPMENT)).isoformat(), True
    return _FALLBACK_AS_OF, False


def _sample(count: Optional[int], seed: int) -> list[Path]:
    if not CORPUS.is_dir():
        sys.exit(
            f"말뭉치가 없습니다: {CORPUS}\n"
            "이 점검은 실물 서류가 있어야 돕니다. 없으면 건너뛰는 것이 아니라 "
            "돌리지 않은 것입니다."
        )
    files = sorted(CORPUS.glob("*.json"))
    if not files:
        sys.exit(f"말뭉치 디렉터리가 비어 있습니다: {CORPUS}")
    if count is None or count >= len(files):
        return files
    # 정렬된 앞쪽 N 건만 쓰면 파일명 순서에 실린 편향(촬영 배치·서식)을 그대로
    # 물려받는다. 씨앗을 고정해 표본을 재현 가능하게 두되, 전체에서 뽑는다.
    return random.Random(seed).sample(files, count)


def run(count: Optional[int], seed: int) -> dict:
    from fastapi.testclient import TestClient

    from api.main import app

    files = _sample(count, seed)
    stat = collections.Counter()
    rules: collections.Counter = collections.Counter()
    completeness: list[float] = []
    hits: list[dict] = []
    failures: list[tuple] = []

    with TestClient(app) as client:
        for index, path in enumerate(files, 1):
            if index % 100 == 0:
                print(f"  … {index}/{len(files)}", flush=True)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                extract = client.post("/extract/label", json={
                    "Images": raw.get("Images", {}), "bbox": raw.get("bbox", []),
                })
                if extract.status_code != 200:
                    stat["F1 실패"] += 1
                    failures.append((path.name, "extract", extract.status_code))
                    continue
                draft = extract.json()

                bl = {f["name"]: f["value"] for f in draft["fields"]}
                confidence = {
                    f["name"]: f["confidence"] for f in draft["fields"]
                    if f["confidence"] is not None
                }
                completeness.append(draft["completeness"])
                stat["검증가능"] += bool(draft["is_ready_for_verification"])

                as_of, dated = _as_of(bl)
                stat["선적일 읽음"] += dated
                body = {"bl": bl, "field_confidence": confidence, "as_of": as_of}

                verify = client.post("/verify", json=body)
                if verify.status_code != 200:
                    stat["F3 실패"] += 1
                    failures.append((path.name, "verify", verify.status_code))
                    continue
                verdict = verify.json()["verdict"]

                report = client.post("/report", json=body)
                if report.status_code != 200:
                    stat["F4 실패"] += 1
                    failures.append((path.name, "report", report.status_code))
                    continue

                stat["전구간 통과"] += 1
                stat["보류 발생"] += bool(verdict["held_count"])
                for violation in verdict["violations"]:
                    rules[violation["rule_id"]] += 1
                    hits.append({
                        "doc": path.name,
                        "rule_id": violation["rule_id"],
                        "severity": violation["severity"],
                        "title": violation["title"],
                        "message": violation.get("message", ""),
                        "fields": {
                            name: bl.get(name)
                            for name in (violation.get("fields") or [])
                        },
                        "as_of": as_of[:10],
                        "dated": dated,
                    })
            except Exception as exc:  # noqa: BLE001
                stat["예외"] += 1
                failures.append((path.name, type(exc).__name__, str(exc)[:70]))

    return {
        "total": len(files), "stat": stat, "rules": rules, "hits": hits,
        "failures": failures, "completeness": completeness,
    }


def render(result: dict) -> str:
    total = result["total"]
    stat, rules = result["stat"], result["rules"]
    passed = stat["전구간 통과"]
    comp = result["completeness"]

    lines = [
        "",
        "=" * 62,
        f"실물 말뭉치 {total:,}건 · F1 → F3 → F4",
        "=" * 62,
        f"  전구간 통과      {passed:,} / {total:,}",
        f"  검증가능(F1)     {stat['검증가능']:,} / {total:,}"
        "   ← 나머지는 F1 이 '확인 먼저'로 막은 것",
        f"  선적일 읽음      {stat['선적일 읽음']:,} / {total:,}",
        f"  판정 보류 발생   {stat['보류 발생']:,} / {total:,}",
    ]
    if comp:
        lines.append(f"  평균 채움률      {sum(comp) / len(comp):.1%}")

    for label in ("F1 실패", "F3 실패", "F4 실패", "예외"):
        if stat[label]:
            lines.append(f"  {label}          {stat[label]:,}")

    lines += ["", "  검출된 하자 (합격 기준 아님 — 사람이 봐야 한다):"]
    if rules:
        for rule_id, hit in rules.most_common():
            lines.append(f"    {rule_id}  {hit:,}건")
    else:
        lines.append("    없음")

    if result["failures"]:
        lines += ["", "  실패 상세 (앞 10건):"]
        lines += [f"    ✗ {f}" for f in result["failures"][:10]]

    verdict = "통과" if passed == total else "실패"
    lines += ["", f"  판정: {verdict} — 경로가 {'모두' if passed == total else '일부만'} 살아 있다", ""]
    return "\n".join(lines)


def sheet(result: dict) -> str:
    """잡힌 하자를 실무 검토가 가능한 형태로.

    룰 단위로 묶는다. 같은 룰이 25건을 잡았다면 실무자가 볼 것은 "이 룰의
    해석이 맞는가" 하나이고, 서류 25건은 그 판단의 사례다. 서류 단위로
    늘어놓으면 같은 질문을 25번 하게 된다 — `review_sheet.py` 와 같은 이유다.
    """
    by_rule: dict = collections.defaultdict(list)
    for hit in result["hits"]:
        by_rule[hit["rule_id"]].append(hit)

    out = [
        "# 실물 말뭉치 하자 검토표",
        "",
        f"표본 {result['total']:,}건에서 검출된 하자입니다. **이것이 진짜 하자인지 "
        "판단해 주십시오.** 정답 라벨이 없어 코드로는 확인할 수 없습니다.",
        "",
        "> `기준시각` 은 그 서류의 선적일 + 7일입니다. 말뭉치 서류가 2006~2013년 "
        "것이라 오늘을 기준으로 잡으면 전건이 제시기간 경과로 걸립니다.",
        "",
    ]
    for rule_id, hits in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        first = hits[0]
        out += [
            f"## {rule_id} — {first['title']}",
            "",
            f"- 심각도: **{first['severity']}**",
            f"- 검출: **{len(hits)}건** / {result['total']:,}건",
            "",
            "| 서류 | 기준시각 | 근거 필드 | 메시지 |",
            "|---|---|---|---|",
        ]
        for hit in hits[:15]:
            fields = ", ".join(
                f"`{k}` = {v!r}" for k, v in hit["fields"].items()
            ) or "—"
            message = hit["message"].replace("|", "\\|")
            out.append(
                f"| {hit['doc'].replace('IMG_OCR_6_T_BL_', '')} | {hit['as_of']} "
                f"| {fields} | {message} |"
            )
        if len(hits) > 15:
            out.append(f"| … | | | 외 {len(hits) - 15}건 |")
        out += ["", "**판단:** ☐ 맞는 하자   ☐ 오탐   ☐ 판단 보류", "", "**의견:**", "", "---", ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="실물 말뭉치 F1→F3→F4 점검")
    parser.add_argument("--count", type=int, default=300, help="표본 수 (기본 300)")
    parser.add_argument("--all", action="store_true", help="전건")
    parser.add_argument("--seed", type=int, default=42, help="표본 씨앗")
    parser.add_argument("--sheet", metavar="PATH", help="하자 검토표를 파일로")
    args = parser.parse_args()

    result = run(None if args.all else args.count, args.seed)
    print(render(result))

    if args.sheet:
        Path(args.sheet).write_text(sheet(result), encoding="utf-8")
        print(f"  검토표: {args.sheet} ({len(result['hits']):,}건)\n")

    sys.exit(0 if result["stat"]["전구간 통과"] == result["total"] else 1)


if __name__ == "__main__":
    main()

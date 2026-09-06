"""수용 기준 실측 (19번).

기획안 v2 가 5.1·5.3·5.4 에 붙인 **완료 기준**을 실제로 잰다. 1차 기획안에는
없던 숫자들이라 지금까지 한 번도 측정한 적이 없다.

실행:
    python -m acceptance
    python -m acceptance --count 200 --json acceptance.json

## 최댓값으로 판정한다

명세는 "선적 1건 검증 10초"라고 쓴다. **평균 10초는 절반이 넘긴다는 뜻이다.**
평균으로 보고하면 통과인데 사용자 절반이 기준 밖인 상태가 만들어지므로,
판정은 최댓값으로 하고 분포(p50·p95)를 함께 싣는다.

## 냉시작을 분리한다

첫 1회에는 모델 적재·폰트 등록·룰 카탈로그 파싱이 들어간다. 이건 요청당
비용이 아니라 프로세스당 비용이라, 섞으면 최댓값이 냉시작으로 정해져
정작 요청 비용을 못 본다. 따로 재서 따로 보고한다.

## 잴 수 없는 것을 결과에서 빼지 않는다

룰엔진이 평가불가를 1급 상태로 두는 것과 같은 이유다. 측정하지 못한 항목을
침묵으로 넘기면 "쟀고 통과했다"로 읽힌다. 미측정은 미측정으로 싣고, **왜**
못 쟀는지를 함께 남긴다.

## LLM 서사는 기본으로 끈다

`apply_narrative` 는 GEMINI_API_KEY 가 있으면 외부 API 를 호출한다. 그 경로의
시간은 우리 코드가 아니라 네트워크가 정하므로 기본 측정에서 제외하고, 어느
경로로 쟀는지를 결과에 표기한다. `--llm` 으로 켤 수 있다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Callable, List, Optional, Sequence

from mlModel.synth import EVAL, SyntheticGenerator
from ocr.pipeline import IntakePipeline
from report import apply_narrative, build_report, check_narrative, render_pdf
from ruleEngine import RuleEngine

# ── 수용 기준 (기획안 v2) ────────────────────────────────────────
#
# 숫자는 v2 5.1·5.3·5.4 에서 그대로 옮겼다. 10.5 가 "명세 수치는 초기
# 목표치이며 조정 시 기획안을 함께 갱신하라"고 못박았으므로, 여기서 임의로
# 완화하지 않는다. 못 맞추면 완화가 아니라 보고 대상이다.

TARGET_VERIFY_SECONDS = 10.0        # 5.3 선적 1건 검증
TARGET_REPORT_SECONDS = 15.0        # 5.4 리포트
TARGET_REPORT_PDF_SECONDS = 30.0    # 5.4 PDF 포함
TARGET_INTAKE_10P_SECONDS = 60.0    # 5.1 10페이지 추출
TARGET_RATIO = 1.0                  # 근거 표시율·수치 일치율 100%


@dataclass
class Timing:
    """반복 측정 결과. 냉시작은 표본에 넣지 않는다."""

    cold_ms: float
    warm_ms: List[float] = field(default_factory=list)

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.warm_ms) if self.warm_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.warm_ms:
            return 0.0
        ordered = sorted(self.warm_ms)
        # 표본이 적을 때 index 가 끝을 넘지 않게 자른다.
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    @property
    def max_ms(self) -> float:
        return max(self.warm_ms) if self.warm_ms else 0.0

    def to_dict(self) -> dict:
        return {
            "cold_ms": round(self.cold_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p95_ms": round(self.p95_ms, 1),
            "max_ms": round(self.max_ms, 1),
            "count": len(self.warm_ms),
        }


def measure(fn: Callable[[int], object], count: int) -> Timing:
    """fn 을 count 회 돌려 시간을 잰다. 첫 회는 냉시작으로 뗀다."""
    start = perf_counter()
    fn(0)
    cold_ms = (perf_counter() - start) * 1000

    warm: List[float] = []
    for index in range(1, count):
        start = perf_counter()
        fn(index)
        warm.append((perf_counter() - start) * 1000)
    return Timing(cold_ms=cold_ms, warm_ms=warm)


# ── 결과 ─────────────────────────────────────────────────────────

PASSED = "통과"
FAILED = "미달"
UNMEASURED = "미측정"


@dataclass
class Result:
    """수용 기준 1건의 실측 결과."""

    feature: str        # F1 | F3 | F4
    name: str
    spec: str           # 기획안 근거 절
    target: str         # 사람이 읽는 목표
    status: str         # 통과 | 미달 | 미측정
    measured: str = ""
    note: str = ""
    timing: Optional[Timing] = None

    def to_dict(self) -> dict:
        out = {
            "feature": self.feature,
            "name": self.name,
            "spec": self.spec,
            "target": self.target,
            "status": self.status,
            "measured": self.measured,
            "note": self.note,
        }
        if self.timing is not None:
            out["timing"] = self.timing.to_dict()
        return out


def _fmt_ms(value: float) -> str:
    """읽는 사람 기준으로 단위를 고른다.

    전부 초로 찍으면 `0.000초` 가 나오는데, 그 숫자는 통과 판정을 주면서
    아무것도 말하지 않는다 — 빠른 건지 측정이 안 된 건지 구분되지 않는다.
    """
    if value >= 1000:
        return f"{value / 1000:.2f}초"
    if value >= 1:
        return f"{value:.1f}ms"
    return f"{value * 1000:.0f}µs"


def _seconds_result(
    feature: str, name: str, spec: str, target_seconds: float, timing: Timing
) -> Result:
    """시간 기준 결과. 판정은 최댓값으로 한다."""
    return Result(
        feature=feature,
        name=name,
        spec=spec,
        target=f"{target_seconds:g}초 이하",
        status=PASSED if timing.max_ms <= target_seconds * 1000 else FAILED,
        measured=f"최대 {_fmt_ms(timing.max_ms)} (p95 {_fmt_ms(timing.p95_ms)})",
        timing=timing,
    )


def _ratio_result(
    feature: str, name: str, spec: str, hit: int, total: int, note: str = ""
) -> Result:
    """비율 기준 결과. 명세가 100% 를 요구하는 항목들이다."""
    ratio = hit / total if total else 0.0
    return Result(
        feature=feature,
        name=name,
        spec=spec,
        target="100%",
        status=PASSED if total and ratio >= TARGET_RATIO else FAILED,
        measured=f"{ratio:.2%} ({hit}/{total})",
        note=note,
    )


# ── F3 · F4 측정 ─────────────────────────────────────────────────

def measure_f3_f4(count: int, seed: int, use_llm: bool) -> List[Result]:
    """검증·리포트·PDF 를 같은 표본으로 잰다.

    평가셋 네임스페이스를 쓴다(16번). 개발 중 열람하지 않은 서류로 재는 것이
    시간 측정에서도 맞다 — 룰을 고치며 본 서류만 빠르게 도는 경우를 배제한다.
    """
    generator = SyntheticGenerator(seed=seed, split=EVAL)
    samples = generator.generate(count, 0.5)
    engine = RuleEngine()

    verdicts = []

    def verify(index: int) -> None:
        s = samples[index]
        verdicts.append(engine.verify(s.bl, s.lc, as_of=s.as_of))

    verify_timing = measure(verify, count)

    # **검증부터 잰다.** `/report` 는 verify → build_report → 서사를 한 번에
    # 하므로(`api.main._make_report`), 조립만 재면 사용자가 기다리는 시간이
    # 아니다. 이미 계산해 둔 verdict 를 재사용하면 0.000초가 나오는데, 그
    # 숫자는 통과 판정을 주면서 아무것도 말하지 않는다.
    def report(index: int) -> None:
        s = samples[index]
        verdict = engine.verify(s.bl, s.lc, as_of=s.as_of)
        built = build_report(verdict, s.bl.to_dict(), s.lc, as_of=s.as_of)
        if use_llm:
            apply_narrative(built)

    report_timing = measure(report, count)

    def report_pdf(index: int) -> None:
        s = samples[index]
        verdict = engine.verify(s.bl, s.lc, as_of=s.as_of)
        built = build_report(verdict, s.bl.to_dict(), s.lc, as_of=s.as_of)
        if use_llm:
            built = apply_narrative(built)
        render_pdf(built)

    # PDF 는 한 건이 무거워 전량을 돌리면 측정 자체가 오래 걸린다. 상한을 둔다.
    pdf_count = min(count, 30)
    pdf_timing = measure(report_pdf, pdf_count)

    results = [
        _seconds_result("F3", "선적 1건 검증", "v2 5.3", TARGET_VERIFY_SECONDS, verify_timing),
        _seconds_result("F4", "리포트 생성", "v2 5.4", TARGET_REPORT_SECONDS, report_timing),
        _seconds_result(
            "F4", "리포트 + PDF", "v2 5.4", TARGET_REPORT_PDF_SECONDS, pdf_timing
        ),
    ]
    if pdf_count < count:
        results[-1].note = f"표본 {pdf_count}건 (전량 렌더는 측정 자체가 길어진다)"
    results[1].note = "LLM 서사 포함" if use_llm else "템플릿 서사 (LLM 미포함)"

    results.extend(_measure_evidence_ratios(samples, verdicts, use_llm))
    return results


def _measure_evidence_ratios(samples, verdicts, use_llm: bool) -> List[Result]:
    """근거 표시율·수치 일치율. 시간과 달리 전건이 100% 여야 한다."""
    violations = [v for verdict in verdicts for v in verdict.violations]

    with_source = sum(1 for v in violations if v.source)
    with_remedy = sum(1 for v in violations if v.source and v.remedy)

    # 리포트의 수치가 판정 데이터와 일치하는가. 리포트가 스스로 다시 세는
    # 곳이 있으면 여기서 어긋난다.
    #
    # **서사를 붙인 뒤에 잰다.** 예전에는 `build_report` 만 부르고
    # `apply_narrative` 를 건너뛰었는데, 그러면 템플릿이 채운 필드끼리만
    # 대조하게 되어 LLM 이 산문에 쓴 숫자는 측정 밖에 남는다. v2 5.4 가
    # 요구하는 것은 "리포트 내 **모든** 수치"이므로 그 상태의 100% 는
    # 통과라고 말할 수 없었다.
    matched = 0
    intact = 0
    for sample, verdict in zip(samples, verdicts):
        report = build_report(
            verdict, sample.bl.to_dict(), sample.lc, as_of=sample.as_of
        )
        if use_llm:
            report = apply_narrative(report)
        if (
            report.counts == verdict.counts
            and report.defect_probability == verdict.defect_probability
            and len(report.risks) == len(verdict.violations)
            and len(report.unchecked) == len(verdict.skipped)
        ):
            matched += 1
        if check_narrative(report, report.headline, report.narrative).ok:
            intact += 1

    return [
        _ratio_result(
            "F3", "조문 근거 표시율", "v2 5.3", with_source, len(violations),
            note="룰 카탈로그가 source 를 필수로 요구하므로 구조로 보장된다",
        ),
        _ratio_result(
            "F4", "조문 인용 + 조치 문장 보유율", "v2 5.4",
            with_remedy, len(violations),
        ),
        _ratio_result(
            "F4", "리포트 수치와 판정 데이터 일치율", "v2 5.4",
            matched, len(samples),
            note="LLM 서사 포함" if use_llm else "템플릿 서사 (LLM 미포함)",
        ),
        _ratio_result(
            "F4", "서술 무결성 검사 통과율", "v2 5.7",
            intact, len(samples),
            note=(
                "LLM 서사" if use_llm
                else "템플릿 서사 — LLM 경로는 --llm 으로 재야 한다"
            ),
        ),
    ]


# ── F1 측정 ──────────────────────────────────────────────────────

# 라벨 데이터셋 해상도. 좌표를 비율로 옮기는 기준이라 값 자체는 중요하지 않다.
_LABEL_WIDTH = 1654
_LABEL_HEIGHT = 2340
_PDF_WIDTH = 595.0
_PDF_HEIGHT = 842.0

# 교정된 서식의 정상 B/L 한 장. (필드명, 지면 비율 x, y, 텍스트)
# `field_parser.REGIONS` 가 교정된 그 레이아웃이다 — 이 사실이 아래
# '추출 정확도'를 상한값으로 만든다.
_BL_LINES = [
    ("header", 0.36, 0.03, "BILL OF LADING"),
    ("bl_no", 0.62, 0.08, "B/L NO HG290309"),
    ("shipper", 0.06, 0.14, "GAE WOON CO., LTD."),
    ("consignee", 0.06, 0.21, "DHHJ FRANCHISING CO., LTD."),
    ("notify", 0.06, 0.28, "TRY ENERGY CO., LTD."),
    ("vessel_info", 0.06, 0.40, "MSC BIANCA V.112"),
    ("port_left", 0.06, 0.45, "OMA, JAPAN"),
    ("port_right", 0.55, 0.45, "SHINJIMA, JAPAN"),
    ("cargo", 0.06, 0.55, "27 PKG CELL ASSEMBLY"),
    ("weight", 0.62, 0.62, "TOTAL 884 KG"),
    ("measurement", 0.62, 0.66, "TOTAL 349.64 CBM"),
    ("freight", 0.06, 0.78, "FREIGHT PREPAID $1,741.56"),
    ("issue_place", 0.27, 0.90, "SEOUL, KOREA"),
    ("issue_date", 0.27, 0.93, "SEP 06, 2006"),
]

# 위 서식이 담고 있는 정답. 추출 정확도의 대조군이다.
_BL_TRUTH = {
    "bl_no": "HG290309",
    "shipper": "GAE WOON CO., LTD.",
    "consignee": "DHHJ FRANCHISING CO., LTD.",
    "notify_party": "TRY ENERGY CO., LTD.",
    "port_of_loading": "OMA, JAPAN",
    "port_of_discharge": "SHINJIMA, JAPAN",
}


def _write_bl_pdf(path: Path, pages: int) -> bool:
    """텍스트 레이어를 가진 B/L PDF 를 만든다. PyMuPDF 가 없으면 False."""
    try:
        import pymupdf
    except ImportError:
        return False

    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=_PDF_WIDTH, height=_PDF_HEIGHT)
        for _name, xr, yr, text in _BL_LINES:
            page.insert_text(
                (xr * _PDF_WIDTH, yr * _PDF_HEIGHT), text, fontsize=9, fontname="helv"
            )
    doc.save(str(path))
    doc.close()
    return True


def measure_f1(pages: int = 10) -> List[Result]:
    """텍스트 레이어 PDF 추출 시간과 정확도.

    스캔 경로(PaddleOCR)는 여기서 재지 않는다 — 실물 스캔이 없으면 정확도가
    측정되지 않고, 합성 이미지 1장으로는 여섯 모델 구성이 전부 만점이 나와
    아무것도 구분되지 않는다는 것을 이미 확인했다(2.1절).
    """
    unmeasurable = _f1_unmeasurable()

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "bl_10p.pdf"
        if not _write_bl_pdf(pdf_path, pages):
            return [
                Result(
                    feature="F1", name=f"{pages}페이지 추출", spec="v2 5.1",
                    target=f"{TARGET_INTAKE_10P_SECONDS:g}초 이하", status=UNMEASURED,
                    note="PyMuPDF 미설치 — pip install pymupdf",
                )
            ] + unmeasurable

        pipeline = IntakePipeline()
        drafts = []

        def extract(index: int) -> None:
            drafts.append(pipeline.run_from_pdf(str(pdf_path), page_number=index))

        timing = measure(extract, pages)

        # 명세는 "10페이지 60초"다. 페이지당이 아니라 문서 전체 시간이므로
        # 냉시작을 포함한 총합으로 판정한다.
        total_ms = timing.cold_ms + sum(timing.warm_ms)
        results = [
            Result(
                feature="F1",
                name=f"{pages}페이지 추출 (텍스트 레이어)",
                spec="v2 5.1",
                target=f"{TARGET_INTAKE_10P_SECONDS:g}초 이하",
                status=(
                    PASSED if total_ms <= TARGET_INTAKE_10P_SECONDS * 1000 else FAILED
                ),
                measured=f"총 {_fmt_ms(total_ms)} (페이지당 p50 {_fmt_ms(timing.p50_ms)})",
                timing=timing,
            ),
            _extraction_accuracy(drafts[0]),
        ]

    return results + unmeasurable


def _extraction_accuracy(draft) -> Result:
    """교정된 서식에서의 추출 정확도.

    **수용 기준의 답이 아니다.** 이 레이아웃은 `field_parser.REGIONS` 가
    교정된 바로 그 서식이라, 여기서 나오는 값은 상한이지 실물 성적이 아니다.
    임의 레이아웃에서는 값이 밀린다는 것이 이미 관측돼 있다(선적항 자리에
    "DATE OF ISSUE" 가 들어갔다). 그래서 참고값으로만 싣는다.
    """
    hit = sum(
        1 for name, truth in _BL_TRUTH.items()
        if (draft.get(name).value if draft.get(name) else None) == truth
    )
    return Result(
        feature="F1",
        name="추출 정확도 (텍스트 PDF)",
        spec="v2 5.1",
        target="95%",
        status=UNMEASURED,
        measured=f"참고값 {hit / len(_BL_TRUTH):.2%} ({hit}/{len(_BL_TRUTH)})",
        note=(
            "교정 서식 기준이라 상한값이다. REGIONS 가 이 레이아웃에서 "
            "교정됐으므로 수용 기준의 답으로 쓸 수 없다 — 실물 서식이 필요하다"
        ),
    )


def _f1_unmeasurable() -> List[Result]:
    """지금 잴 수 없는 F1 기준. 왜 못 재는지가 결과의 일부다."""
    return [
        Result(
            feature="F1", name="추출 정확도 (스캔)", spec="v2 5.1", target="85%",
            status=UNMEASURED,
            note=(
                "실물 스캔 말뭉치가 없다. 합성 이미지 1장으로는 모델 구성 여섯 개가 "
                "전부 만점이라 정확도가 구분되지 않는다(2.1절)"
            ),
        ),
        Result(
            feature="F1", name="근거 좌표 보유율", spec="v2 5.1", target="100%",
            status=UNMEASURED,
            note=(
                "구조적으로 잴 수 없다 — `BLFields` 가 좌표를 들고 나오지 않는다. "
                "confidence·provenance 만 남고 bbox 는 파서 안에서 버려진다. "
                "DB 스키마의 field_value 는 자동 추출 값에 좌표를 CHECK 로 요구하므로 "
                "연동 시 반드시 걸린다"
            ),
        ),
        Result(
            feature="F1", name="오추출 라우팅 재현율", spec="v2 5.1", target="90%",
            status=UNMEASURED,
            note=(
                "수단은 생겼다(18번 · `ocr.degrade`). 다만 실행에 PaddleOCR 과 "
                "원본 서류 이미지가 필요해 이 측정에 포함하지 않는다 — 포함하면 "
                "수용 기준 측정 전체가 OCR 설치와 장당 10초에 묶인다. "
                "따로 돌릴 것: python -m ocr.degrade --image <서류.png>"
            ),
        ),
    ]


# ── 보고 ─────────────────────────────────────────────────────────

def render(results: Sequence[Result]) -> str:
    lines = [
        "",
        "수용 기준 실측 (기획안 v2 5.1 · 5.3 · 5.4)",
        "=" * 78,
        f"{'기능':<4} {'기준':<32} {'목표':<12} {'실측':<24} 판정",
        "-" * 78,
    ]
    for r in results:
        lines.append(
            f"{r.feature:<4} {r.name:<32} {r.target:<12} {r.measured:<24} {r.status}"
        )
    lines.append("-" * 78)

    counts = {s: sum(1 for r in results if r.status == s) for s in (PASSED, FAILED, UNMEASURED)}
    lines.append(
        f"통과 {counts[PASSED]} · 미달 {counts[FAILED]} · 미측정 {counts[UNMEASURED]}"
    )

    notes = [r for r in results if r.note]
    if notes:
        lines.append("")
        lines.append("비고")
        for r in notes:
            lines.append(f"  · {r.name}: {r.note}")

    failed = [r for r in results if r.status == FAILED]
    if failed:
        lines.append("")
        lines.append("미달 항목 — 기획안 10.5 에 따라 임의 완화 대상이 아니다")
        for r in failed:
            lines.append(f"  · [{r.feature}] {r.name}: 목표 {r.target} / 실측 {r.measured}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="수용 기준 실측 (19번)")
    parser.add_argument("--count", type=int, default=100, help="F3·F4 표본 수")
    parser.add_argument("--pages", type=int, default=10, help="F1 추출 페이지 수")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--llm", action="store_true",
        help="리포트 서사를 LLM 으로 생성해 잰다 (네트워크에 묶인다)",
    )
    parser.add_argument("--json", type=Path, help="결과를 JSON 으로 저장")
    args = parser.parse_args()

    results = measure_f1(args.pages) + measure_f3_f4(args.count, args.seed, args.llm)
    # 기능 순으로 모아 보여 준다. 측정 순서는 의존 관계지 읽는 순서가 아니다.
    results.sort(key=lambda r: (r.feature, r.status == UNMEASURED))

    print(render(results))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "measured_at": datetime.now().isoformat(timespec="seconds"),
                    "sample_count": args.count,
                    "llm_narrative": args.llm,
                    "results": [r.to_dict() for r in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"JSON 저장: {args.json}")


if __name__ == "__main__":
    main()

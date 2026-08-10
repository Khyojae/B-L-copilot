# F4 — 선제 대응 서류 분석 리포트

> 기획안 5절 F4: "제출 전 종합 리포트 자동 생성: 하자 리스크 요약, 누락 서류·기한 체크리스트, 심각도별 수정 권고, 예상 심사 결과. PDF 출력·공유 가능"
> **AI 기술: F3 결과 종합 + LLM 리포트 생성**

F3 의 `Verdict` 를 사람이 읽는 문서로 옮긴다. `aiService/report/` 에 있다.

기획안 5.2 는 이 리포트의 차별점을 이렇게 규정한다.

> 기존 상용 도구는 은행 심사 후 하자를 "통보"하지만, 본 리포트는 제출 전에 "예방"하는 문서로, 하자 재제출 루프 자체를 제거하는 것을 목표로 함

## 구성

기획안 5.2 의 5개 구성을 그대로 옮겼다. 여기에 하나를 더했다.

| # | 구성 | 출처 |
|---|---|---|
| ① | 요약 (하자 확률·심각도 분포) | `Verdict.counts`, `defect_probability` |
| ② | 항목별 리스크와 **근거 조문** | `Violation.source` (룰 카탈로그) |
| ③ | 누락 서류·제출 기한 체크리스트 | L/C 46A + UCP 600 Art.14(c) 계산 |
| ④ | 수정 권고 (우선순위순) | `Violation.remedy`, 심각도 정렬 |
| ⑤ | 예상 심사 결과 시나리오 | 심각도 분포 + 기한 상태 |
| **부록** | **미검사 항목** | `Verdict.skipped` |

**부록이 기획안에 없는 추가분이다.** 검사하지 못한 룰을 리포트에서 감추면 사용자는 '검사했고 문제없다'로 읽는다. 제출 전 예방을 표방하는 문서가 그 오해를 만들면 안 된다.

⑤ 예상 심사 결과에도 같은 취지가 들어간다:

> 다만 자료 부족으로 검사하지 못한 항목이 3건 있어, 이 결과가 서류 전체를 보증하지는 않습니다.

## 골격은 결정론, LLM 은 산문만

리포트의 수치·체크리스트·기한은 `builder.py` 가 전부 계산한다. LLM(`narrative.py`)은 이미 만들어진 리포트를 사람이 읽을 문장으로 옮기기만 한다.

두 가지 이유다.

1. **LLM 이 없거나 한도에 걸려도 리포트는 나와야 한다.** 발표 중에 외부 API 하나 때문에 산출물이 통째로 비는 상황을 만들지 않는다.
2. **수치를 LLM 이 만들면 검증할 방법이 없다.** 확률·기한·건수를 생성하게 두면 리포트의 숫자와 본문이 어긋나도 아무도 못 잡는다.

`TemplateNarrator` 가 기본값이고, LLM 이 붙으면 `narrative_source` 가 `template` → `llm` 으로 바뀐다. 어느 쪽으로 썼는지 리포트가 스스로 밝힌다.

## 제출 기한 계산

UCP 600 Art.14(c) 는 두 가지를 요구한다.

- 선적일로부터 제시기간(기본 21일, L/C 가 정하면 그 값) 이내
- 그리고 **어떤 경우에도** 신용장 유효기일(31D) 이내

둘 중 **이른 날**이 실질 기한이다. `Deadline.basis` 에 어떻게 계산했는지 남겨서, 사용자가 날짜를 납득할 수 있게 한다.

```python
Deadline(
    presentation_due=date(2026, 6, 22),   # 선적일 + 21일
    expiry=date(2026, 12, 31),            # 31D
    effective_due=date(2026, 6, 22),      # 이른 날
    days_left=12,
    basis="선적일 + 21일(UCP 600 Art.14(c)) / 신용장 유효기일(31D) 중 이른 날",
)
```

기한을 계산하지 못하면 체크리스트에 그 사실을 적는다 — 침묵하면 '기한 문제 없음'으로 읽힌다.

## 예상 심사 결과는 시나리오다

확정 예측이 아니다. 지금 확률의 출처가 학습된 모델이 아니라 룰 가중치일 수 있기 때문이다(`Verdict.model` 이 `rules-v1` 인 경우). 문구에서 단정을 피한다.

| 상태 | 문구 |
|---|---|
| 기한 경과 | 제시기한 경과 — 수리 불가 가능성 높음 |
| CRITICAL 있음 | 하자 통보 및 재제출 요구 예상 |
| WARNING 만 | 심사역 재량 — 하자 지적 가능성 있음 |
| 없음 | 수리 예상 |

기한 경과를 맨 앞에 두는 이유는, 제시기한이 지나면 하자 여부와 무관하게 거절될 수 있어서다.

## PDF

**한글 폰트는 ReportLab 내장 CID 폰트를 쓴다.**

```python
pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
```

원본 `ai_sample/report_generator.py` 는 macOS/Ubuntu 폰트 경로 목록을 뒤지는 방식이라 **Windows 에서 PDF 생성이 실패한다.** CID 폰트는 파일시스템에 의존하지 않아 전 플랫폼에서 동일하게 동작한다. 폰트 파일을 배포에 포함할 필요도 없다.

**`render_pdf()` 는 파일이 아니라 `bytes` 를 반환한다.** 저장 위치(S3·DB·로컬)를 호출부가 정하게 두기 위해서다. 스키마가 확정되면 `verification_reports` 에 넣든 S3 pre-signed URL 로 올리든 이 함수는 바뀌지 않는다.

## 사용

```python
from ruleEngine import RuleEngine, LCTerms
from report import build_report
from report.pdf import render_pdf

verdict = RuleEngine().verify(bl, lc, as_of=now)
report = build_report(
    verdict,
    bl.to_dict(),
    lc,
    submitted_documents=["COMMERCIAL INVOICE", "BILL OF LADING"],
    as_of=now,
)

report.to_dict()                      # S7 화면용 JSON
pathlib.Path("out.pdf").write_bytes(render_pdf(report))
```

## 실행 확인

하자 있는 건과 없는 건 양쪽으로 실제 PDF 를 만들어 확인했다.

```
[defect] 등급 높음 | 확률 1.0 | 리스크 8 | 권고 8 | 미검사 3 | 11,222B  → 3쪽, 한글 1126자
[clean ] 등급 낮음 | 확률 0.0 | 리스크 0 | 권고 0 | 미검사 3 |  6,998B  → 2쪽, 한글  441자
```

추출한 본문에서 근거 조문이 정상 출력되는 것을 확인했다.

```
치명  선적항 불일치
      선적항이 L/C 지정 항구와 다릅니다. (서류 SHANGHAI, CHINA / L/C BUSAN)
      근거: UCP 600 Art.20(a)(iii) — 선하증권상 선적항은 신용장에 명시된 선적항과 일치해야 한다.
      대상 필드: port_of_loading
```

## 테스트

```bash
cd aiService && python -m pytest        # 164 passed
```

PDF 본문 검증에 PyMuPDF 를 쓴다. 파일이 생성됐는지만 보면 한글이 깨져도 통과하므로, 실제로 텍스트를 추출해 대조한다.

## 남은 것

- **LLM Narrator 구현** — 지금은 `TemplateNarrator` 만 있다. 인터페이스(`Narrator` Protocol)는 잡혀 있어 붙이기만 하면 된다. 폐쇄망 프로파일(기획안 3.1 ③)에서는 로컬 LLM 을 쓴다.
- **S7 화면 연동** — `report.to_dict()` 가 그 계약이다.
- **`verification_reports` 저장** — 스키마 확정 후. B파트 요청 시트에서 `file_path` 삭제·S3 전환이 이미 합의된 항목이다.

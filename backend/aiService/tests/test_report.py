"""F4 리포트 테스트.

핵심 관심사는 두 가지다.
  1. 기획안 5.2 의 5개 구성이 전부 채워지는가.
  2. LLM 없이도 리포트가 완성되는가 — 발표 중 외부 API 실패에 대비.
"""

from __future__ import annotations

import zlib
from datetime import datetime

import pytest

from report import (
    TemplateNarrator,
    apply_narrative,
    build_report,
    render_pdf,
)
from report.narrative import LLMNarrator
from ruleEngine import LCTerms, RuleEngine

AS_OF = datetime(2026, 5, 25)


@pytest.fixture(scope="module")
def engine() -> RuleEngine:
    return RuleEngine()


def clean_bl() -> dict:
    return {
        "bl_no": "MAEU123456789",
        "shipper": "HOMINAI CO LTD",
        "consignee": "TO ORDER OF KEB HANA BANK",
        "notify_party": "ABC IMPORT INC",
        "vessel": "EVER GIVEN",
        "voyage_no": "0123W",
        "port_of_loading": "BUSAN, KOREA",
        "port_of_discharge": "LOS ANGELES, USA",
        "description_of_goods": "ELECTRONIC COMPONENTS",
        "gross_weight": "12000 KGS",
        "on_board_date": "2026-05-10",
        "date_of_issue": "2026-05-11",
    }


def matching_lc() -> LCTerms:
    return LCTerms(
        lc_no="LC-2026-0001",
        latest_shipment_date="2026-05-15",
        expiry_date="2026-06-05",
        port_of_loading="BUSAN, KOREA",
        port_of_discharge="LOS ANGELES, USA",
        description_of_goods="ELECTRONIC COMPONENTS",
        documents_required=["COMMERCIAL INVOICE", "BILL OF LADING"],
    )


def make(engine: RuleEngine, bl: dict, lc: LCTerms, submitted=None):
    verdict = engine.verify(bl, lc, as_of=AS_OF)
    report = build_report(verdict, bl, lc, submitted_documents=submitted, as_of=AS_OF)
    return apply_narrative(report, TemplateNarrator())


class Test기획안_5_2_구성:
    """5.2 가 규정한 5개 구성이 전부 나와야 한다."""

    def test_요약에_확률과_심각도_분포가_담긴다(self, engine):
        bl = clean_bl()
        bl["on_board_date"] = "2026-05-20"  # 최종선적일 초과
        report = make(engine, bl, matching_lc())

        assert report.defect_probability > 0
        assert report.counts["critical"] >= 1
        assert report.risk_level == "높음"

    def test_리스크에_근거_조문이_붙는다(self, engine):
        bl = clean_bl()
        bl["on_board_date"] = "2026-05-20"
        report = make(engine, bl, matching_lc())

        assert report.risks
        assert all(r.source for r in report.risks), "근거 조문 없는 리스크가 있습니다"

    def test_체크리스트가_누락_서류를_잡는다(self, engine):
        report = make(
            engine, clean_bl(), matching_lc(),
            submitted=["Commercial Invoice"],  # BILL OF LADING 미제출
        )
        missing = [c for c in report.checklist if not c.done and "요구 서류" in c.label]
        assert any("BILL OF LADING" in c.label for c in missing)

    def test_수정_권고는_심각도_우선순위로_정렬된다(self, engine):
        bl = clean_bl()
        bl["on_board_date"] = "2026-05-20"       # critical
        bl["notify_party"] = None                 # warning
        report = make(engine, bl, matching_lc())

        labels = [r.severity_label for r in report.recommendations]
        assert labels == sorted(labels, key=lambda x: {"치명": 0, "경고": 1, "참고": 2}[x])
        assert [r.order for r in report.recommendations] == list(
            range(1, len(report.recommendations) + 1)
        )

    def test_예상_심사_결과가_채워진다(self, engine):
        report = make(engine, clean_bl(), matching_lc())
        assert report.outlook
        assert report.outlook_detail


class Test제시기한:
    def test_유효기일이_이르면_그쪽이_실질_기한이_된다(self, engine):
        lc = matching_lc()
        lc.expiry_date = "2026-05-20"  # 선적일(5/10)+21일=5/31 보다 이름
        report = make(engine, clean_bl(), lc)

        assert report.deadline.effective_due.isoformat() == "2026-05-20"
        assert report.deadline.is_overdue is True  # as_of 5/25

    def test_기한_경과는_예상_결과를_뒤집는다(self, engine):
        lc = matching_lc()
        lc.expiry_date = "2026-05-20"
        report = make(engine, clean_bl(), lc)
        assert "경과" in report.outlook

    def test_선적일과_유효기일이_모두_없으면_기한은_None(self, engine):
        bl = clean_bl()
        bl["on_board_date"] = None
        lc = matching_lc()
        lc.expiry_date = None
        report = make(engine, bl, lc)
        assert report.deadline is None


class Test미검사_항목:
    """검사하지 못한 항목을 감추면 '전부 검사했고 문제없다'로 읽힌다."""

    def test_평가불가_룰이_리포트에_실린다(self, engine):
        report = make(engine, clean_bl(), LCTerms())  # L/C 조건 대부분 없음
        assert report.unchecked, "평가불가 항목이 리포트에서 사라졌습니다"

    def test_미검사가_있으면_예상_결과에_단서가_붙는다(self, engine):
        report = make(engine, clean_bl(), LCTerms())
        assert "보증하지는 않습니다" in report.outlook_detail


class TestLLM_없이_동작:
    def test_템플릿_요약만으로_리포트가_완성된다(self, engine):
        report = make(engine, clean_bl(), matching_lc())
        assert report.headline
        assert report.narrative
        assert report.narrative_source == "template"

    def test_LLM이_실패해도_템플릿으로_떨어진다(self, engine):
        def broken(system: str, user: str) -> str:
            raise RuntimeError("API 한도 초과")

        verdict = engine.verify(clean_bl(), matching_lc(), as_of=AS_OF)
        report = build_report(verdict, clean_bl(), matching_lc(), as_of=AS_OF)
        report = apply_narrative(report, LLMNarrator(broken))

        assert report.headline, "LLM 실패 시 요약이 비었습니다"
        assert report.narrative

    def test_LLM은_수치를_만들지_않는다(self, engine):
        """LLM 에 넘기는 사실 목록에 리포트의 수치가 들어 있어야 한다."""
        from report.narrative import _render_facts

        bl = clean_bl()
        bl["on_board_date"] = "2026-05-20"
        report = make(engine, bl, matching_lc())
        facts = _render_facts(report)

        assert f"{report.defect_probability:.2f}" in facts
        assert str(report.counts) in facts


class TestPDF:
    def test_PDF가_생성되고_한글이_들어간다(self, engine, tmp_path):
        bl = clean_bl()
        bl["on_board_date"] = "2026-05-20"
        report = make(engine, bl, matching_lc(), submitted=["Commercial Invoice"])

        data = render_pdf(report)
        assert data.startswith(b"%PDF"), "PDF 헤더가 아닙니다"
        assert len(data) > 3000

        fitz = pytest.importorskip("fitz", reason="PyMuPDF 미설치")
        path = tmp_path / "r.pdf"
        path.write_bytes(data)
        doc = fitz.open(str(path))
        text = "".join(page.get_text() for page in doc)

        assert "선제 대응 서류 분석 리포트" in text
        assert "예상 심사 결과" in text
        # 근거 조문이 실제로 지면에 찍혔는지
        assert "UCP 600" in text
        # 한글이 깨지지 않았는지 (CID 폰트 미등록 시 공백/네모가 된다)
        korean = sum(1 for ch in text if "가" <= ch <= "힣")
        assert korean > 100, f"한글이 거의 없습니다({korean}자) — 폰트 문제로 보입니다"

    def test_미검사_항목이_PDF_부록에_실린다(self, engine, tmp_path):
        report = make(engine, clean_bl(), LCTerms())
        assert report.unchecked

        fitz = pytest.importorskip("fitz", reason="PyMuPDF 미설치")
        path = tmp_path / "r2.pdf"
        path.write_bytes(render_pdf(report))
        text = "".join(page.get_text() for page in fitz.open(str(path)))
        assert "검사하지 못한 항목" in text


class TestShareToken:
    """공유 토큰 자체의 계약. API 계층은 test_api.py 가 본다."""

    PAYLOAD = {"bl": {"bl_no": "HG290309"}, "lc": None}
    SECRET = b"test-secret"

    def test_왕복한다(self):
        from report import share

        token = share.encode(self.PAYLOAD, secret=self.SECRET)

        assert share.decode(token, secret=self.SECRET) == self.PAYLOAD

    def test_다른_비밀키로는_열리지_않는다(self):
        from report import share

        token = share.encode(self.PAYLOAD, secret=self.SECRET)

        with pytest.raises(share.ShareTokenError, match="서명"):
            share.decode(token, secret=b"other-secret")

    def test_버전이_다르면_거절한다(self):
        # 서명 방식을 바꿨을 때 옛 링크가 조용히 오해되지 않아야 한다.
        from report import share

        token = share.encode(self.PAYLOAD, secret=self.SECRET)
        _, packed, signature = token.split(".")

        with pytest.raises(share.ShareTokenError, match="버전"):
            share.decode(f"v0.{packed}.{signature}", secret=self.SECRET)

    def test_서명을_압축_해제보다_먼저_본다(self):
        # 반대 순서면 서명 없는 입력이 zlib 에 먼저 들어간다.
        from report import share

        bomb = share._b64encode(zlib.compress(b"\x00" * 10_000_000))

        with pytest.raises(share.ShareTokenError, match="서명"):
            share.decode(f"v1.{bomb}.{share._b64encode(b'x' * 32)}",
                         secret=self.SECRET)

    def test_너무_긴_입력은_발급하지_않는다(self):
        # 프록시가 URL 을 잘라 조용히 깨지는 것보다 거절이 낫다.
        from report import share

        # 반복 문자열은 zlib 이 뭉개 버려 한계에 닿지 않는다. 해시로
        # 압축되지 않는 내용을 만든다.
        import hashlib

        huge = {
            "bl": {
                f"field_{i}": hashlib.sha256(str(i).encode()).hexdigest()
                for i in range(400)
            }
        }

        with pytest.raises(share.ShareTokenTooLarge, match="너무 깁니다"):
            share.encode(huge, secret=self.SECRET)

    def test_비밀키가_없으면_프로세스마다_임시값을_쓴다(self, monkeypatch):
        # 고정 기본값을 두면 소스를 읽은 누구나 토큰을 위조할 수 있다.
        from report import share

        monkeypatch.delenv(share.SECRET_ENV, raising=False)
        monkeypatch.setattr(share, "_process_secret", None)

        assert share.secret_is_ephemeral()
        assert share.share_secret() == share.share_secret()

    def test_환경변수를_주면_고정된다(self, monkeypatch):
        from report import share

        monkeypatch.setenv(share.SECRET_ENV, "고정키")

        assert not share.secret_is_ephemeral()
        assert share.share_secret() == "고정키".encode("utf-8")

    def test_만료_시각을_읽을_수_있다(self):
        from report import share

        token = share.encode(self.PAYLOAD, ttl_seconds=3600, now=1000,
                             secret=self.SECRET)

        assert share.expires_at(token) == 4600

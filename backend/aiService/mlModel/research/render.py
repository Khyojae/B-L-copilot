"""서류 세트 렌더링 — 라벨 채널과 피처 채널이 공유하는 중립 모듈 (계획서 8단계 Task 2).

원래 `synth/review.py` 안에 있던 `render_document_set()` 을 이리로 옮긴다.

★★ 왜 중립 위치가 필요한가 (채널 독립, 설계서 1절) ★★
라벨 채널(`synth/review.py`, 채널 B)은 하자 주입 이후의 **진실** 선적을
렌더링해 은행 심사 프롬프트를 만든다. 피처 채널(`llm_features.py` 이 쓰는,
`dataset.py` pass 1a 가 만드는 텍스트)은 룰엔진과 똑같이 **관측값**
(`synth/extraction_view.py` 의 OCR 훼손 사본)을 렌더링한다 — 진실이 아니라
룰이 실제로 보는 것과 같은 입력을 LLM 도 보게 하기 위해서다.

두 채널이 이 렌더링 함수 자체는 공유하되(문서를 텍스트로 바꾸는 로직은
채널 중립적이다), **어떤 선적 사본을 넣느냐**만 서로 다르다. 만약 피처 채널이
`synth/review.py` 를 직접 import 해서 이 함수를 가져다 썼다면, "피처 채널이
라벨 모듈을 import 한다"는 채널 결합 냄새가 생긴다 — `tests/test_no_leakage.py`
가 정확히 이런 류의 import 를 금지한다(채널 A 모듈 목록에 `llm_features` 포함).
그래서 이 함수를 review.py 도 아니고 extraction_view.py 도 아닌, 어느 채널도
소유하지 않는 이 모듈에 둔다.

⚠️ 렌더링 텍스트 자체는 절대 바꾸지 않는다. `review.PROMPT_VERSION` /
`review.content_hash()` / `llm_features` 의 캐시 키가 전부 이 함수의 출력
문자열에 의존한다 — 문구를 한 글자라도 바꾸면 기존 캐시(저장소에 커밋된
재현성 아티팩트)가 전부 무효화된다.
"""

from __future__ import annotations

from f3_research.synth.generator import SynthShipment


def render_document_set(shipment: SynthShipment) -> str:
    """선적 사본을 UCP600/ISBP 심사(또는 LLM 피처 추출)용 서류 세트 텍스트로 렌더링한다.

    ★★ 라벨 누수 차단 불변식 (설계서 5.5 "계약") ★★
    `injected_defects`, `covered_by_rule`, 룰 코드, 룰 발화 벡터는 여기 절대
    넣지 않는다 — 이 함수의 반환값이 그대로 채널 B 프롬프트에 들어간다. 여기
    나열된 필드는 전부 B/L·L/C·상업송장·포장명세서에 실제로 적히는 값뿐이다.

    호출부가 `shipment` 로 **진실**(review.py, 채널 B)을 줄지 **관측값**
    (`extraction_view.extraction_view()` 사본, 채널 A/LLM 피처)을 줄지 결정한다
    — 이 함수 자체는 어느 쪽인지 모른다(위 모듈 docstring 참고).
    """
    if shipment.lc_present:
        lc_section = (
            f":47A: 부가조건: {shipment.lc_47a_text or '(없음)'}\n"
            f":46A: 필요서류 종수: {shipment.lc_required_doc_count}\n"
            f":31D: 유효기일: {shipment.lc_expiry_date}\n"
            f":44F: 양륙항: {shipment.lc_port_of_discharge}\n"
            f":48: 제시기간: {shipment.lc_presentation_period_days}일\n"
            f"분할선적 허용 여부: {shipment.lc_partial_shipment_allowed}\n"
            f"환적 허용 여부: {shipment.lc_transshipment_allowed}\n"
            f"금액 허용오차: {shipment.lc_amount_tolerance_pct}%\n"
            f"양도가능 여부: {shipment.lc_is_transferable}\n"
            f"특수조건 존재 여부: {shipment.lc_has_special_clause}\n"
        )
    else:
        lc_section = "(신용장 없음 — 무신용장 거래)\n"

    return (
        "=== 선하증권(Bill of Lading) ===\n"
        f"Shipper: {shipment.shipper}\n"
        f"Consignee: {shipment.consignee}\n"
        f"Notify Party: {shipment.notify_party}\n"
        f"Port of Loading: {shipment.port_of_loading}\n"
        f"Port of Discharge: {shipment.port_of_discharge}\n"
        f"Vessel / Voyage No: {shipment.vessel} / {shipment.voyage_no}\n"
        f"Goods Description: {shipment.goods_description}\n"
        f"Package Quantity: {shipment.package_qty}\n"
        f"Gross Weight: {shipment.gross_weight_kg} KG\n"
        f"Number of Original B/L Issued: {shipment.original_bl_count}\n"
        f"B/L Issue Date: {shipment.bl_issue_date}\n"
        f"On Board Date: {shipment.onboard_date}\n"
        "\n=== 신용장(Letter of Credit) 조건 ===\n"
        f"{lc_section}"
        "\n=== 상업송장(Commercial Invoice) ===\n"
        f"Consignee: {shipment.invoice_consignee}\n"
        f"Goods Description: {shipment.invoice_goods_description}\n"
        f"Unit Price: USD {shipment.unit_price_usd}\n"
        f"Invoice Amount: USD {shipment.invoice_amount_usd}\n"
        "\n=== 포장명세서(Packing List) ===\n"
        f"Package Quantity (sum): {shipment.packing_list_qty_sum}\n"
        f"Weight (sum): {shipment.packing_list_weight_sum} KG\n"
        "\n=== 제시(presentation) 정보 ===\n"
        f"Presentation Date: {shipment.presentation_date}\n"
    )

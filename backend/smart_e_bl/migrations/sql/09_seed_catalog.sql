-- ============================================================================
-- 카탈로그 초기 적재
-- 근거: 기획안 5.1 출력 필드 표, 5.3 룰엔진 카탈로그
--
-- 여기 담는 것은 기획안에 명시적으로 열거된 항목뿐이다.
-- 룰 판정식(expression)과 조문 스니펫(authority_snippet)은 자리만 잡아 두었고,
-- 실제 값은 F3 구현 시 채운다. README 의 "채워야 하는 것" 절을 참고.
-- ============================================================================

INSERT INTO rule_catalog_version (version, note, is_current) VALUES
  ('2026.08.1', '초기 카탈로그. 기획안 5.3 표의 룰 20종 골격', true);

-- ---------------------------------------------------------------------------
-- field_definition — 기획안 5.1 "출력 — B/L 초안 필드" 표 그대로
-- ---------------------------------------------------------------------------
INSERT INTO field_definition (code, doc_type, field_group, label_ko, label_en, data_type, source_priority, is_required) VALUES
  -- 당사자 (주 출처: L/C > SI)
  ('BL.SHIPPER',              'BL_DRAFT', '당사자',    '송하인',        'Shipper',                'text',   '{LC_MT700,SI}', true),
  ('BL.CONSIGNEE',            'BL_DRAFT', '당사자',    '수하인',        'Consignee',              'text',   '{LC_MT700,SI}', true),
  ('BL.NOTIFY_PARTY',         'BL_DRAFT', '당사자',    '통지처',        'Notify Party',           'text',   '{LC_MT700,SI}', false),
  ('BL.CARRIER',              'BL_DRAFT', '당사자',    '운송인',        'Carrier',                'text',   '{LC_MT700,SI}', true),
  -- 식별번호 (주 출처: SI > L/C)
  ('BL.BL_NO',                'BL_DRAFT', '식별번호',  'B/L 번호',      'B/L No.',                'text',   '{SI,LC_MT700}', true),
  ('BL.BOOKING_NO',           'BL_DRAFT', '식별번호',  '부킹 번호',     'Booking No.',            'text',   '{SI}',          false),
  ('BL.LC_NO',                'BL_DRAFT', '식별번호',  'L/C 번호',      'L/C No.',                'text',   '{SI,LC_MT700}', false),
  ('BL.CARGO_CONTROL_NO',     'BL_DRAFT', '식별번호',  '화물관리번호',  'Cargo Control No.',      'text',   '{SI}',          false),
  -- 운송구간 (주 출처: L/C(:44E:/:44F:) > SI)
  ('BL.PLACE_OF_RECEIPT',     'BL_DRAFT', '운송구간',  '수취지',        'Place of Receipt',       'code',   '{LC_MT700,SI}', false),
  ('BL.PORT_OF_LOADING',      'BL_DRAFT', '운송구간',  '선적항',        'Port of Loading',        'code',   '{LC_MT700,SI}', true),
  ('BL.PORT_OF_DISCHARGE',    'BL_DRAFT', '운송구간',  '양륙항',        'Port of Discharge',      'code',   '{LC_MT700,SI}', true),
  ('BL.PLACE_OF_DELIVERY',    'BL_DRAFT', '운송구간',  '인도지',        'Place of Delivery',      'code',   '{LC_MT700,SI}', false),
  ('BL.VESSEL_VOYAGE',        'BL_DRAFT', '운송구간',  '선명·항차',     'Vessel/Voyage',          'text',   '{SI}',          true),
  -- 화물 (주 출처: 포장명세서 > 상업송장)
  ('BL.MARKS_AND_NUMBERS',    'BL_DRAFT', '화물',      '화인·번호',     'Marks & Numbers',        'text',   '{PACKING_LIST,COMMERCIAL_INVOICE}', false),
  ('BL.NO_OF_PACKAGES',       'BL_DRAFT', '화물',      '포장 수',       'No. of Packages',        'number', '{PACKING_LIST,COMMERCIAL_INVOICE}', true),
  ('BL.DESCRIPTION_OF_GOODS', 'BL_DRAFT', '화물',      '화물 명세',     'Description of Goods',   'text',   '{PACKING_LIST,COMMERCIAL_INVOICE}', true),
  ('BL.HS_CODE',              'BL_DRAFT', '화물',      'HS 코드',       'HS Code',                'code',   '{COMMERCIAL_INVOICE}', false),
  ('BL.GROSS_WEIGHT',         'BL_DRAFT', '화물',      '총중량',        'Gross Weight',           'number', '{PACKING_LIST}', true),
  ('BL.MEASUREMENT',          'BL_DRAFT', '화물',      '용적',          'Measurement',            'number', '{PACKING_LIST}', false),
  -- 컨테이너 (주 출처: SI)
  ('BL.CONTAINER_NO',         'BL_DRAFT', '컨테이너',  '컨테이너 번호', 'Container No.',          'code',   '{SI}', false),
  ('BL.SEAL_NO',              'BL_DRAFT', '컨테이너',  '실 번호',       'Seal No.',               'text',   '{SI}', false),
  ('BL.CONTAINER_TYPE_QTY',   'BL_DRAFT', '컨테이너',  '컨테이너 유형·수량', 'Container Type/Qty', 'text',  '{SI}', false),
  -- 조건·발행 (주 출처: L/C > SI)
  ('BL.FREIGHT_TERMS',        'BL_DRAFT', '조건·발행', '운임 조건',     'Freight Terms',          'text',   '{LC_MT700,SI}', true),
  ('BL.INCOTERMS',            'BL_DRAFT', '조건·발행', '가격 조건',     'Incoterms',              'code',   '{LC_MT700,SI}', false),
  ('BL.NO_OF_ORIGINAL_BL',    'BL_DRAFT', '조건·발행', '원본 통수',     'No. of Original B/L',    'number', '{LC_MT700,SI}', true),
  ('BL.PLACE_OF_ISSUE',       'BL_DRAFT', '조건·발행', '발행지',        'Place of Issue',         'code',   '{LC_MT700,SI}', true),
  ('BL.DATE_OF_ISSUE',        'BL_DRAFT', '조건·발행', '발행일',        'Date of Issue',          'date',   '{LC_MT700,SI}', true),
  ('BL.ONBOARD_DATE',         'BL_DRAFT', '조건·발행', '본선적재일',    'Shipped on Board Date',  'date',   '{SI}', true),

  -- L/C (MT700) — 기획안 5.1 필드 태그 파서 대상
  ('LC.20',   'LC_MT700', 'L/C', 'L/C 번호',        'Documentary Credit Number',   'text',   '{LC_MT700}', true),
  ('LC.31D',  'LC_MT700', 'L/C', '유효기일·장소',   'Date and Place of Expiry',    'date',   '{LC_MT700}', true),
  ('LC.44C',  'LC_MT700', 'L/C', '최종 선적일',     'Latest Date of Shipment',     'date',   '{LC_MT700}', false),
  ('LC.44E',  'LC_MT700', 'L/C', '선적항',          'Port of Loading',             'code',   '{LC_MT700}', false),
  ('LC.44F',  'LC_MT700', 'L/C', '양륙항',          'Port of Discharge',           'code',   '{LC_MT700}', false),
  ('LC.45A',  'LC_MT700', 'L/C', '상품 명세',       'Description of Goods',        'text',   '{LC_MT700}', false),
  ('LC.46A',  'LC_MT700', 'L/C', '요구 서류',       'Documents Required',          'text',   '{LC_MT700}', false),
  ('LC.47A',  'LC_MT700', 'L/C', '추가 조건',       'Additional Conditions',       'text',   '{LC_MT700}', false),
  ('LC.48',   'LC_MT700', 'L/C', '제출 기간',       'Period for Presentation',     'number', '{LC_MT700}', false),

  -- 상업송장
  ('INV.DESCRIPTION_OF_GOODS','COMMERCIAL_INVOICE', '화물', '상품 명세', 'Description of Goods', 'text',   '{COMMERCIAL_INVOICE}', true),
  ('INV.QUANTITY',            'COMMERCIAL_INVOICE', '화물', '수량',      'Quantity',             'number', '{COMMERCIAL_INVOICE}', true),
  ('INV.UNIT_PRICE',          'COMMERCIAL_INVOICE', '화물', '단가',      'Unit Price',           'number', '{COMMERCIAL_INVOICE}', false),
  ('INV.AMOUNT',              'COMMERCIAL_INVOICE', '화물', '금액',      'Amount',               'number', '{COMMERCIAL_INVOICE}', true),

  -- 포장명세서
  ('PL.PACKAGE_COUNT',        'PACKING_LIST', '화물', '포장 수',   'No. of Packages', 'number', '{PACKING_LIST}', true),
  ('PL.GROSS_WEIGHT',         'PACKING_LIST', '화물', '총중량',    'Gross Weight',    'number', '{PACKING_LIST}', true),
  ('PL.NET_WEIGHT',           'PACKING_LIST', '화물', '순중량',    'Net Weight',      'number', '{PACKING_LIST}', false),
  ('PL.MEASUREMENT',          'PACKING_LIST', '화물', '용적',      'Measurement',     'number', '{PACKING_LIST}', false);

-- ---------------------------------------------------------------------------
-- rule — 기획안 5.3 계층 A 룰엔진 카탈로그 표의 20종
--
-- authority_snippet 은 UCP600·ISBP 조문 원문이 들어갈 자리다. 두 문서는 ICC 저작물이라
-- 원문을 임의로 채워 넣지 않았다. 라이선스 확보 후 갱신해야 F4 리포트 ②항목별 리스크의
-- "근거 조문 원문"이 성립한다(기획안 5.4).
-- expression 은 기획안 5.3 이 제시한 내부 DSL 형태의 초안이다.
-- ---------------------------------------------------------------------------
INSERT INTO rule (rule_code, catalog_version, title, authority_ref, authority_snippet, severity, target_field_codes, expression, is_llm_assisted, message_template, remediation_template, requires_lc, is_active) VALUES
  ('R-UCP-14C', '2026.08.1', '본선적재일로부터 21일 초과 제출', 'UCP600 14(c)', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.ONBOARD_DATE}', 'bl.onboard_date + 21d < presentation_date', false,
   '본선적재일({actual})로부터 21일을 넘겨 제출될 예정입니다.', '제출 일정을 앞당기거나 은행과 기한을 협의하세요.', true, true),
  ('R-UCP-14D', '2026.08.1', '서류 간·서류 내 정보 상충', 'UCP600 14(d)', '(조문 원문 미적재)', 'CRITICAL',
   '{}', 'exists(field_value where conflict_flag)', false,
   '동일 정보가 서류마다 다르게 기재되어 있습니다: {field}', '출처 서류를 확인해 값을 일치시키세요.', true, true),
  ('R-UCP-20A', '2026.08.1', '운송인 명칭·서명 자격 기재', 'UCP600 20(a)(i)', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.CARRIER}', 'bl.carrier is present and bl.signature_capacity in (carrier, master, agent)', false,
   '운송인 명칭 또는 서명 자격 표시가 없습니다.', '운송인명과 서명 자격(운송인·선장·대리인)을 기재하세요.', true, true),
  ('R-UCP-20B', '2026.08.1', '본선적재 표기와 일자 존재', 'UCP600 20(a)(ii)', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.ONBOARD_DATE}', 'bl.onboard_date is present', false,
   '본선적재 표기(on board notation) 또는 일자가 없습니다.', 'on board notation 과 적재일을 기재하세요.', true, true),
  ('R-UCP-20C', '2026.08.1', 'L/C 요구 선적항·양륙항 표시', 'UCP600 20(a)(iii)', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.PORT_OF_LOADING,BL.PORT_OF_DISCHARGE}', 'bl.port_of_loading is present and bl.port_of_discharge is present', false,
   'L/C 가 요구한 항구 표시가 누락되었습니다.', '선적항·양륙항을 B/L 에 명시하세요.', true, true),
  ('R-UCP-20D', '2026.08.1', '원본 통수(full set) 일치', 'UCP600 20(a)(iv)', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.NO_OF_ORIGINAL_BL}', 'bl.no_of_original_bl == lc.required_original_count', false,
   '원본 통수({actual})가 요구 통수({expected})와 다릅니다.', '원본 통수를 L/C 요구와 일치시키세요.', true, true),
  ('R-UCP-27',  '2026.08.1', '무고장(clean) 여부', 'UCP600 27', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.DESCRIPTION_OF_GOODS}', 'not contains_defect_clause(bl.description_of_goods)', true,
   '포장·화물 하자 문언이 발견되었습니다.', '하자 문언을 제거하거나 무고장 B/L 을 재발급받으세요.', true, true),
  ('R-UCP-31',  '2026.08.1', '분할선적 금지 위반 정황', 'UCP600 31', '(조문 원문 미적재)', 'WARNING',
   '{BL.VESSEL_VOYAGE}', 'lc.partial_shipment_prohibited and count(distinct bl.voyage) > 1', false,
   '분할선적 금지 조건에서 분할 정황이 감지되었습니다.', '단일 항차로 통합하거나 L/C 조건 변경을 검토하세요.', true, true),
  ('R-UCP-30A', '2026.08.1', 'about/approximately 시 ±10% 검사', 'UCP600 30(a)', '(조문 원문 미적재)', 'WARNING',
   '{INV.AMOUNT,INV.QUANTITY}', 'lc.has_about and abs(actual - expected) / expected > 0.10', false,
   '허용 범위(±10%)를 벗어났습니다.', '금액·수량을 허용 범위 안으로 조정하세요.', true, true),
  ('R-UCP-30B', '2026.08.1', '포장 단위 미지정 시 ±5% 검사', 'UCP600 30(b)', '(조문 원문 미적재)', 'WARNING',
   '{BL.NO_OF_PACKAGES}', 'not lc.has_packaging_unit and abs(actual - expected) / expected > 0.05', false,
   '수량 허용 범위(±5%)를 벗어났습니다.', '수량을 허용 범위 안으로 조정하세요.', true, true),
  ('R-UCP-18C', '2026.08.1', '송장 상품 명세와 L/C 부합', 'UCP600 18(c)', '(조문 원문 미적재)', 'CRITICAL',
   '{INV.DESCRIPTION_OF_GOODS,LC.45A}', 'matches(inv.description_of_goods, lc.45a)', true,
   '송장 상품 명세가 L/C(:45A:) 명세와 부합하지 않습니다.', 'L/C 문언과 동일한 표현으로 명세를 맞추세요.', true, true),
  ('R-LC-31D',  '2026.08.1', 'L/C 유효기일 경과', 'MT700 :31D:', '(조문 원문 미적재)', 'CRITICAL',
   '{LC.31D}', 'presentation_date > lc.31d', false,
   'L/C 유효기일({expected})이 경과했거나 잔여일이 부족합니다.', '유효기일 내 제출하거나 조건 변경을 요청하세요.', true, true),
  ('R-LC-48',   '2026.08.1', 'L/C 서류 제출 기간 초과', 'MT700 :48:', '(조문 원문 미적재)', 'CRITICAL',
   '{LC.48,BL.ONBOARD_DATE}', 'presentation_date > bl.onboard_date + lc.48', false,
   '제출 기간({expected}일)을 초과했습니다.', '제출 일정을 앞당기세요.', true, true),
  ('R-LC-44EF', '2026.08.1', '선적항·양륙항 L/C 지정 일치', 'MT700 :44E:/:44F:', '(조문 원문 미적재)', 'CRITICAL',
   '{BL.PORT_OF_LOADING,BL.PORT_OF_DISCHARGE,LC.44E,LC.44F}',
   'bl.port_of_loading == lc.44e and bl.port_of_discharge == lc.44f', false,
   'B/L 항구({actual})가 L/C 지정({expected})과 다릅니다.', 'L/C 지정 항구로 정정하세요.', true, true),
  ('R-LC-46A',  '2026.08.1', 'L/C 요구 서류 구비', 'MT700 :46A:', '(조문 원문 미적재)', 'CRITICAL',
   '{LC.46A}', 'all_required_documents_present(lc.46a)', false,
   'L/C 가 요구한 서류가 누락되었습니다: {missing}', '누락 서류를 준비해 업로드하세요.', true, true),
  ('R-LC-47A',  '2026.08.1', '추가 조건 미충족 판별', 'MT700 :47A:', '(조문 원문 미적재)', 'WARNING',
   '{LC.47A}', 'llm_condition_satisfied(lc.47a)', true,
   '추가 조건 중 미충족 항목이 있습니다.', '해당 조건의 요구 사항을 확인하세요.', true, true),
  ('R-XREF-QTY', '2026.08.1', '포장 수량 합계 일치', '서류 간 정합성', '(내부 정합성 규칙)', 'CRITICAL',
   '{BL.NO_OF_PACKAGES,PL.PACKAGE_COUNT}', 'bl.no_of_packages == sum(pl.package_count)', false,
   'B/L 포장 수({actual})가 포장명세서 합계({expected})와 다릅니다.', '수량을 재확인해 일치시키세요.', false, true),
  ('R-XREF-WGT', '2026.08.1', '총중량 편차 검사', '서류 간 정합성', '(내부 정합성 규칙)', 'WARNING',
   '{BL.GROSS_WEIGHT,PL.GROSS_WEIGHT}', 'abs(bl.gross_weight - pl.gross_weight) / pl.gross_weight > 0.05', false,
   '총중량 편차가 허용치를 넘습니다.', '계량 기준을 확인하고 중량을 맞추세요.', false, true),
  ('R-FMT-CTR', '2026.08.1', '컨테이너 번호 체크디지트', 'ISO 6346', '(ISO 6346 체크디지트 산식)', 'WARNING',
   '{BL.CONTAINER_NO}', 'iso6346_check_digit_valid(bl.container_no)', false,
   '컨테이너 번호({actual})의 체크디지트가 유효하지 않습니다.', '컨테이너 번호를 재확인하세요.', false, true),
  ('R-FMT-DATE', '2026.08.1', '일자 논리 순서', '내부 정합성', '(내부 정합성 규칙)', 'CRITICAL',
   '{BL.DATE_OF_ISSUE,BL.ONBOARD_DATE}', 'bl.onboard_date <= bl.date_of_issue', false,
   '일자 순서가 어긋납니다(발행일 {actual} < 적재일 {expected}).', '발행일·적재일·출항일 순서를 확인하세요.', false, true);


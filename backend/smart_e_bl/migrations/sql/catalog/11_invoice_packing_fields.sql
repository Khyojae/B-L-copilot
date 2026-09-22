-- ============================================================================
-- 상업송장·포장명세서 필드 정의 보강 (마이그레이션 0004)
--
-- 09_seed_catalog.sql 은 기획안 5.1 표에 열거된 항목만 담아 상업송장 4 ·
-- 포장명세서 4 코드로 그쳤다. 그런데 aiService 가 두 서류에서 뽑는 필드
-- (ocr/doc_types.py DocumentSpec.fields) 와 서류 간 정합성 룰
-- (ruleEngine/cross_rules.yaml — 송하인=매도인, 수하인=매수인, 송장번호·
-- L/C 번호·인코텀즈 일치 등)이 쓰는 필드는 그보다 많다. 코드가 없으면
-- 워커가 그 값을 "카탈로그 밖"으로 버려서, 추출은 됐는데 서류 간 검사는
-- "세트에 없는 서류"로 빠진다.
--
-- is_required 는 aiService DocumentSpec.critical 과 맞춘다(그 필드가 비면
-- aiService 가 초안 자체를 '필수 확인'으로 올리는 필드).
-- 재실행 안전: 이미 있는 코드는 건드리지 않는다.
-- ============================================================================

INSERT INTO field_definition (code, doc_type, field_group, label_ko, label_en, data_type, source_priority, is_required) VALUES
  -- 상업송장
  ('INV.INVOICE_NO',   'COMMERCIAL_INVOICE', '식별번호',  '송장 번호',   'Invoice No.',   'text', '{COMMERCIAL_INVOICE}', true),
  ('INV.INVOICE_DATE', 'COMMERCIAL_INVOICE', '조건·발행', '송장 일자',   'Invoice Date',  'date', '{COMMERCIAL_INVOICE}', false),
  ('INV.SELLER',       'COMMERCIAL_INVOICE', '당사자',    '매도인',      'Seller',        'text', '{COMMERCIAL_INVOICE}', false),
  ('INV.BUYER',        'COMMERCIAL_INVOICE', '당사자',    '매수인',      'Buyer',         'text', '{COMMERCIAL_INVOICE}', true),
  ('INV.INCOTERMS',    'COMMERCIAL_INVOICE', '조건·발행', '인코텀즈',    'Incoterms',     'code', '{COMMERCIAL_INVOICE}', false),
  ('INV.LC_NO',        'COMMERCIAL_INVOICE', '식별번호',  'L/C 번호',    'L/C No.',       'text', '{COMMERCIAL_INVOICE}', false),

  -- 포장명세서
  ('PL.INVOICE_NO',           'PACKING_LIST', '식별번호',  '송장 번호',   'Invoice No.',          'text', '{PACKING_LIST}', true),
  ('PL.PACKING_DATE',         'PACKING_LIST', '조건·발행', '작성 일자',   'Packing Date',         'date', '{PACKING_LIST}', false),
  ('PL.SELLER',               'PACKING_LIST', '당사자',    '매도인',      'Seller',               'text', '{PACKING_LIST}', false),
  ('PL.BUYER',                'PACKING_LIST', '당사자',    '매수인',      'Buyer',                'text', '{PACKING_LIST}', true),
  ('PL.DESCRIPTION_OF_GOODS', 'PACKING_LIST', '화물',      '상품 명세',   'Description of Goods', 'text', '{PACKING_LIST}', false),
  ('PL.MARKS',                'PACKING_LIST', '화물',      '화인',        'Marks & Numbers',      'text', '{PACKING_LIST}', false)
ON CONFLICT (code) DO NOTHING;

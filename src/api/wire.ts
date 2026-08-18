/**
 * aiService 가 실제로 내려주는 JSON 의 모양 (= "wire 타입")
 *
 * ⚠ 이 파일의 타입은 **도메인 타입이 아닙니다.**
 *   `types/domain.ts` 는 우리 화면이 쓰는 말이고, 여기 있는 건 백엔드가 쓰는 말입니다.
 *   둘이 다르기 때문에 `adapters.ts` 가 번역을 합니다.
 *   백엔드 응답이 바뀌면 **이 파일만** 고치면 되도록 분리해 둔 것입니다.
 *
 * 근거: docs/ai-service/f3-defect-prediction.md 의 `POST /verify` 응답 예시
 *       (백엔드 저장소 C:\Smart_e-BL_Backend)
 *
 * 용어: "wire" 는 네트워크 선을 타고 오가는 원본 데이터라는 뜻입니다.
 */

/** 백엔드의 심각도는 **소문자**입니다. 우리 화면은 'Critical' 처럼 대문자로 시작합니다. */
export type WireSeverity = 'critical' | 'warning' | 'info';

/** 위반 1건. 백엔드는 "위반한 룰"만 배열로 내려줍니다 (통과한 룰은 안 옵니다). */
export interface WireViolation {
  rule_id: string;
  severity: WireSeverity;
  /** '치명' · '경고' · '참고' — 백엔드가 만든 한글 라벨. 우리는 SEVERITY 상수를 쓰므로 안 씁니다 */
  severity_label: string;
  title: string;
  message: string;
  /** 우리 쪽 Verdict.target_fields 에 해당 */
  fields: string[];
  /** 조문 근거. 예: "UCP 600 Art.20(a)(ii)" */
  source: string;
  /** 수정 권고. 우리 쪽 Verdict.action_hint 에 해당 */
  remedy: string;
  /** 룰이 실제로 본 값. 예: { bl: "SHANGHAI", lc: "BUSAN" } */
  observed: Record<string, string | null>;
}

/**
 * 평가하지 **못한** 룰.
 *
 * 입력이 비어 있거나 파싱에 실패해서 판단 자체를 못 한 경우입니다.
 * "통과"가 아닙니다 — 화면에서 감추면 사용자가 '검사했고 문제없다'로 읽습니다.
 */
export interface WireSkippedRule {
  rule_id: string;
  title: string;
  reason: string;
}

/** 어떤 룰 카탈로그로 판정했는지. 판정 재현성용 (기획안 §5.8) */
export interface WireCatalog {
  version: string;
  /** 카탈로그 내용의 sha256 앞 12자 */
  digest: string;
  /** "v1+ab12cd34ef56" 형태로 합쳐둔 것 */
  label: string;
}

export interface WireVerdict {
  /** 확률을 누가 냈는지. "rules-v1" = 룰 가중치 합산 */
  model: string;
  catalog: WireCatalog | null;
  /** 룰 가중치 합. **확률이 아니라 위험 점수에 가깝습니다** */
  defect_probability: number;
  evaluated_count: number;
  skipped_count: number;
  counts: Record<WireSeverity, number>;
  has_critical: boolean;
  /** 심각도 내림차순 → 가중치 내림차순으로 이미 정렬돼 있습니다 */
  violations: WireViolation[];
  skipped: WireSkippedRule[];
}

export interface WirePrediction {
  probability: number;
  /**
   * "xgboost-v1" 이면 학습된 모델,
   * **"rules-v1" 이면 모델이 아니라 룰 가중치**입니다 (모델 미적재·예측 실패 시).
   * 이걸 학습 모델의 확률로 표기하면 안 됩니다.
   */
  model: string;
  is_defect: boolean;
  threshold: number;
}

export interface WireVerifyResponse {
  /** 백엔드는 bl.bl_no 를 그대로 돌려줍니다. 우리 shipment_id 와는 다른 값입니다 */
  shipment_id: string | null;
  verdict: WireVerdict;
  prediction: WirePrediction;
}

/** `POST /verify` 요청 본문 */
export interface WireVerifyRequest {
  /** B/L 필드. { field_name: value } 형태의 평범한 객체 */
  bl: Record<string, string>;
  /** 신용장 조건(MT700). 없으면 서류 내부 정합성만 검사합니다 */
  lc?: Record<string, string>;
  /** 제시기간 계산 기준 시각. 시연·테스트에서 결과를 고정하려면 넣습니다 */
  as_of?: string;
}

// ─────────────────────────────────────────────
// F1 인테이크 — `/extract`, `/extract/pdf` 등의 응답
//
// 근거: docs/ai-service/f1-intake.md "공통 응답 — 초안 구조"
//       (다섯 개 엔드포인트가 모두 같은 모양을 돌려줍니다)
// ─────────────────────────────────────────────

/** 추출된 필드 1개. 이름이 우리 쪽 `field_name` 이 아니라 `name` 입니다 */
export interface WireDraftField {
  name: string;
  /** 한국어 라벨. 예: "B/L 번호". 우리는 자체 라벨을 쓰므로 안 씁니다 */
  label: string;
  /** 추출 실패면 null */
  value: string | null;
  /** 값이 없으면 null. 있으면 0.0~1.0 */
  confidence: number | null;
  /** 값을 어떻게 찾았는지: 'region'(좌표) · 'anchor'(항목명 근접) · 'llm' · null */
  source: string | null;
  /**
   * 백엔드가 매긴 신뢰도 4등급 — **소문자**입니다.
   * 'confirmed' | 'recommended' | 'required' | 'undetected'
   * (우리 화면의 ConfidenceGrade 는 CONFIRMED·ADVISORY·REQUIRED·NOT_FOUND 로
   *  이름이 다릅니다. 지금은 화면이 bbox·신뢰도로 직접 등급을 매기므로 안 씁니다)
   */
  grade: string;
  grade_label: string;
  /** 검증에 반드시 필요한 필드인지 */
  is_critical: boolean;
  needs_review: boolean;
  /** 'missing' · 'low_confidence' · 'label_echoed' 등. 없으면 null */
  review_reason: string | null;
  review_message: string | null;
}

/**
 * 초안 1건.
 *
 * ⚠ **필드 좌표(bbox)가 없습니다.** 백엔드는 값·신뢰도·등급만 돌려주고
 *   "원본의 어디에서 뽑았는지"는 응답에 담지 않습니다. 그래서 S3 뷰어의
 *   하이라이트는 실제 추출 결과에는 아직 붙일 수 없습니다 (adapters.ts 참고).
 */
export interface WireDraftResponse {
  image_id: string;
  /** '선하증권' | '상업송장' | '포장명세서' | '미상' */
  form_type: string;
  /** 어느 경로로 읽었는지: 'json' | 'image' | 'pdf-text' | 'pdf-ocr' | 'excel' | 'email-*' */
  source: string;
  ocr_mean_confidence: number;
  processing_time_ms: number | null;
  /** 값이 채워진 필드 비율 0.0~1.0 */
  completeness: number;
  /** 핵심 필드가 다 찼는지. false 면 검증 결과가 '값 없음' 하자로 도배됩니다 */
  is_ready_for_verification: boolean;
  review_required_count: number;
  /** 등급별 필드 수. 예: { confirmed: 0, recommended: 3, required: 6, undetected: 6 } */
  grades: Record<string, number>;
  /**
   * '필수 확인' 등급이라 검증 실행을 막아야 하는 필드 이름들.
   * M-1(검증 실행 버튼 활성 조건)의 답이 여기 있습니다 — 백엔드가 이미
   * 판단해서 내려줍니다. VerifyBar 를 여기에 붙일지는 팀 확정 후에.
   */
  blocking_fields: string[];
  /** 판정 보류 비율 (0.0~1.0) */
  hold_ratio: number;
  fields: WireDraftField[];
}

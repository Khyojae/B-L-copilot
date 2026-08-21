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

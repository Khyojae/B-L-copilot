/**
 * 백엔드의 말(`wire.ts`) → 우리 화면의 말(`types/domain.ts`) 번역기.
 *
 * 왜 번역이 필요한가: 두 팀이 각자 정한 이름·모양이 다릅니다.
 * 예) 백엔드 `remedy` = 우리 `action_hint`, 백엔드 `"critical"` = 우리 `'Critical'`.
 *
 * ⚠ 번역기의 원칙 — **없는 값을 지어내지 않습니다** (규약 §2.4).
 *   백엔드가 안 주는 것은 빈 값으로 두고, 아래 "백엔드가 아직 안 주는 것"에
 *   적어둡니다. 그럴듯한 값을 채워 넣으면 화면이 거짓말을 하게 됩니다.
 *
 * ── 백엔드가 아직 안 주는 것 (2026-08-15 기준) ──
 *   · Verdict.verdict_id   → 없음. rule_id + 순번으로 만들어 씁니다 (화면 key 용도)
 *   · Verdict.judged_at    → 없음. 응답을 받은 시각으로 대신합니다 (동기 호출이라 거의 같음)
 *   · result: 'PASS'       → 백엔드는 위반한 룰만 내려줍니다. 통과한 룰 목록이 없습니다
 *   · result: 'DEFERRED'   → skipped 로 오지만 심각도가 없어 Verdict 로 못 만듭니다 (아래 참고)
 *   · DefectPrediction.top_factors → 백엔드에 SHAP 기여도가 없습니다. 빈 배열로 둡니다
 */

import type {
  DefectPrediction,
  Severity,
  Verdict,
  FieldValue,
} from '../types/domain';
import type {
  WireSeverity,
  WireSkippedRule,
  WireVerifyResponse,
  WireViolation,
} from './wire';

/** 백엔드 소문자 → 우리 대문자. 3종뿐이라 표 하나로 끝납니다 */
const SEVERITY_MAP: Record<WireSeverity, Severity> = {
  critical: 'Critical',
  warning: 'Warning',
  info: 'Info',
};

/**
 * 검사하지 못한 룰.
 *
 * `Verdict` 로 만들지 않고 따로 둡니다. `Verdict.severity` 는 필수인데
 * 백엔드 `skipped` 에는 심각도가 없기 때문입니다 — 아무 심각도나 붙이면
 * S4 요약(위반 n건 · 주의 n건)이 틀린 숫자를 보여줍니다.
 *
 * 화면에서는 "검사하지 못한 항목"으로 따로 보여줘야 합니다. 감추면 사용자가
 * '검사했고 문제없다'로 읽습니다.
 */
export interface SkippedRuleView {
  rule_id: string;
  title: string;
  reason: string;
}

/** 번역 결과 한 묶음 */
export interface VerifyView {
  verdicts: Verdict[];
  prediction: DefectPrediction;
  skipped: SkippedRuleView[];
  /**
   * 확률을 누가 냈는지. `'xgboost-v1'` 이면 학습된 모델,
   * **`'rules-v1'` 이면 모델이 아니라 룰 가중치 합**입니다.
   * 화면에서 후자를 "AI 예측 확률"로 적으면 안 됩니다.
   */
  predictionModel: string;
  /** 판정에 쓴 룰 카탈로그 (예: "v1+ab12cd34ef56"). 없으면 null */
  catalogLabel: string | null;
}

/** 위반 1건 번역 */
function toVerdict(
  v: WireViolation,
  index: number,
  judgedAt: string,
  ruleVersion: string,
  modelVersion: string,
): Verdict {
  return {
    // 백엔드에 판정 id 가 없어서 만들어 씁니다. 같은 룰이 두 번 걸려도
    // 순번 때문에 겹치지 않습니다 (React 목록의 key 로 쓰입니다).
    verdict_id: `${v.rule_id}#${index}`,
    rule_id: v.rule_id,
    target_fields: v.fields,
    result: 'VIOLATION',
    severity: SEVERITY_MAP[v.severity],
    message: v.message,
    // 빈 문자열은 "권고가 없다"는 뜻이므로 null 로 바꿉니다.
    // VerdictCard 가 `action_hint !== null` 로 표시 여부를 정하는데,
    // 빈 문자열을 그대로 두면 빈 줄이 하나 생깁니다.
    action_hint: v.remedy.trim() === '' ? null : v.remedy,
    evidence: { clause_text: v.source },
    judged_at: judgedAt,
    rule_version: ruleVersion,
    model_version: modelVersion,
  };
}

function toSkipped(s: WireSkippedRule): SkippedRuleView {
  return { rule_id: s.rule_id, title: s.title, reason: s.reason };
}

/**
 * `POST /verify` 응답 전체를 화면이 쓰는 모양으로 옮깁니다.
 *
 * @param receivedAt 응답을 받은 시각(ISO 문자열). 백엔드가 판정 시각을 안 주는
 *                   자리를 메웁니다. 호출한 쪽에서 넣어주면 테스트가 고정됩니다.
 */
export function toVerifyView(
  res: WireVerifyResponse,
  receivedAt: string,
): VerifyView {
  const ruleVersion = res.verdict.catalog?.label ?? 'unknown';

  return {
    verdicts: res.verdict.violations.map((v, i) =>
      toVerdict(v, i, receivedAt, ruleVersion, res.verdict.model),
    ),
    prediction: {
      probability: res.prediction.probability,
      // 백엔드에 SHAP 기여도가 없습니다. 지어내지 않고 빈 배열로 둡니다.
      top_factors: [],
      deferred_count: res.verdict.skipped_count,
    },
    skipped: res.verdict.skipped.map(toSkipped),
    predictionModel: res.prediction.model,
    catalogLabel: res.verdict.catalog?.label ?? null,
  };
}

/**
 * 화면의 필드 목록 → 백엔드 `/verify` 가 받는 `bl` 객체.
 *
 * 백엔드는 `{ 필드이름: 값 }` 형태의 평범한 객체를 받습니다. 모르는 키는
 * 조용히 무시하므로, 우리 쪽에만 있는 필드(carrier, booking_no 등)를 같이
 * 보내도 문제 없습니다.
 *
 * `normalized_value` 가 아니라 `value`(원문)를 보냅니다 — 백엔드가 항구명·
 * 날짜 정규화를 스스로 하기 때문에, 우리가 미리 UN/LOCODE 로 바꿔 보내면
 * 백엔드의 대조 규칙과 어긋납니다.
 */
export function toBLPayload(fields: FieldValue[]): Record<string, string> {
  const bl: Record<string, string> = {};
  for (const field of fields) {
    // 값이 없는 필드는 아예 보내지 않습니다. 빈 문자열을 보내면 백엔드가
    // "값이 있는데 형식이 틀렸다"로 읽을 수 있습니다.
    if (field.value !== null && field.value.trim() !== '') {
      bl[field.field_name] = field.value;
    }
  }
  return bl;
}

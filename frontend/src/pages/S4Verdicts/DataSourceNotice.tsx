/**
 * 지금 화면에 보이는 판정이 **어디서 온 것인지** 알려주는 띠.
 *
 * 백엔드가 안 떠 있으면 목데이터로 물러나는데, 그 사실을 감추면 사용자가
 * 목데이터를 실제 판정으로 읽습니다. 규약 §2.4(근거 없는 값 표시 금지)와
 * §5.6(데이터 없음을 정상으로 판단하지 않음)이 같은 이야기를 합니다.
 */

import { SEVERITY } from '../../constants/domain';

interface DataSourceNoticeProps {
  /** 'live' = aiService 응답 · 'mock' = 목데이터 */
  source: 'live' | 'mock';
  /** 목데이터로 물러난 이유. source 가 'mock' 일 때만 씁니다 */
  reason?: string;
  /**
   * 확률을 누가 냈는지. 'rules-v1' 이면 학습된 모델이 아니라 룰 가중치 합이라
   * 그렇게 적어줍니다.
   */
  predictionModel?: string;
}

export function DataSourceNotice({ source, reason, predictionModel }: DataSourceNoticeProps) {
  const isLive = source === 'live';
  // 색상값을 직접 쓰지 않고 SEVERITY 상수를 거칩니다 (CLAUDE.md 변경 금지 1·2번).
  const accent = isLive ? SEVERITY.Info : SEVERITY.Warning;

  return (
    <div
      style={{
        padding: 'var(--space-2) var(--space-3)',
        fontSize: 13,
        lineHeight: 1.6,
        border: '1px solid var(--border-default)',
        borderLeft: `4px solid var(${accent.colorVar})`,
        borderRadius: 'var(--radius-card)',
        backgroundColor: `var(${accent.bgVar})`,
        color: 'var(--text-muted)',
        textAlign: 'left',
      }}
    >
      {isLive ? (
        <>
          <strong style={{ color: 'var(--text)' }}>aiService 실시간 판정</strong>
          {predictionModel === 'rules-v1' && (
            <>
              {' · '}
              하자 확률은 <strong>학습 모델이 아니라 룰 가중치 합</strong>입니다
              (<code>rules-v1</code>)
            </>
          )}
          {predictionModel !== undefined && predictionModel !== 'rules-v1' && (
            <> · 확률 모델 <code>{predictionModel}</code></>
          )}
        </>
      ) : (
        <>
          <strong style={{ color: 'var(--text)' }}>목데이터입니다 — 실제 판정이 아닙니다.</strong>
          {reason !== undefined && <> aiService 응답 실패: {reason}</>}
        </>
      )}
    </div>
  );
}

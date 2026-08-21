/**
 * 검사하지 **못한** 룰 목록.
 *
 * 백엔드 `/verify` 응답의 `skipped` 입니다. 입력이 비었거나 파싱에 실패해서
 * 판단 자체를 못 한 룰이며, **통과가 아닙니다.**
 *
 * 이걸 화면에서 빼면 사용자는 "검사했고 문제없다"로 읽습니다. 백엔드
 * `SkippedRule` 주석도 같은 말을 합니다 — "검사하지 못한 항목을 침묵으로
 * 넘기면 사용자는 '검사했고 문제없다'로 읽는다".
 */

import type { SkippedRuleView } from '../../api/adapters';

interface SkippedListProps {
  skipped: SkippedRuleView[];
}

export function SkippedList({ skipped }: SkippedListProps) {
  if (skipped.length === 0) return null;

  return (
    <details
      style={{
        padding: 'var(--space-3)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        backgroundColor: 'var(--bg-card)',
        textAlign: 'left',
      }}
    >
      {/* <details>/<summary> 는 브라우저가 기본 제공하는 접기/펼치기입니다 */}
      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
        검사하지 못한 항목 {skipped.length}건
      </summary>

      <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
        아래 항목은 <strong>통과한 것이 아니라 판단하지 못한 것</strong>입니다.
      </p>

      <ul style={{ margin: '8px 0 0', paddingLeft: '1.2em' }}>
        {skipped.map((s) => (
          <li key={s.rule_id} style={{ marginTop: 6, fontSize: 14 }}>
            {s.title}
            <span style={{ color: 'var(--text-muted)' }}> — {s.reason}</span>
            <span style={{ marginLeft: 6, fontSize: 12, color: 'var(--text-muted)' }}>
              {s.rule_id}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

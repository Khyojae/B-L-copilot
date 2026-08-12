import { Link } from 'react-router-dom';

/** S1 대시보드 자리 — 지금은 S4Verdicts로 가는 임시 링크만 있음 */
export function S1Dashboard() {
  return (
    <div style={{ padding: 32, textAlign: 'center' }}>
      <h1>B/L Copilot</h1>
      <Link to="/shipments/test-001/verdicts">/shipments/test-001/verdicts로 가기</Link>
    </div>
  );
}

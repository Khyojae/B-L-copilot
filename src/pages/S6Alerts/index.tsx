import { mockAlerts } from '../../mocks/shipment.fixture';
import { bySeverity } from '../../constants/domain';
import type { Alert } from '../../types/domain';
import { PageContainer } from '../../components/PageContainer';
import { AlertCard } from './AlertCard';

/** 미확인(acknowledged: false)이 먼저, 그 안에서는 심각도 순(위반 → 주의 → 참고) */
function byUnacknowledgedThenSeverity(a: Alert, b: Alert): number {
  if (a.acknowledged !== b.acknowledged) return a.acknowledged ? 1 : -1;
  return bySeverity(a, b);
}

export function S6Alerts() {
  return (
    <PageContainer>
      <h1>경보 센터</h1>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {[...mockAlerts].sort(byUnacknowledgedThenSeverity).map((alert) => (
          <AlertCard key={alert.alert_id} alert={alert} />
        ))}
      </div>
    </PageContainer>
  );
}

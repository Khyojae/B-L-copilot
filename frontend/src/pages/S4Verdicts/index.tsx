import { ClipboardCheck, FileQuestion } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { VerdictCard } from './VerdictCard';
import { VerdictSummary } from './VerdictSummary';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import { findShipmentData } from '../../mocks/shipmentData';
import { bySeverity } from '../../constants/domain';

export function S4Verdicts() {
  // URL이 /shipments/:id/verdicts 라서, useParams()로 그 :id 자리의 값을 꺼냅니다.
  // (App.tsx의 <Route path="/shipments/:id/verdicts"> 와 이름이 같아야 합니다)
  const { id } = useParams();
  const data = findShipmentData(id);

  // 주소창에 없는 선적 id를 직접 쳐서 들어온 경우
  if (data === null) {
    return (
      <PageContainer narrow>
        <EmptyState icon={FileQuestion} message={`선적 ${id ?? ''}을(를) 찾을 수 없습니다.`} />
      </PageContainer>
    );
  }

  const { shipment, verdicts } = data;

  // 아직 검증 전(DRAFT)인 선적. 판정이 0건인 것과 "검증했는데 문제 없음"은
  // 전혀 다른 뜻이라, 0건 요약(위반 0 · 주의 0 · 참고 0)을 보여주면 후자로
  // 오해됩니다. 그래서 요약 대신 안내 문구를 띄웁니다.
  if (verdicts.length === 0) {
    return (
      <PageContainer narrow>
        <EmptyState icon={ClipboardCheck} message="아직 검증을 실행하지 않았습니다." />
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <Link to={`/shipments/${shipment.shipment_id}/draft`} className="btn btn-primary">
            초안 편집기에서 검증 실행
          </Link>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer narrow>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Link to={`/shipments/${shipment.shipment_id}/report`} className="btn btn-primary">
            리포트 생성
          </Link>
        </div>

        <VerdictSummary verdicts={verdicts} />
        {[...verdicts].sort(bySeverity).map((verdict) => (
          <VerdictCard key={verdict.verdict_id} verdict={verdict} />
        ))}
      </div>
    </PageContainer>
  );
}

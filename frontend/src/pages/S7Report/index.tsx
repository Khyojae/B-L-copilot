import { ClipboardCheck, FileQuestion, PauseCircle } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { EmptyState } from '../../components/EmptyState';
import { PageContainer } from '../../components/PageContainer';
import { StatusBadge } from '../../components/StatusBadge';
import { VerdictCard } from '../S4Verdicts/VerdictCard';
import { findShipmentData } from '../../mocks/shipmentData';
import { bySeverity } from '../../constants/domain';

/**
 * S7 선제 대응 리포트 — 축소 구현 (화면전이_정의.md §1 "이번 기간: 축소").
 *
 * 원래 리포트는 [리포트 생성] 시점의 "스냅샷 불변"이라, 이후 서류가 바뀌면
 * 열람 시 "이후 N건 변경됨" 배너를 보여줘야 합니다 (§S4→S7). 이번 기간은
 * 그 불변 스냅샷·변경 감지 로직 없이, 지금 mock 데이터를 리포트 형태로
 * 그대로 렌더링만 합니다.
 *
 * 공유 버튼은 만들지 않습니다 (규약 §10.1 — 이번 기간 제외).
 * "PDF로 내보내기"는 자리만 두고 실제 내보내기는 구현하지 않습니다.
 */
export function S7Report() {
  // S4와 마찬가지로 URL의 :id로 선적을 찾습니다 (/shipments/:id/report)
  const { id } = useParams();
  const data = findShipmentData(id);

  function handleExportPdf() {
    // 설계만 — 실제 PDF 렌더링(§10.5 REPORT_PDF 목표 30s)은 이번 기간 범위 밖.
    // 버튼은 남겨두되 클릭해도 아무 일도 안 일어나면 헷갈리니 짧게 안내만 띄움
    window.alert('PDF 내보내기는 준비 중입니다');
  }

  if (data === null) {
    return (
      <PageContainer narrow>
        <EmptyState icon={FileQuestion} message={`선적 ${id ?? ''}을(를) 찾을 수 없습니다.`} />
      </PageContainer>
    );
  }

  const { shipment, verdicts, prediction } = data;

  // 검증 전이면 리포트에 담을 판정도 하자 확률도 없습니다. 빈 리포트를 껍데기만
  // 그리는 대신 안내로 대체합니다 — 하자 확률을 0%로 채워 넣으면 "안전하다"는
  // 근거 없는 값을 보여주는 셈이라 규약 §2.4(추정 생성 금지)에 어긋납니다.
  if (verdicts.length === 0 || prediction === null) {
    return (
      <PageContainer narrow>
        <EmptyState
          icon={ClipboardCheck}
          message="검증을 실행한 뒤에 리포트를 만들 수 있습니다."
        />
      </PageContainer>
    );
  }

  const sortedVerdicts = [...verdicts].sort(bySeverity);
  const deferredVerdicts = verdicts.filter((verdict) => verdict.result === 'DEFERRED');

  return (
    <PageContainer narrow>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <h1 style={{ margin: 0 }}>선제 대응 리포트</h1>
        <button type="button" className="btn-secondary" onClick={handleExportPdf}>
          PDF로 내보내기
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {/* 선적 기본 정보 */}
        <section
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            padding: 'var(--space-3)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-card)',
            backgroundColor: 'var(--bg-card)',
            textAlign: 'left',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <strong style={{ fontSize: 18 }}>{shipment.bl_no ?? '-'}</strong>
            <StatusBadge status={shipment.status} />
          </div>
          <span style={{ color: 'var(--text)' }}>L/C {shipment.lc_no ?? '-'}</span>
          <span style={{ color: 'var(--text)' }}>
            Cargo Control No. {shipment.cargo_control_no ?? '-'}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            조회 시각: {new Date().toLocaleString('ko-KR')} — 스냅샷이 아닌 현재 데이터 기준입니다
          </span>
        </section>

        {/* 하자 확률 요약 */}
        <section
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            padding: 'var(--space-3)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-card)',
            boxShadow: 'var(--shadow-card)',
            backgroundColor: 'var(--brand-primary-light)',
            textAlign: 'left',
          }}
        >
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>하자 확률 요약</p>
          <p style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
            예상 하자 확률 {Math.round(prediction.probability * 100)}%
            {prediction.deferred_count > 0 && (
              <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--text-muted)' }}>
                {' '}
                (판정 보류 {prediction.deferred_count}건 제외)
              </span>
            )}
          </p>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--text-muted)' }}>
            {prediction.top_factors.map((factor) => (
              <li key={factor.factor}>
                {factor.factor} ({Math.round(factor.contribution * 100)}%)
              </li>
            ))}
          </ul>
        </section>

        {/* 판정 보류 안내 */}
        {deferredVerdicts.length > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              padding: 'var(--space-3)',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-card)',
              backgroundColor: 'var(--bg-card)',
              textAlign: 'left',
            }}
          >
            <PauseCircle
              size={16}
              color="var(--text-muted)"
              aria-hidden="true"
              style={{ flexShrink: 0, marginTop: 2 }}
            />
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
              판정 보류 {deferredVerdicts.length}건 — 위 하자 확률에는 반영되지 않았습니다. 관련 필드가
              확인되면 판정이 재개됩니다.
            </p>
          </div>
        )}

        {/* 판정 목록 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <h2 style={{ textAlign: 'left', margin: '8px 0 0' }}>판정 목록</h2>
          {sortedVerdicts.map((verdict) => (
            <VerdictCard
              key={verdict.verdict_id}
              verdict={verdict}
              shipmentId={shipment.shipment_id}
            />
          ))}
        </div>
      </div>
    </PageContainer>
  );
}

import { PauseCircle } from 'lucide-react';
import { PageContainer } from '../../components/PageContainer';
import { StatusBadge } from '../../components/StatusBadge';
import { VerdictCard } from '../S4Verdicts/VerdictCard';
import { mockShipment, mockPrediction, mockVerdicts } from '../../mocks/shipment.fixture';
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
  const sortedVerdicts = [...mockVerdicts].sort(bySeverity);
  const deferredVerdicts = mockVerdicts.filter((verdict) => verdict.result === 'DEFERRED');

  function handleExportPdf() {
    // 설계만 — 실제 PDF 렌더링(§10.5 REPORT_PDF 목표 30s)은 이번 기간 범위 밖
    console.log('[S7Report] PDF로 내보내기 클릭 — 아직 동작 없음');
  }

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
        <button type="button" className="btn-primary" onClick={handleExportPdf}>
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
            <strong style={{ fontSize: 18 }}>{mockShipment.bl_no ?? '-'}</strong>
            <StatusBadge status={mockShipment.status} />
          </div>
          <span style={{ color: 'var(--text)' }}>L/C {mockShipment.lc_no ?? '-'}</span>
          <span style={{ color: 'var(--text)' }}>
            Cargo Control No. {mockShipment.cargo_control_no ?? '-'}
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
            예상 하자 확률 {Math.round(mockPrediction.probability * 100)}%
            {mockPrediction.deferred_count > 0 && (
              <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--text-muted)' }}>
                {' '}
                (판정 보류 {mockPrediction.deferred_count}건 제외)
              </span>
            )}
          </p>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 13, color: 'var(--text-muted)' }}>
            {mockPrediction.top_factors.map((factor) => (
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
            <VerdictCard key={verdict.verdict_id} verdict={verdict} />
          ))}
        </div>
      </div>
    </PageContainer>
  );
}

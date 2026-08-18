import { ArrowRight, FileSearch, Radar, Scale, Ship } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { DashboardPreview } from './DashboardPreview';

/**
 * 랜딩 페이지 — 서비스 소개 + 대시보드 진입.
 *
 * ⚠ 로그인 기능은 없습니다. "시작하기"는 그냥 /shipments 로 이동하는
 *   링크일 뿐이고, 인증·계정 개념 자체가 아직 없습니다. 나중에 로그인이
 *   생기면 이 버튼이 그 흐름의 시작점이 됩니다.
 *
 * 이 화면만 NavBar를 두르지 않습니다 (App.tsx의 AppLayout 밖에 있음) —
 * 아래에 자체 헤더가 있어서 상단 바가 두 줄로 겹치면 어색하기 때문입니다.
 */

/** 소개 카드 3장. 문구는 실제 구현 범위에 맞춰 적었습니다 (없는 기능 홍보 금지) */
const FEATURES: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: FileSearch,
    title: '항목 자동 추출',
    body: 'S/I·L/C·상업송장·포장명세서에서 26개 항목을 뽑고, 각 값이 원문 어디서 나왔는지 함께 표시합니다.',
  },
  {
    icon: Scale,
    title: 'UCP600 기준 판정',
    body: '위반·주의·참고 3단계로 나누어 근거 조항과 수정 방법을 함께 제시합니다.',
  },
  {
    icon: Radar,
    title: '현실 데이터 대조',
    body: '통관·선박 실적과 서류 기재값이 어긋나면 경보로 알립니다.',
  },
];

/** 헤더·본문·푸터가 공유하는 좌우 여백 */
const GUTTER = 'var(--space-6)';

export function S0Landing() {
  // 미리보기 카드의 D-day 계산 기준 시각. 렌더 중에 new Date()를 여러 번
  // 부르지 않도록 여기서 한 번만 만듭니다.
  const now = new Date();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, textAlign: 'left' }}>
      {/* ── 자체 헤더 ── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: `var(--space-3) ${GUTTER}`,
          borderBottom: '1px solid var(--border-default)',
        }}
      >
        <BrandBadge />
        <div style={{ flex: 1 }} />
        {/* 아직 해당 화면이 없어서 링크가 아니라 글자로만 둡니다 — 눌러도 아무
            일도 안 일어나는 링크를 두면 고장난 것처럼 보이기 때문입니다 */}
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>문서</span>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>지원</span>
      </header>

      {/* ── 히어로 ── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          // 디자인의 그라데이션 대신 기존 토큰으로 은은한 남색 배경만 깝니다
          // (새 색상값을 만들지 않기 위해 — CLAUDE.md 1번)
          background: 'var(--brand-primary-light)',
        }}
      >
        <div
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-6)',
            flexWrap: 'wrap',
            padding: `var(--space-6) ${GUTTER}`,
            boxSizing: 'border-box',
          }}
        >
        <div
          style={{
            flex: '1 1 460px',
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-start',
            gap: 'var(--space-5)',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <StatusPill />

            <h1
              style={{
                margin: 0,
                fontSize: 56,
                fontWeight: 600,
                lineHeight: 1.12,
                letterSpacing: '-1.9px',
                color: 'var(--text-primary)',
              }}
            >
              <span style={{ color: 'var(--brand-primary)' }}>B/L</span> Copilot
            </h1>

            <p style={{ fontSize: 19, lineHeight: 1.58, color: 'var(--text-secondary)' }}>
              전자 선하증권 자동검증 플랫폼.
              <br />
              선적서류를 올리면 L/C 조건과 대조해 하자 가능성을 판정합니다.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Link
              to="/shipments"
              className="btn btn-primary"
              style={{ gap: 7, padding: '12px 22px', fontSize: 15, fontWeight: 600 }}
            >
              시작하기
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
            {/* 문의 창구가 아직 없어서 비활성입니다 */}
            <button type="button" className="btn-secondary" disabled style={{ padding: '12px 18px' }}>
              도입 문의
            </button>
          </div>

          <div
            style={{
              alignSelf: 'stretch',
              display: 'flex',
              flexWrap: 'wrap',
              gap: 'var(--space-2)',
            }}
          >
            {FEATURES.map((feature) => (
              <FeatureCard key={feature.title} {...feature} />
            ))}
          </div>
        </div>

          <DashboardPreview now={now} />
        </div>
      </div>

      {/* ── 푸터 ── */}
      <footer
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: `var(--space-2) ${GUTTER}`,
          borderTop: '1px solid var(--border-default)',
          fontSize: 12,
          color: 'var(--text-muted)',
        }}
      >
        <span>판정 기준 RC-2026.08.1</span>
        <div style={{ flex: 1 }} />
        <span>이용약관</span>
        <span>개인정보처리방침</span>
      </footer>
    </div>
  );
}

/** 남색 알약 안에 배 아이콘 + 서비스명 — 헤더 로고 */
function BrandBadge() {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-1)',
        padding: '5px 10px',
        borderRadius: 6,
        backgroundColor: 'var(--brand-primary)',
        color: '#fff',
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: '-0.2px',
      }}
    >
      <Ship size={15} aria-hidden="true" />
      B/L Copilot
    </span>
  );
}

/**
 * 상단 상태 알약.
 *
 * 디자인 원안은 "UNIPASS · DCSA 연동 운영 중"이었지만, 지금은 어댑터가 붙어
 * 있지 않고 목데이터로만 돕니다. 없는 연동을 운영 중이라고 적으면 근거 없는
 * 주장이라(규약 §2.4) 사실대로 바꿨습니다. 실제로 붙으면 문구를 되돌리세요.
 */
function StatusPill() {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        alignSelf: 'flex-start',
        padding: '4px 10px',
        border: '1px solid var(--border-default)',
        borderRadius: 999,
        backgroundColor: 'var(--bg)',
        fontSize: 12,
        fontWeight: 600,
        color: 'var(--text-secondary)',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          backgroundColor: 'var(--status-draft)',
        }}
      />
      목데이터로 동작하는 시제품 · UNIPASS · DCSA 연동 예정
    </span>
  );
}

function FeatureCard({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) {
  return (
    <div
      style={{
        flex: '1 1 240px',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-2)',
        padding: '13px 15px',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-card)',
        backgroundColor: 'var(--bg)',
      }}
    >
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          width: 30,
          height: 30,
          borderRadius: 999,
          backgroundColor: 'var(--brand-primary-light)',
        }}
      >
        <Icon size={15} color="var(--brand-primary)" aria-hidden="true" />
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{title}</span>
        <span style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--text-secondary)' }}>{body}</span>
      </div>
    </div>
  );
}

import { NavLink } from 'react-router-dom';

// "/"는 랜딩(S0)이 쓰므로 대시보드는 "/shipments"입니다
const NAV_ITEMS = [
  { to: '/shipments', label: '대시보드' },
  { to: '/alerts', label: '경보 센터' },
];

/**
 * 전 화면 공통 상단 네비게이션.
 *
 * S3(초안 편집기)·S5(타임라인)는 특정 선적 ID가 있어야 들어갈 수 있는 화면이라
 * 여기 목록에 넣지 않았습니다. 지금은 S1 대시보드에서 선적 카드를 클릭해서
 * 들어가는 경로만 있습니다 — 어떻게 하면 좋을지는 대화에서 의견 남겼습니다.
 */
export function NavBar() {
  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-4)',
        padding: 'var(--space-3) var(--space-6)',
        borderBottom: '1px solid var(--border-default)',
        backgroundColor: 'var(--bg-card)',
      }}
    >
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

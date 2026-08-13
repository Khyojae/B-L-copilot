import type { ReactNode } from 'react';

interface PageContainerProps {
  children: ReactNode;
}

/**
 * 모든 화면이 같이 쓰는 페이지 여백.
 * 화면 폭 제한·중앙 정렬은 #root(index.css)가 맡고, 여기서는 좌우 여백만
 * 통일합니다 — 화면마다 padding 값을 따로 정하지 않도록.
 */
export function PageContainer({ children }: PageContainerProps) {
  return <div style={{ padding: 'var(--space-5) var(--space-6)' }}>{children}</div>;
}

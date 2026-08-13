import type { ReactNode } from 'react';

interface PageContainerProps {
  children: ReactNode;
  /**
   * 목록형 화면(카드 여러 개를 세로로 나열)에서 켜세요. 카드 텍스트 한 줄이
   * 화면 폭만큼 늘어나면 오히려 읽기 불편해지므로, 페이지 자체는 넓어도
   * 콘텐츠는 --content-narrow-width로 좁혀서 가운데 정렬합니다.
   * S3처럼 뷰어+폼을 좌우로 배치해야 하는 화면은 끄고(기본값) 폭을 그대로 씁니다.
   */
  narrow?: boolean;
}

/**
 * 모든 화면이 같이 쓰는 페이지 여백.
 * 화면 폭 제한·중앙 정렬은 #root(index.css)가 맡고, 여기서는 좌우 여백와
 * (narrow일 때) 콘텐츠 폭 제한을 담당합니다 — 화면마다 값을 따로 정하지 않도록.
 */
export function PageContainer({ children, narrow = false }: PageContainerProps) {
  const content = narrow ? (
    <div style={{ maxWidth: 'var(--content-narrow-width)', margin: '0 auto' }}>{children}</div>
  ) : (
    children
  );

  return <div style={{ padding: 'var(--space-5) var(--space-6)' }}>{content}</div>;
}

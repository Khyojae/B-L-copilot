import { Outlet } from 'react-router-dom';
import { NavBar } from './NavBar';

/**
 * 상단 NavBar를 두르는 공통 레이아웃.
 *
 * <Outlet />은 "이 자리에 자식 화면을 끼워 넣어라"는 뜻의 react-router 부품입니다.
 * App.tsx에서 이 레이아웃을 부모 라우트로 두면, 그 안의 화면들만 NavBar를
 * 갖게 됩니다 — 랜딩(S0)은 자체 헤더가 있어서 이 레이아웃 밖에 둡니다.
 */
export function AppLayout() {
  return (
    <>
      <NavBar />
      <Outlet />
    </>
  );
}

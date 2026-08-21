import { Routes, Route } from 'react-router-dom'
import { S0Landing } from './pages/S0Landing'
import { S1Dashboard } from './pages/S1Dashboard'
import { S2Upload } from './pages/S2Upload'
import { S3Draft } from './pages/S3Draft'
import { S4Verdicts } from './pages/S4Verdicts'
import { S5Timeline } from './pages/S5Timeline'
import { S6Alerts } from './pages/S6Alerts'
import { S7Report } from './pages/S7Report'
import { ComingSoon } from './components/ComingSoon'
import { AppLayout } from './components/AppLayout'

function App() {
  return (
    <Routes>
      {/* 랜딩은 자체 헤더가 있어서 AppLayout(NavBar) 밖에 둡니다 */}
      <Route path="/" element={<S0Landing />} />

      {/* 나머지 화면 — 공통 NavBar를 두른 레이아웃 안쪽.
          대시보드가 "/"에서 "/shipments"로 옮겨졌습니다 (랜딩이 "/"를 씀) */}
      <Route element={<AppLayout />}>
        <Route path="/shipments" element={<S1Dashboard />} />
        <Route path="/shipments/new" element={<S2Upload />} />
        <Route path="/shipments/:id/draft" element={<S3Draft />} />
        <Route path="/shipments/:id/verdicts" element={<S4Verdicts />} />
        <Route path="/shipments/:id" element={<S5Timeline />} />
        <Route path="/alerts" element={<S6Alerts />} />
        <Route path="/shipments/:id/report" element={<S7Report />} />
        <Route path="/shipments/:id/outcome" element={<ComingSoon label="S10 결과 기록" />} />
        <Route path="/settings" element={<ComingSoon label="S11 설정" />} />
      </Route>
    </Routes>
  )
}

export default App

import { Routes, Route } from 'react-router-dom'
import { S1Dashboard } from './pages/S1Dashboard'
import { S2Upload } from './pages/S2Upload'
import { S3Draft } from './pages/S3Draft'
import { S4Verdicts } from './pages/S4Verdicts'
import { S6Alerts } from './pages/S6Alerts'
import { ComingSoon } from './components/ComingSoon'

function App() {
  return (
    <Routes>
      <Route path="/" element={<S1Dashboard />} />
      <Route path="/shipments/new" element={<S2Upload />} />
      <Route path="/shipments/:id/draft" element={<S3Draft />} />
      <Route path="/shipments/:id/verdicts" element={<S4Verdicts />} />
      <Route path="/shipments/:id" element={<ComingSoon label="S5 선적 상세(타임라인)" />} />
      <Route path="/alerts" element={<S6Alerts />} />
      <Route path="/shipments/:id/report" element={<ComingSoon label="S7 선제 대응 리포트" />} />
      <Route path="/shipments/:id/outcome" element={<ComingSoon label="S10 결과 기록" />} />
      <Route path="/settings" element={<ComingSoon label="S11 설정" />} />
    </Routes>
  )
}

export default App

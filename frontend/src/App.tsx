import { Routes, Route } from 'react-router-dom'
import { S1Dashboard } from './pages/S1Dashboard'
import { S4Verdicts } from './pages/S4Verdicts'
import { ComingSoon } from './components/ComingSoon'

function App() {
  return (
    <Routes>
      <Route path="/" element={<S1Dashboard />} />
      <Route path="/shipments/new" element={<ComingSoon label="S2 서류 업로드" />} />
      <Route path="/shipments/:id/draft" element={<ComingSoon label="S3 초안 편집기" />} />
      <Route path="/shipments/:id/verdicts" element={<S4Verdicts />} />
      <Route path="/shipments/:id" element={<ComingSoon label="S5 선적 상세(타임라인)" />} />
      <Route path="/alerts" element={<ComingSoon label="S6 경보 센터" />} />
      <Route path="/shipments/:id/report" element={<ComingSoon label="S7 선제 대응 리포트" />} />
      <Route path="/shipments/:id/outcome" element={<ComingSoon label="S10 결과 기록" />} />
      <Route path="/settings" element={<ComingSoon label="S11 설정" />} />
    </Routes>
  )
}

export default App

import { Routes, Route } from 'react-router-dom'
import { S1Dashboard } from './pages/S1Dashboard'
import { S2Upload } from './pages/S2Upload'
import { S3Draft } from './pages/S3Draft'
import { S4Verdicts } from './pages/S4Verdicts'
import { S5Timeline } from './pages/S5Timeline'
import { S6Alerts } from './pages/S6Alerts'
import { S7Report } from './pages/S7Report'
import { ComingSoon } from './components/ComingSoon'
import { NavBar } from './components/NavBar'

function App() {
  return (
    <>
      <NavBar />
      <Routes>
        <Route path="/" element={<S1Dashboard />} />
        <Route path="/shipments/new" element={<S2Upload />} />
        <Route path="/shipments/:id/draft" element={<S3Draft />} />
        <Route path="/shipments/:id/verdicts" element={<S4Verdicts />} />
        <Route path="/shipments/:id" element={<S5Timeline />} />
        <Route path="/alerts" element={<S6Alerts />} />
        <Route path="/shipments/:id/report" element={<S7Report />} />
        <Route path="/shipments/:id/outcome" element={<ComingSoon label="S10 결과 기록" />} />
        <Route path="/settings" element={<ComingSoon label="S11 설정" />} />
      </Routes>
    </>
  )
}

export default App

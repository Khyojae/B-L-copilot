import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { ShipmentStoreProvider } from './shared/shipmentStore'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      {/* 화면들이 선적을 읽는 통로. 픽스처 4건 + 이번 세션에 업로드로 만든 것 */}
      <ShipmentStoreProvider>
        <App />
      </ShipmentStoreProvider>
    </BrowserRouter>
  </StrictMode>,
)

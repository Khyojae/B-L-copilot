import { mockShipment } from '../../mocks/shipment.fixture';
import { ShipmentCard } from './ShipmentCard';

export function S1Dashboard() {
  return (
    <div style={{ padding: 32 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        <h1 style={{ margin: 0 }}>B/L Copilot</h1>

        {/* S2(서류 업로드)가 아직 스텁이라 지금은 자리만 잡아둠 — 클릭해도 동작 없음 */}
        <button type="button">+ 새 선적</button>
      </div>

      <ShipmentCard shipment={mockShipment} />
    </div>
  );
}

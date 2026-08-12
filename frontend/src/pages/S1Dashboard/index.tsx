import { Link } from 'react-router-dom';
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
        <Link to="/shipments/new">+ 새 선적</Link>
      </div>

      <ShipmentCard shipment={mockShipment} />
    </div>
  );
}

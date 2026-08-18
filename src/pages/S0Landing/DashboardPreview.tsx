import { useEffect, useRef, useState } from 'react';
import { mockShipments } from '../../mocks/shipment.fixture';
import { findShipmentData } from '../../mocks/shipmentData';
import { ShipmentCard } from '../S1Dashboard/ShipmentCard';

/** 액자 안에서 카드를 그릴 실제 폭. 이 값을 아래 SCALE로 줄여서 넣습니다 */
const CARD_WIDTH = 660;
const SCALE = 0.66;

interface DashboardPreviewProps {
  /** 카드의 D-day 계산 기준 시각 — 랜딩이 한 번만 만들어 넘깁니다 */
  now: Date;
}

/**
 * 랜딩 히어로 오른쪽의 대시보드 미리보기.
 *
 * 스크린샷 이미지를 쓰지 않고 실제 ShipmentCard를 렌더해서 축소합니다.
 * 대시보드가 바뀌면 미리보기도 같이 바뀌므로, 화면과 홍보물이 어긋나는 일이
 * 생기지 않습니다. 값도 전부 목데이터라 지어낸 숫자가 없습니다.
 *
 * ⚠ 장식이라 조작 대상이 아닙니다. 세 가지로 막습니다:
 *   - pointer-events: none  — 마우스 클릭 차단
 *   - inert                 — 키보드 Tab이 카드 안 링크로 들어가지 못하게
 *   - aria-hidden           — 화면 낭독기가 읽지 않게
 *   pointer-events만 쓰면 클릭은 막히지만 Tab으로는 들어가져서, 보이지도 않는
 *   링크에 포커스가 갇힙니다.
 */
export function DashboardPreview({ now }: DashboardPreviewProps) {
  // transform: scale은 레이아웃 크기를 바꾸지 않습니다. 그래서 액자 높이를
  // 따로 정해줘야 하는데, 숫자를 박아두면 카드 내용이 늘어날 때 중간이
  // 잘립니다(처음에 실제로 "위반 2" 띠 한가운데서 잘렸습니다).
  // 카드의 실제 높이를 재서 축소 비율만큼만 자리를 잡습니다.
  const cardRef = useRef<HTMLDivElement>(null);
  const [frameHeight, setFrameHeight] = useState<number | undefined>(undefined);

  useEffect(() => {
    const element = cardRef.current;
    if (element === null) return;

    // offsetHeight는 transform의 영향을 받지 않는 원래 높이입니다
    const sync = () => setFrameHeight(Math.ceil(element.offsetHeight * SCALE));
    sync();

    // 폰트 로딩·줄바꿈으로 높이가 바뀌면 따라갑니다
    const observer = new ResizeObserver(sync);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // 목록 첫 번째 선적 — 판정·필드가 가장 많이 채워져 있어 화면을 대표합니다
  const first = mockShipments[0];
  const data = first === undefined ? null : findShipmentData(first.shipment_id);
  if (data === null) return null;

  return (
    <figure className="landing-preview">
      <div
        style={{
          // 축소한 카드가 액자를 넘치지 않도록 잘라냅니다
          overflow: 'hidden',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-card)',
          boxShadow: 'var(--shadow-card)',
          backgroundColor: 'var(--bg)',
          // 카드 높이 × 축소 비율. 재기 전(첫 렌더)에는 undefined라 내용
          // 높이대로 잠깐 커졌다가 곧 맞춰집니다.
          height: frameHeight,
        }}
      >
        <div
          ref={cardRef}
          inert
          aria-hidden="true"
          style={{
            width: CARD_WIDTH,
            transform: `scale(${SCALE})`,
            transformOrigin: 'top left',
            pointerEvents: 'none',
          }}
        >
          <ShipmentCard data={data} now={now} />
        </div>
      </div>

      {/* 실제 화면으로 오해하지 않도록 밝힙니다 */}
      <figcaption style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        대시보드 미리보기 — 실제 화면의 선적 카드입니다
      </figcaption>
    </figure>
  );
}

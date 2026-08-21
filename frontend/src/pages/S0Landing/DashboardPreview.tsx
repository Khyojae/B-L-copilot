import { useEffect, useRef, useState } from 'react';
import { mockShipments } from '../../mocks/shipment.fixture';
import { findShipmentData } from '../../mocks/shipmentData';
import { ShipmentCard } from '../S1Dashboard/ShipmentCard';

/** 액자 안에서 카드를 그릴 실제 폭. 이 값을 아래 SCALE로 줄여서 넣습니다 */
const CARD_WIDTH = 660;
const SCALE = 0.5;
/** 카드를 감싸는 안쪽 여백(아래 stack의 padding과 같은 값) */
const STACK_PADDING = 14;
/** 액자 전체 폭 = 축소된 카드 폭 + 안쪽 여백 양쪽. 이 값이 바뀌면 액자도 같이
    좁아지거나 넓어집니다 — 배율만 바꾸고 이 상수를 안 맞추면 액자 안에 빈
    공간이 남습니다(실제로 SCALE을 0.66→0.5로 낮췄는데 CSS 폭은 그대로 440이라
    오른쪽에 80px 빈 공간이 생겼던 적이 있습니다) */
const FRAME_WIDTH = CARD_WIDTH * SCALE + STACK_PADDING * 2;
/** 앞에서 몇 건만 보여줄지 — 미리보기는 장식이라 목록 전체를 넣을 필요는 없습니다 */
const PREVIEW_COUNT = 3;
/** 액자 몸통의 최대 높이. 넘치면 자르고 아래쪽을 페이드로 가립니다 */
const MAX_BODY_HEIGHT = 460;

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
 * 브라우저 창 액자 안에 카드를 여러 장 쌓아서 "선적 목록 화면"처럼 보이게
 * 합니다 — 시안(랜딩.dc.html)은 자체 축약 카드를 그렸지만, 여기서는 반드시
 * 실제 컴포넌트를 씁니다. 그래서 시안의 "위반 3" 같은 숫자는 나오지 않고
 * 지금 목데이터의 실제 값(위반 2 등)이 그대로 보입니다.
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
  // 잘립니다. 카드들을 쌓은 실제 높이를 재서 축소 비율만큼만 자리를 잡고,
  // 그래도 MAX_BODY_HEIGHT를 넘기면 거기서 자르고 페이드를 덧씌웁니다.
  const stackRef = useRef<HTMLDivElement>(null);
  const [bodyHeight, setBodyHeight] = useState(MAX_BODY_HEIGHT);
  const [isClipped, setIsClipped] = useState(false);

  useEffect(() => {
    const element = stackRef.current;
    if (element === null) return;

    // offsetHeight는 transform의 영향을 받지 않는 원래 높이입니다
    const sync = () => {
      const scaledHeight = Math.ceil(element.offsetHeight * SCALE);
      setBodyHeight(Math.min(scaledHeight, MAX_BODY_HEIGHT));
      setIsClipped(scaledHeight > MAX_BODY_HEIGHT);
    };
    sync();

    // 폰트 로딩·줄바꿈으로 높이가 바뀌면 따라갑니다
    const observer = new ResizeObserver(sync);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // 앞에서 PREVIEW_COUNT건 — 판정·필드가 채워진 순서 그대로 보여줍니다.
  //
  // 다른 화면과 달리 저장소(useShipmentList)를 쓰지 않고 픽스처를 직접 읽습니다.
  // 저장소를 쓰면 사용자가 방금 업로드한 빈 초안이 미리보기에 뜨는데, 랜딩은
  // "이 제품이 무엇을 보여주는가"를 소개하는 자리라 판정·경보가 다 채워진
  // 고정 예시가 맞습니다.
  const items = mockShipments
    .slice(0, PREVIEW_COUNT)
    .map((shipment) => findShipmentData(shipment.shipment_id))
    .filter((data) => data !== null);

  if (items.length === 0) return null;

  return (
    <figure className="landing-preview">
      <div
        style={{
          width: FRAME_WIDTH,
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-card)',
          boxShadow: 'var(--shadow-card)',
          backgroundColor: 'var(--bg)',
          overflow: 'hidden',
        }}
      >
        {/* 브라우저 창 흉내 — 점 3개 + 탭 라벨. 실제 화면 캡처가 아님을
            바로 알 수 있도록 하는 장식용 크롬입니다 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            padding: '9px 14px',
            borderBottom: '1px solid var(--border-default)',
            backgroundColor: 'var(--bg-card)',
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: 999, backgroundColor: 'var(--border-default)' }} />
          <span style={{ width: 7, height: 7, borderRadius: 999, backgroundColor: 'var(--border-default)' }} />
          <span style={{ width: 7, height: 7, borderRadius: 999, backgroundColor: 'var(--border-default)' }} />
          <span
            style={{
              marginLeft: 6,
              padding: '2px 10px',
              borderRadius: 4,
              border: '1px solid var(--border-default)',
              backgroundColor: 'var(--bg)',
              fontSize: 11,
              color: 'var(--text-muted)',
            }}
          >
            선적 목록 · B/L Copilot
          </span>
        </div>

        {/* 몸통 — 실제 카드를 쌓아 넣고 넘치면 자릅니다 */}
        <div
          style={{
            position: 'relative',
            height: bodyHeight,
            overflow: 'hidden',
            backgroundColor: 'var(--bg-card)',
          }}
        >
          <div
            ref={stackRef}
            inert
            aria-hidden="true"
            style={{
              width: CARD_WIDTH,
              display: 'flex',
              flexDirection: 'column',
              gap: 14,
              padding: 14,
              boxSizing: 'content-box',
              transform: `scale(${SCALE})`,
              transformOrigin: 'top left',
              pointerEvents: 'none',
            }}
          >
            {items.map((data) => (
              <ShipmentCard key={data.shipment.shipment_id} data={data} now={now} />
            ))}
          </div>

          {/* 더 있다는 느낌만 주는 페이드 — 실제로 잘렸을 때만 보여줍니다 */}
          {isClipped && (
            <div
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 0,
                height: 64,
                background: 'linear-gradient(to bottom, transparent, var(--bg-card))',
                pointerEvents: 'none',
              }}
            />
          )}
        </div>
      </div>

      {/* 실제 화면으로 오해하지 않도록 밝힙니다 */}
      <figcaption style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        대시보드 미리보기 — 실제 화면의 선적 카드입니다
      </figcaption>
    </figure>
  );
}

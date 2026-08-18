import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { mockShipments } from '../mocks/shipment.fixture';
import {
  buildNewDraftData,
  findShipmentData,
  type ShipmentMockData,
} from '../mocks/shipmentData';
import type { FieldValue, Shipment } from '../types/domain';

/**
 * 화면이 선적을 읽는 유일한 통로.
 *
 * 전에는 각 화면이 mocks의 findShipmentData를 직접 불렀는데, 그건 모듈 로드 시
 * 한 번 만들어지는 상수라 런타임에 선적을 추가할 자리가 없었습니다. 그래서
 * S2 업로드가 몇 번을 해도 늘 같은 DRAFT 선적으로 갔습니다.
 *
 * 여기서 "픽스처 4건 + 이번 세션에 만들어진 것"을 합쳐서 돌려줍니다.
 * 화면 코드는 어느 쪽인지 몰라도 됩니다.
 *
 * ⚠ 목데이터 단계의 임시 장치입니다. 실제 API가 붙으면 이 저장소는 서버
 *   응답을 담는 캐시로 바뀌거나 통째로 사라집니다.
 */

/** sessionStorage 키 — 탭이 살아 있는 동안만 유지됩니다 */
const STORAGE_KEY = 'bl-copilot:created-shipments';

/**
 * 저장하는 것 — 식별 정보(Shipment)와, 백엔드에서 뽑아온 필드 목록.
 *
 * 묶음 전체(제안·영향분석까지)를 저장하면 용량도 크고, 픽스처가 바뀌었을 때
 * 저장된 옛 구조가 되살아나 화면과 어긋납니다. 그래서 나머지는 읽을 때마다
 * buildNewDraftData로 다시 만듭니다.
 *
 * 다만 **추출 필드는 다시 만들 수 없습니다** — 그건 사용자가 올린 파일에서
 * 백엔드가 한 번 읽어낸 결과라, 새로고침하면 되살릴 방법이 없습니다.
 * 그래서 이것만 함께 저장합니다.
 */
interface CreatedShipment {
  shipment: Shipment;
  /** 실제 추출 결과. 추출 없이 만든 초안이면 null */
  fields: FieldValue[] | null;
}

function readStored(): CreatedShipment[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw === null) return [];
    const parsed = JSON.parse(raw) as unknown[];
    // 예전 형식(Shipment만 저장하던 때)이 남아 있어도 화면이 죽지 않게 감쌉니다.
    return parsed.map((item) => {
      const record = item as Partial<CreatedShipment> & Partial<Shipment>;
      return record.shipment !== undefined
        ? { shipment: record.shipment, fields: record.fields ?? null }
        : { shipment: item as Shipment, fields: null };
    });
  } catch {
    // 저장소를 못 쓰는 환경(사생활 보호 모드 등)에서도 화면은 떠야 합니다
    return [];
  }
}

function writeStored(created: CreatedShipment[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(created));
  } catch {
    // 저장에 실패해도 이번 세션 메모리에는 남아 있으므로 화면은 계속 동작합니다
    // (추출 필드가 커서 용량 한계에 걸리는 경우도 여기로 옵니다)
  }
}

interface ShipmentStoreValue {
  /** 픽스처 + 새로 만든 선적. 새것이 위로 옵니다 (S1이 "최근 수정순"이라고 밝힘) */
  list: ShipmentMockData[];
  find: (shipmentId: string | undefined) => ShipmentMockData | null;
  /**
   * 새 초안을 만들고 그 shipment_id를 돌려줍니다.
   * `fields` 는 백엔드 /extract 로 뽑아온 실제 필드입니다. 없으면 목 필드로 채웁니다.
   */
  createDraft: (fields?: FieldValue[] | null) => string;
}

const ShipmentStoreContext = createContext<ShipmentStoreValue | null>(null);

export function ShipmentStoreProvider({ children }: { children: ReactNode }) {
  const [created, setCreated] = useState<CreatedShipment[]>(readStored);

  const createDraft = useCallback((fields?: FieldValue[] | null): string => {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, '0');
    const datePart = `${now.getFullYear()}-${pad(now.getMonth() + 1)}${pad(now.getDate())}`;

    let shipmentId = '';
    setCreated((prev) => {
      // 같은 날 여러 건을 만들어도 번호가 겹치지 않게 뒤 3자리를 올립니다.
      // 픽스처가 001~004를 쓰므로 900번대부터 시작해 부딪히지 않게 합니다.
      const sequence = 901 + prev.length;
      shipmentId = `SHP-${datePart}-${sequence}`;

      const shipment: Shipment = {
        shipment_id: shipmentId,
        status: 'DRAFT',
        // 업로드 직후라 아직 없는 값들입니다. 지어내지 않고 null로 둡니다.
        bl_no: null,
        cargo_control_no: null,
        lc_no: null,
        created_at: now.toISOString(),
        updated_at: now.toISOString(),
        lc_expiry_date: null,
      };

      const next = [...prev, { shipment, fields: fields ?? null }];
      writeStored(next);
      return next;
    });

    return shipmentId;
  }, []);

  const value = useMemo<ShipmentStoreValue>(() => {
    // 새로 만든 것이 위, 그 아래 픽스처 4건
    const createdData = [...created]
      .reverse()
      .map((record) => buildNewDraftData(record.shipment, record.fields));
    const fixtureData = mockShipments
      .map((shipment) => findShipmentData(shipment.shipment_id))
      .filter((data): data is ShipmentMockData => data !== null);
    const list = [...createdData, ...fixtureData];

    return {
      list,
      find: (shipmentId) =>
        shipmentId === undefined
          ? null
          : list.find((data) => data.shipment.shipment_id === shipmentId) ?? null,
      createDraft,
    };
  }, [created, createDraft]);

  return <ShipmentStoreContext.Provider value={value}>{children}</ShipmentStoreContext.Provider>;
}

function useStore(): ShipmentStoreValue {
  const store = useContext(ShipmentStoreContext);
  if (store === null) {
    throw new Error('ShipmentStoreProvider 안에서만 쓸 수 있습니다');
  }
  return store;
}

/** 선적 목록 — S1·S6처럼 여러 건을 한 화면에 놓는 곳에서 씁니다 */
export function useShipmentList(): ShipmentMockData[] {
  return useStore().list;
}

/** URL의 :id로 선적 1건 찾기. 없으면 null */
export function useShipmentData(shipmentId: string | undefined): ShipmentMockData | null {
  return useStore().find(shipmentId);
}

/** 새 초안 만들기 — S2 업로드가 끝났을 때 씁니다 */
export function useCreateDraft(): (fields?: FieldValue[] | null) => string {
  return useStore().createDraft;
}

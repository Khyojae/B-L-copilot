import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud } from 'lucide-react';
import type { Job } from '../../types/domain';
import { JOB_STATUS_LABEL, SUPPORTED_INPUT } from '../../constants/domain';
import { mockShipmentDraft } from '../../mocks/shipment.fixture';
import { PageContainer } from '../../components/PageContainer';

function getExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf('.');
  return dotIndex === -1 ? '' : fileName.slice(dotIndex).toLowerCase();
}

export function S2Upload() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [rejectMessage, setRejectMessage] = useState<string | null>(null);

  // 가짜 추출 작업 진행 — PENDING 800ms 후 EXTRACTING, 다시 2000ms 후 DONE
  useEffect(() => {
    if (job?.status === 'PENDING') {
      const timer = setTimeout(() => {
        setJob((prev) => (prev ? { ...prev, status: 'EXTRACTING' } : prev));
      }, 800);
      return () => clearTimeout(timer);
    }
    if (job?.status === 'EXTRACTING') {
      const timer = setTimeout(() => {
        setJob((prev) => (prev ? { ...prev, status: 'DONE' } : prev));
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [job?.status]);

  // DONE이 되면 S3(초안 편집기)로 이동 — 화면전이_정의.md: "job DONE 전에는 S3로 이동하지 않는다"
  //
  // 어디로 보낼 것인가: 업로드는 "새 선적을 만드는" 흐름이라 원래는 방금 만들어진
  // 선적으로 가야 합니다. 하지만 mockDataByShipment는 모듈 로드 시 한 번 만들어지는
  // 고정 상수라, 런타임에 선적을 새로 추가하려면 전역 상태 저장소가 필요하고 —
  // 무엇보다 새로고침하면 그 선적이 사라져 "선적을 찾을 수 없습니다"가 됩니다.
  //
  // 대신 이미 있는 DRAFT 선적(SHP-2026-0813-002)으로 보냅니다. 이 선적은 26개
  // 필드 중 SI·L/C에서 나오는 6개만 값이 있는, 정확히 "서류를 막 올린 초안"
  // 상태라 업로드 직후 도착할 화면으로 맞습니다.
  //
  // ⚠ 한계: 몇 번을 업로드해도 같은 선적으로 갑니다. 실제 API가 붙으면
  //   POST /shipments 응답의 새 shipment_id로 이동하도록 바꿔야 합니다.
  useEffect(() => {
    if (job?.status === 'DONE') {
      navigate(`/shipments/${mockShipmentDraft.shipment_id}/draft`);
    }
  }, [job?.status, navigate]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ''; // 같은 파일을 다시 골라도 change 이벤트가 나도록 비움

    if (!file) return;

    const ext = getExtension(file.name);
    const acceptedExt: readonly string[] = SUPPORTED_INPUT.ACCEPTED_EXT;
    const deferredExt: readonly string[] = SUPPORTED_INPUT.DEFERRED_EXT;

    if (!acceptedExt.includes(ext)) {
      const isDeferred = deferredExt.includes(ext);
      setRejectMessage(
        isDeferred
          ? `${ext} 형식은 이번 기간에는 아직 지원하지 않습니다.`
          : `${ext || '이 형식'}은(는) 지원하지 않는 파일 형식입니다.`,
      );
      return;
    }

    setRejectMessage(null);
    setJob({ job_id: `JOB-${Date.now()}`, status: 'PENDING', progress: null, failure_reason: null });
  }

  function openFilePicker() {
    if (job !== null) return;
    inputRef.current?.click();
  }

  return (
    // 목록·폼 화면은 narrow로 콘텐츠 폭을 좁힙니다 (S1·S4~S7과 같은 기준).
    // 전체 폭을 쓰는 건 뷰어+폼을 좌우로 놓는 S3뿐입니다.
    <PageContainer narrow>
      <h1>서류 업로드</h1>

      <input ref={inputRef} type="file" onChange={handleFileChange} style={{ display: 'none' }} />

      {/* 드롭존 — 지금은 클릭만 되고, 실제 드래그앤드롭 연결은 다음 단계 */}
      <div
        onClick={openFilePicker}
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 'var(--space-3)',
          height: 300,
          border: '2px dashed var(--border-default)',
          borderRadius: 'var(--radius-card)',
          backgroundColor: 'var(--bg-card)',
          cursor: job !== null ? 'default' : 'pointer',
          opacity: job !== null ? 0.6 : 1,
          textAlign: 'center',
        }}
      >
        <UploadCloud size={32} color="var(--text-muted)" aria-hidden="true" />
        <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
          파일을 드래그하거나 클릭해서 선택하세요
        </p>
        <button
          type="button"
          className="btn-primary"
          onClick={(event) => {
            event.stopPropagation();
            openFilePicker();
          }}
          disabled={job !== null}
        >
          파일 선택
        </button>
      </div>

      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 'var(--space-3)' }}>
        지원 형식: {SUPPORTED_INPUT.ACCEPTED_EXT.join(', ')}
      </p>

      {rejectMessage !== null && (
        <p style={{ color: 'var(--severity-critical)' }}>{rejectMessage}</p>
      )}

      {job !== null && <p>진행 상태: {JOB_STATUS_LABEL[job.status]}</p>}
    </PageContainer>
  );
}

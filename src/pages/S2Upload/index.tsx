import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud } from 'lucide-react';
import type { Job } from '../../types/domain';
import { JOB_STATUS_LABEL, SUPPORTED_INPUT } from '../../constants/domain';
import { mockShipment } from '../../mocks/shipment.fixture';
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
  useEffect(() => {
    if (job?.status === 'DONE') {
      navigate(`/shipments/${mockShipment.shipment_id}/draft`);
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
    <PageContainer>
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

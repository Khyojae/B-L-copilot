import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud } from 'lucide-react';
import type { Job } from '../../types/domain';
import { JOB_STATUS_LABEL, SUPPORTED_INPUT } from '../../constants/domain';
import { useCreateDraft } from '../../shared/shipmentStore';
import { extractDraft } from '../../api/extract';
import { PageContainer } from '../../components/PageContainer';

function getExtension(fileName: string): string {
  const dotIndex = fileName.lastIndexOf('.');
  return dotIndex === -1 ? '' : fileName.slice(dotIndex).toLowerCase();
}

export function S2Upload() {
  const navigate = useNavigate();
  const createDraft = useCreateDraft();
  const inputRef = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<Job | null>(null);
  // 사용자가 고른 파일. 이게 정해지면 아래 useEffect가 추출 요청을 보냅니다.
  const [file, setFile] = useState<File | null>(null);
  const [rejectMessage, setRejectMessage] = useState<string | null>(null);

  // 파일이 정해지면 백엔드(F1 인테이크)에 올려서 초안 필드를 받아옵니다.
  //
  // 예전에는 setTimeout으로 진행 상태를 흉내 냈지만, 지금은 진짜 요청이
  // 걸리는 동안이 EXTRACTING이고 응답이 오면 DONE입니다.
  //
  // 화면전이_정의.md: "job DONE 전에는 S3로 이동하지 않는다"
  useEffect(() => {
    if (file === null) return;

    // 화면을 떠나면 요청을 취소합니다.
    const controller = new AbortController();
    setJob({
      job_id: `JOB-${file.lastModified}-${file.size}`,
      status: 'EXTRACTING',
      progress: null,
      failure_reason: null,
    });

    extractDraft(file, controller.signal)
      .then((fields) => {
        if (controller.signal.aborted) return;
        setJob((prev) => (prev ? { ...prev, status: 'DONE' } : prev));
        // 추출된 진짜 필드로 새 선적을 만들고 그 선적의 S3로 갑니다.
        const shipmentId = createDraft(fields);
        navigate(`/shipments/${shipmentId}/draft`);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setJob((prev) =>
          prev
            ? {
                ...prev,
                status: 'FAILED',
                failure_reason: err instanceof Error ? err.message : String(err),
              }
            : prev,
        );
      });

    return () => controller.abort();
  }, [file, createDraft, navigate]);

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
    setFile(file);
  }

  // 추출 중이거나 이미 끝난 뒤에만 잠급니다 — 실패했으면 다시 고를 수 있어야 합니다.
  const busy = job !== null && job.status !== 'FAILED';

  function openFilePicker() {
    if (busy) return;
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
          cursor: busy ? 'default' : 'pointer',
          opacity: busy ? 0.6 : 1,
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
          disabled={busy}
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

      {/* 실패 사유는 감추지 않고 그대로 보여줍니다 — 추출 서버가 안 떠 있는
          것인지, 형식이 안 맞는 것인지 사용자가 알아야 다음 행동이 정해집니다 */}
      {job?.status === 'FAILED' && (
        <p style={{ color: 'var(--severity-critical)' }}>
          추출 실패: {job.failure_reason ?? '알 수 없는 오류'}
        </p>
      )}
    </PageContainer>
  );
}

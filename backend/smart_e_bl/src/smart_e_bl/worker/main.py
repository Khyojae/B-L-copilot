"""워커 프로세스.

ingest_job 테이블 자체를 큐로 씁니다. FOR UPDATE SKIP LOCKED 로 잡을 집으면
워커를 여러 개 띄워도 같은 잡을 두 번 처리하지 않습니다.

Redis·Celery 를 도입하지 않은 이유: 잡 상태(QUEUED/EXTRACTING/DONE/FAILED)와
진행률을 어차피 DB 에 두어야 화면이 폴링할 수 있고(기획안 5.1), 브로커를 따로 두면
폐쇄망 단일 호스트 배포에 컴포넌트가 하나 더 늘어납니다. 처리량이 부족해지면
그때 브로커로 옮기면 됩니다 — 이 파일의 집는 부분만 바뀝니다.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy import select

from smart_e_bl.clients.ai_service import AiServiceError
from smart_e_bl.config import settings
from smart_e_bl.db import sync_session
from smart_e_bl.models import IngestJob
from smart_e_bl.models.enums import JobStatus
from smart_e_bl.worker.pipeline import UnsupportedDocumentError, run_extraction

logger = logging.getLogger("smart_e_bl.worker")

_shutdown = False


def _handle_signal(signum: int, frame: FrameType | None) -> None:
    global _shutdown
    _shutdown = True
    logger.info("종료 신호 수신(%s). 진행 중인 잡을 마치고 멈춥니다.", signum)


def claim_job(session) -> IngestJob | None:
    """대기 중인 잡 하나를 배타적으로 집습니다."""
    job = session.scalar(
        select(IngestJob)
        .where(IngestJob.status == JobStatus.QUEUED)
        .order_by(IngestJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.EXTRACTING
    job.started_at = datetime.now(UTC)
    session.commit()
    return job


def process(session, job: IngestJob) -> None:
    """F1 추출 파이프라인.

    이번 라운드 범위: 문서 1건(이미지 또는 PDF 1페이지)을 aiService에 보내
    field_value로 저장한다. 다중 문서·다중 페이지 병합은 다음 라운드.

    field_value 저장 시 자동 추출 값은 반드시 근거 좌표를 함께 넣어야 한다.
    좌표 없이 저장하면 DB CHECK(field_value_evidence_required_ck)가 거부한다
    — pipeline.py가 저장 전에 이를 먼저 걸러 NOT_FOUND로 강등한다.
    """
    saved = run_extraction(session, job)
    logger.info("job_id=%s 필드 %d건 저장", job.id, saved)


def run_once() -> bool:
    """잡 하나를 처리합니다. 처리했으면 True."""
    with sync_session() as session:
        job = claim_job(session)
        if job is None:
            return False
        logger.info("잡 시작 job_id=%s", job.id)
        try:
            process(session, job)
        except UnsupportedDocumentError as exc:
            session.rollback()
            job = session.get(IngestJob, job.id)
            job.status = JobStatus.FAILED
            job.error_code = "UNSUPPORTED_DOCUMENT"
            job.error_message = str(exc)
            job.finished_at = datetime.now(UTC)
            session.commit()
            logger.warning("잡 실패 job_id=%s: %s", job.id, exc)
        except AiServiceError as exc:
            session.rollback()
            job = session.get(IngestJob, job.id)
            job.status = JobStatus.FAILED
            job.error_code = "AI_SERVICE_ERROR"
            job.error_message = str(exc)[:2000]
            job.finished_at = datetime.now(UTC)
            session.commit()
            logger.warning("잡 실패 job_id=%s: %s", job.id, exc)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            job = session.get(IngestJob, job.id)
            job.status = JobStatus.FAILED
            job.error_code = "EXTRACTION_ERROR"
            job.error_message = str(exc)[:2000]
            job.finished_at = datetime.now(UTC)
            session.commit()
            logger.exception("잡 실패 job_id=%s", job.id)
        else:
            job.status = JobStatus.DONE
            job.progress = 100
            job.finished_at = datetime.now(UTC)
            session.commit()
            logger.info("잡 완료 job_id=%s", job.id)
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("워커 시작 (프로파일=%s)", settings.deployment_profile)
    while not _shutdown:
        if not run_once():
            time.sleep(settings.worker_poll_seconds)
    logger.info("워커 종료")


if __name__ == "__main__":
    main()

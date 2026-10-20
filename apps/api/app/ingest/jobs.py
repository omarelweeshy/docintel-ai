"""Durable ingestion queue on PostgreSQL.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED, so several workers can poll the same table
without taking the same job. A claimed job carries a lease; a worker that crashes stops renewing
it, and once the lease expires another worker may claim the job again. Failed attempts are retried
with exponential backoff up to max_attempts, after which the job and its document are marked
failed. There is at most one unfinished job per document (partial unique index).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, IngestJob


def now() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(attempts: int, base: float = 5.0, cap: float = 300.0) -> float:
    """5 s, 10 s, 20 s, ... capped at 5 minutes."""
    return float(min(cap, base * 2 ** max(0, attempts - 1)))


class JobQueue:
    def __init__(self, session: AsyncSession, lease_seconds: float = 120.0):
        self.session = session
        self.lease_seconds = lease_seconds

    async def enqueue(
        self, document_id: UUID, index_version: str, kind: str = "ingest", max_attempts: int = 3
    ) -> IngestJob:
        """Queue work for a document, or return its unfinished job if one exists (idempotent)."""
        existing = await self.session.scalar(
            select(IngestJob).where(
                IngestJob.document_id == document_id,
                IngestJob.status.in_(("queued", "running")),
            )
        )
        if existing is not None:
            return existing
        job = IngestJob(
            document_id=document_id,
            kind=kind,
            status="queued",
            index_version=index_version,
            attempts=0,
            max_attempts=max_attempts,
            stage="queued",
            progress=0,
            run_after=now(),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim(self, worker: str) -> IngestJob | None:
        """Take the oldest runnable job: queued and due, or running with an expired lease."""
        moment = now()
        job = await self.session.scalar(
            select(IngestJob)
            .where(
                or_(
                    (IngestJob.status == "queued") & (IngestJob.run_after <= moment),
                    (IngestJob.status == "running") & (IngestJob.lease_expires_at < moment),
                )
            )
            .order_by(IngestJob.run_after, IngestJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            await self.session.rollback()
            return None
        if job.status == "running" and job.attempts >= job.max_attempts:
            # Crashed on its last allowed attempt.
            await self._finish_failed(job, "Worker stopped during the final attempt.")
            await self.session.commit()
            return None
        job.status = "running"
        job.attempts += 1
        job.lease_owner = worker
        job.lease_expires_at = moment + timedelta(seconds=self.lease_seconds)
        job.stage = "starting"
        await self.session.commit()
        return job

    async def heartbeat(self, job: IngestJob, stage: str, progress: int) -> bool:
        """Record progress and extend the lease. False if another worker has taken the job."""
        result = await self.session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id, IngestJob.lease_owner == job.lease_owner)
            .values(
                stage=stage,
                progress=max(0, min(100, progress)),
                lease_expires_at=now() + timedelta(seconds=self.lease_seconds),
                updated_at=now(),
            )
        )
        await self.session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def succeed(self, job: IngestJob) -> None:
        job.status = "succeeded"
        job.stage = "done"
        job.progress = 100
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error = None
        job.finished_at = now()
        await self.session.commit()

    async def fail(self, job: IngestJob, error: str, retryable: bool = True) -> None:
        """Retry later with backoff, or give up and mark the document failed."""
        job.last_error = error[:2000]
        job.lease_owner = None
        job.lease_expires_at = None
        if retryable and job.attempts < job.max_attempts:
            job.status = "queued"
            job.stage = "waiting to retry"
            job.run_after = now() + timedelta(seconds=backoff_seconds(job.attempts))
        else:
            await self._finish_failed(job, error)
        await self.session.commit()

    async def _finish_failed(self, job: IngestJob, error: str) -> None:
        job.status = "failed"
        job.stage = "failed"
        job.last_error = error[:2000]
        job.finished_at = now()
        document = await self.session.get(Document, job.document_id)
        if document is not None:
            document.status = "failed"
            document.error_message = error[:2000]

    async def latest(self, document_id: UUID) -> IngestJob | None:
        job: IngestJob | None = await self.session.scalar(
            select(IngestJob)
            .where(IngestJob.document_id == document_id)
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )
        return job

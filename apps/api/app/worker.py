"""Ingestion worker: python -m app.worker

Polls the ingest_jobs table, processes one job at a time and exits cleanly on SIGINT/SIGTERM
(finishing or releasing the current job is left to the lease: an interrupted job becomes
claimable again when its lease expires).
"""

import asyncio
import logging
import os
import signal
import socket
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ParseError, ProviderError
from app.core.middleware import JsonFormatter
from app.ingest.jobs import JobQueue
from app.models.entities import Document, IngestJob
from app.providers.interfaces import AIProvider
from app.rag.chunking import WordChunker
from app.services.embeddings import EmbeddingService
from app.services.ingestion import IngestionService
from app.services.storage import FileStorage

logger = logging.getLogger("app.worker")

# Failures that will not succeed on retry: bad files and documents deleted mid-run.
PERMANENT = (ParseError,)


def worker_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"


async def run_job(
    job: IngestJob,
    factory: async_sessionmaker[AsyncSession],
    provider: AIProvider,
    settings: Settings,
    queue_session: AsyncSession,
) -> None:
    queue = JobQueue(queue_session, settings.job_lease_seconds)

    async def progress(stage: str, percent: int) -> None:
        if not await queue.heartbeat(job, stage, percent):
            raise AppError("lease_lost", "Another worker took over this job.", 409)

    storage = FileStorage(settings.storage_dir, settings.max_upload_bytes)
    async with factory() as session:
        document = await session.get(Document, job.document_id)
        if document is None:
            await queue.fail(job, "Document was deleted.", retryable=False)
            return
        service = IngestionService(
            session,
            storage,
            WordChunker(settings.chunk_words, settings.chunk_overlap, settings.max_chunk_chars),
            EmbeddingService(provider, settings.embedding_dimensions),
            settings,
        )
        try:
            data = storage.path(document.storage_name).read_bytes()
            await service.index(
                document.id,
                data,
                Path(document.storage_name).suffix,
                document.filename,
                progress,
            )
        except AppError as exc:
            await session.rollback()
            if exc.code == "lease_lost":
                logger.warning("ingest_job_lease_lost", extra={"job_id": str(job.id)})
                return
            retryable = not isinstance(exc, PERMANENT) and exc.code != "too_many_chunks"
            # Provider errors (model not loaded, timeouts) are the typical transient failure.
            await queue.fail(
                job, exc.message, retryable=retryable or isinstance(exc, ProviderError)
            )
            logger.warning(
                "ingest_job_failed",
                extra={"job_id": str(job.id), "attempt": job.attempts, "code": exc.code},
            )
            return
        except FileNotFoundError:
            await session.rollback()
            await queue.fail(job, "The stored original is missing.", retryable=False)
            return
        except Exception:
            await session.rollback()
            logger.exception("ingest_job_error", extra={"job_id": str(job.id)})
            await queue.fail(job, "Processing failed unexpectedly.", retryable=True)
            return
    await queue.succeed(job)
    logger.info("ingest_job_succeeded", extra={"job_id": str(job.id), "attempt": job.attempts})


async def run_once(
    factory: async_sessionmaker[AsyncSession],
    provider: AIProvider,
    settings: Settings,
    name: str,
) -> bool:
    """Claim and process at most one job. Returns False when nothing was runnable."""
    async with factory() as queue_session:
        job = await JobQueue(queue_session, settings.job_lease_seconds).claim(name)
        if job is None:
            return False
        await run_job(job, factory, provider, settings, queue_session)
        return True


async def main() -> None:
    from app.core.database import engine, session_factory
    from app.providers.factory import create_provider

    settings = get_settings()
    provider = create_provider(settings)
    name = worker_name()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, lambda *_: stop.set())
    logger.info("worker_started", extra={"worker": name})
    try:
        while not stop.is_set():
            try:
                worked = await run_once(session_factory, provider, settings, name)
            except Exception:
                logger.exception("worker_loop_error")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await provider.close()
        await engine.dispose()
        logger.info("worker_stopped", extra={"worker": name})


if __name__ == "__main__":
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())

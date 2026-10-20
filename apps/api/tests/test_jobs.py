"""Durable ingestion: queue semantics, crash recovery and the worker, against real PostgreSQL."""

import io
import json
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import Headers

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.ingest.jobs import JobQueue, backoff_seconds, now
from app.main import app
from app.models.entities import Document, DocumentChunk, IngestJob, Workspace
from app.rag.chunking import WordChunker
from app.routers.api import get_provider
from app.services.embeddings import EmbeddingService
from app.services.ingestion import IngestionService, index_version
from app.services.storage import FileStorage
from app.worker import run_once
from tests.test_integration import db  # noqa: F401

pytestmark = pytest.mark.integration


def provider() -> AsyncMock:
    mock = AsyncMock()
    mock.embed.side_effect = lambda texts, purpose="document": [[1.0] + [0.0] * 1023 for _ in texts]
    return mock


def upload(data: bytes = b"Retention is thirty days.", name: str = "policy.txt") -> UploadFile:
    return UploadFile(
        io.BytesIO(data), filename=name, headers=Headers({"content-type": "text/plain"})
    )


async def queued_document(db, tmp_path, settings, data=b"Retention is thirty days."):  # type: ignore[no-untyped-def]  # noqa: F811
    workspace = Workspace(id=uuid4(), name="Jobs")
    db.add(workspace)
    await db.commit()
    db.info.setdefault("workspaces", []).append(workspace.id)
    service = IngestionService(
        db,
        FileStorage(tmp_path, 100000),
        WordChunker(),
        EmbeddingService(provider(), 1024),
        settings,
    )
    document, job = await service.enqueue(workspace.id, upload(data))
    return workspace, document, job


def test_backoff_doubles_and_caps() -> None:
    assert [backoff_seconds(n) for n in (1, 2, 3)] == [5.0, 10.0, 20.0]
    assert backoff_seconds(20) == 300.0


async def test_enqueue_is_idempotent_per_document(db, tmp_path):  # noqa: F811
    settings = Settings(storage_dir=tmp_path)
    _, document, job = await queued_document(db, tmp_path, settings)
    again = await JobQueue(db).enqueue(document.id, index_version(settings))
    assert again.id == job.id
    assert document.status == "processing" and job.status == "queued"


async def test_worker_ingests_a_queued_document(db, tmp_path):  # noqa: F811
    settings = Settings(storage_dir=tmp_path, worker_poll_seconds=0.1)
    _, document, job = await queued_document(db, tmp_path, settings)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    assert await run_once(factory, provider(), settings, "worker-a")
    async with factory() as session:
        stored = await session.get(Document, document.id)
        finished = await session.get(IngestJob, job.id)
        chunks = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
        )
    assert stored is not None and stored.status == "ready"
    assert stored.index_version == index_version(settings)
    assert finished is not None and finished.status == "succeeded" and finished.progress == 100
    assert chunks == 1
    # Nothing left to do.
    assert not await run_once(factory, provider(), settings, "worker-a")


async def test_crashed_worker_lease_expires_and_job_is_reclaimed(db, tmp_path):  # noqa: F811
    settings = Settings(storage_dir=tmp_path)
    _, document, job = await queued_document(db, tmp_path, settings)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as session:
        claimed = await JobQueue(session, lease_seconds=60).claim("crashing-worker")
        assert claimed is not None and claimed.id == job.id and claimed.attempts == 1
    # A second worker cannot take a job whose lease is still valid.
    async with factory() as session:
        assert await JobQueue(session).claim("worker-b") is None
    # The first worker "crashes": its lease runs out.
    async with factory() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(lease_expires_at=now() - timedelta(seconds=1))
        )
        await session.commit()
    assert await run_once(factory, provider(), settings, "worker-b")
    async with factory() as session:
        recovered = await session.get(IngestJob, job.id)
        stored = await session.get(Document, document.id)
    assert recovered is not None and recovered.status == "succeeded" and recovered.attempts == 2
    assert stored is not None and stored.status == "ready"


async def test_transient_failures_retry_with_backoff_then_fail(db, tmp_path):  # noqa: F811
    settings = Settings(storage_dir=tmp_path, job_max_attempts=2)
    _, document, job = await queued_document(db, tmp_path, settings)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    broken = AsyncMock()
    broken.embed.side_effect = RuntimeError("model not loaded")
    assert await run_once(factory, broken, settings, "w")
    async with factory() as session:
        waiting = await session.get(IngestJob, job.id)
        assert waiting is not None and waiting.status == "queued" and waiting.attempts == 1
        assert waiting.run_after > now()
        # Not due yet, so nothing is claimable.
        assert await JobQueue(session).claim("w") is None
        await session.execute(
            update(IngestJob).where(IngestJob.id == job.id).values(run_after=now())
        )
        await session.commit()
    assert await run_once(factory, broken, settings, "w")
    async with factory() as session:
        final = await session.get(IngestJob, job.id)
        stored = await session.get(Document, document.id)
    assert final is not None and final.status == "failed" and final.attempts == 2
    assert stored is not None and stored.status == "failed" and stored.error_message


async def test_unparseable_files_fail_without_retry(db, tmp_path):  # noqa: F811
    settings = Settings(storage_dir=tmp_path)
    _, document, job = await queued_document(db, tmp_path, settings, data=b"   ")
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    assert await run_once(factory, provider(), settings, "w")
    async with factory() as session:
        final = await session.get(IngestJob, job.id)
    assert final is not None and final.status == "failed" and final.attempts == 1


async def test_queue_mode_http_flow_and_reindex(db, tmp_path):  # noqa: F811
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def session_override():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    settings = Settings(storage_dir=tmp_path, ingestion_mode="queue")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = provider
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            workspace_id = (await client.post("/workspaces", json={"name": "Q"})).json()["id"]
            db.info.setdefault("workspaces", []).append(UUID(workspace_id))
            response = await client.post(
                "/documents",
                data={"workspace_id": workspace_id},
                files={"file": ("p.txt", io.BytesIO(b"Thirty days."), "text/plain")},
            )
            assert response.status_code == 202
            body = response.json()
            assert body["document"]["status"] == "processing"
            assert body["job"]["status"] == "queued"
            document_id = body["document"]["id"]
            job_url = f"/documents/{document_id}/job?workspace_id={workspace_id}"
            assert (await client.get(job_url)).json()["stage"] == "queued"
            assert await run_once(factory, provider(), settings, "w")
            assert (await client.get(job_url)).json()["status"] == "succeeded"
            # Nothing to reindex while settings are unchanged ...
            reindex = await client.post(f"/workspaces/{workspace_id}/reindex")
            assert reindex.json()["queued"] == 0
            # ... but a chunker change makes the document stale.
            app.dependency_overrides[get_settings] = lambda: settings.model_copy(
                update={"chunking": "structure"}
            )
            stale = (await client.post(f"/workspaces/{workspace_id}/reindex")).json()
            assert stale["queued"] == 1 and stale["index_version"].startswith("structure_v1")
            job = (await client.get(job_url)).json()
            assert job["kind"] == "reindex" and job["status"] == "queued"
            assert json.dumps(job)  # serialisable
    finally:
        app.dependency_overrides.clear()

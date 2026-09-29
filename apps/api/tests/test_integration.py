"""Run against a disposable migrated PostgreSQL/pgvector database, never production."""

import io
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Document, DocumentChunk, Workspace
from app.rag.chunking import WordChunker
from app.rag.retrieval import VectorRetriever
from app.repositories.catalog import CatalogRepository
from app.routers.api import delete_document, delete_workspace
from app.services.embeddings import EmbeddingService
from app.services.ingestion import IngestionService
from app.services.storage import FileStorage

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; PostgreSQL integration tests require pgvector")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
        # Only remove this test's UUID workspaces, not arbitrary database data.
        for workspace in list(session.info.get("workspaces", [])):
            existing = await session.get(Workspace, workspace)
            if existing:
                await session.delete(existing)
        await session.commit()
    await engine.dispose()


async def workspace(db):
    item = Workspace(id=uuid4(), name="Integration test")
    db.add(item)
    await db.commit()
    db.info.setdefault("workspaces", []).append(item.id)
    return item


def service(db, tmp_path, provider):
    settings = Settings(storage_dir=tmp_path)
    return IngestionService(
        db, FileStorage(tmp_path, 10000), WordChunker(), EmbeddingService(provider, 1024), settings
    )


def file():
    return UploadFile(
        io.BytesIO(b"Retention is thirty days."),
        filename="policy.txt",
        headers=Headers({"content-type": "text/plain"}),
    )


async def test_upload_duplicate_scope_retrieval_and_delete(db, tmp_path):
    a, b = await workspace(db), await workspace(db)
    provider = AsyncMock()
    provider.embed.side_effect = lambda texts, purpose="document": [
        [1.0] + [0.0] * 1023 for _ in texts
    ]
    ingestion = service(db, tmp_path, provider)
    document = await ingestion.upload(a.id, file())
    assert document.status == "ready"
    assert document.chunk_count == 1
    with pytest.raises(AppError) as duplicate:
        await ingestion.upload(a.id, file())
    assert duplicate.value.status == 409
    # Rollback expires ORM instances; explicitly reload before reusing this test session.
    await db.refresh(a)
    await db.refresh(b)
    await db.refresh(document)
    document_b = await ingestion.upload(b.id, file())
    assert document_b.id != document.id
    retrieval = VectorRetriever(db, EmbeddingService(provider, 1024), Settings())
    results = await retrieval.retrieve(a.id, "retention")
    assert {r.document_id for r in results} == {document.id}
    assert await retrieval.retrieve(a.id, "retention", [document_b.id]) == []
    with pytest.raises(AppError):
        await CatalogRepository(db).document(b.id, document.id)
    storage_path = tmp_path / document.storage_name
    document_id = document.id
    await delete_document(document_id, a.id, db, Settings(storage_dir=tmp_path))
    assert not storage_path.exists()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        == 0
    )
    assert await retrieval.retrieve(a.id, "retention") == []


async def test_provider_failure_has_no_partial_vectors(db, tmp_path):
    a = await workspace(db)
    provider = AsyncMock()
    provider.embed.side_effect = RuntimeError("private provider error")
    document = await service(db, tmp_path, provider).upload(a.id, file())
    assert document.status == "failed"
    assert "private" not in document.error_message
    assert (
        await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
        )
        == 0
    )
    assert await db.get(Document, document.id)


async def test_workspace_delete_removes_originals_and_relational_data(db, tmp_path):
    item = await workspace(db)
    provider = AsyncMock()
    provider.embed.return_value = [[1.0] + [0.0] * 1023]
    document = await service(db, tmp_path, provider).upload(item.id, file())
    original = tmp_path / document.storage_name
    assert original.is_file()

    await delete_workspace(item.id, db, Settings(storage_dir=tmp_path))

    assert not original.exists()
    assert await db.get(Workspace, item.id) is None
    assert (
        await db.scalar(
            select(func.count()).select_from(Document).where(Document.id == document.id)
        )
        == 0
    )

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.ingest.chunking import StructureChunker, table_chunks
from app.ingest.jobs import JobQueue
from app.ingest.structure import parse_blocks
from app.models.entities import Document, DocumentChunk, IngestJob
from app.rag.chunking import Chunk, Chunker
from app.repositories.catalog import CatalogRepository
from app.services.embeddings import EmbeddingService
from app.services.parsing import parse_document
from app.services.storage import FileStorage

logger = logging.getLogger(__name__)


EMBED_BATCH = 32
ProgressCallback = Callable[[str, int], Awaitable[None]]


def index_version(settings: Settings) -> str:
    """Identifies how a document's chunks were built. A change means it needs a reindex."""
    if settings.chunking == "structure":
        chunker = f"structure_v1-{settings.chunk_target_words}"
    elif settings.chunking == "words_tables":
        chunker = f"words_tables_v1-{settings.chunk_words}-{settings.chunk_overlap}"
    else:
        chunker = f"words_v1-{settings.chunk_words}-{settings.chunk_overlap}"
    return f"{chunker}:{settings.embedding_model}:{settings.embedding_dimensions}"


def split_document(
    data: bytes, extension: str, chunker: Chunker, settings: Settings
) -> tuple[list[Chunk], int | None]:
    """Parse and chunk with the configured strategy. Runs in a worker thread (CPU-bound)."""
    if settings.chunking == "structure":
        blocks, page_count = parse_blocks(
            data, extension, settings.max_document_chars, settings.max_pages
        )
        target = settings.chunk_target_words
        chunker_ = StructureChunker(target, max_words=max(300, target * 3 // 2))
        return chunker_.split(blocks), page_count
    parsed = parse_document(data, extension, settings.max_document_chars, settings.max_pages)
    chunks = chunker.split(parsed.pages)
    if settings.chunking == "words_tables":
        # Keep the word windows and add every detected table as extra row-based chunks.
        blocks, _ = parse_blocks(data, extension, settings.max_document_chars, settings.max_pages)
        chunks += table_chunks(blocks, start_index=len(chunks))
    return chunks, parsed.page_count


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        chunker: Chunker,
        embeddings: EmbeddingService,
        settings: Settings,
    ):
        self.session = session
        self.storage = storage
        self.chunker = chunker
        self.embeddings = embeddings
        self.settings = settings
        self.repo = CatalogRepository(session)

    async def register(self, workspace_id: UUID, file: UploadFile) -> tuple[Document, bytes]:
        """Validate and store an upload and create its document row (status "processing")."""
        await self.repo.workspace(workspace_id)
        stored = await self.storage.save(file)
        document = Document(
            id=uuid4(),
            workspace_id=workspace_id,
            filename=stored.filename,
            storage_name=stored.name,
            content_type=stored.content_type,
            file_size=stored.size,
            sha256=stored.sha256,
            status="processing",
            chunk_count=0,
        )
        try:
            if await self.repo.duplicate(workspace_id, stored.sha256):
                raise AppError(
                    "duplicate_document", "This file already exists in the workspace.", 409
                )
            self.session.add(document)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            self.storage.delete(stored.name)
            raise AppError(
                "duplicate_document", "This file already exists in the workspace.", 409
            ) from exc
        except Exception:
            await self.session.rollback()
            self.storage.delete(stored.name)
            raise
        return document, stored.data

    async def index(
        self,
        document_id: UUID,
        data: bytes,
        extension: str,
        filename: str,
        progress: ProgressCallback | None = None,
    ) -> Document:
        """Parse, chunk, embed and store a document's chunks, replacing any earlier chunks (so a
        retried or reindexed job is idempotent). Raises on failure; callers decide what to record.
        """
        if progress:
            await progress("parsing", 5)
        chunks, page_count = await run_in_threadpool(
            split_document, data, extension, self.chunker, self.settings
        )
        if len(chunks) > self.settings.max_chunks:
            raise AppError("too_many_chunks", "Document exceeds the chunk limit.", 422)
        texts = [chunk.text for chunk in chunks]
        if progress is None:
            vectors = await self.embeddings.embed(texts)
        else:
            # Batches let a worker report progress and renew its lease on long documents.
            vectors = []
            for start in range(0, len(texts), EMBED_BATCH):
                vectors.extend(await self.embeddings.embed(texts[start : start + EMBED_BATCH]))
                done = min(len(texts), start + EMBED_BATCH)
                await progress("embedding", 10 + int(85 * done / max(1, len(texts))))
        # Lock only for finalization. Concurrent deletion cancels indexing safely.
        current = await self.session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if current is None:
            raise AppError("document_deleted", "Document was deleted during processing.", 409)
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        self.session.add_all(
            [
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk.index,
                    page_number=chunk.page_number,
                    text=chunk.text,
                    embedding=vector,
                    chunk_metadata={
                        "filename": filename,
                        "strategy": "page_words_v1",
                        **chunk.metadata,
                    },
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        current.page_count = page_count
        current.chunk_count = len(chunks)
        current.embedding_model = self.settings.embedding_model
        current.index_version = index_version(self.settings)
        current.status = "ready"
        current.error_message = None
        current.processed_at = datetime.now(UTC)
        await self.session.commit()
        return current

    async def upload(self, workspace_id: UUID, file: UploadFile) -> Document:
        """Inline mode: register and index within the request (original behaviour)."""
        document, data = await self.register(workspace_id, file)
        document_id = document.id
        try:
            return await self.index(
                document_id, data, Path(document.storage_name).suffix, document.filename
            )
        except (Exception, asyncio.CancelledError) as exc:
            await self.session.rollback()
            current = await self.session.get(Document, document_id)
            if current:
                current.status = "failed"
                current.error_message = (
                    exc.message
                    if isinstance(exc, AppError)
                    else "Processing interrupted or failed. Delete the document and upload again."
                )
                await self.session.commit()
            logger.warning("ingestion_failed", extra={"document_id": str(document_id)})
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, AppError) and exc.code == "document_deleted":
                raise
            if current:
                return current
            raise AppError("ingestion_failed", "Document processing failed.", 500) from exc

    async def enqueue(self, workspace_id: UUID, file: UploadFile) -> tuple[Document, IngestJob]:
        """Queue mode: register the upload and queue an ingestion job for the worker."""
        document, _ = await self.register(workspace_id, file)
        job = await JobQueue(self.session).enqueue(
            document.id, index_version(self.settings), max_attempts=self.settings.job_max_attempts
        )
        await self.session.commit()
        return document, job

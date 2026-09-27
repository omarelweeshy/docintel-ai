import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Document, DocumentChunk
from app.rag.chunking import Chunker
from app.repositories.catalog import CatalogRepository
from app.services.embeddings import EmbeddingService
from app.services.parsing import parse_document
from app.services.storage import FileStorage

logger = logging.getLogger(__name__)


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

    async def upload(self, workspace_id: UUID, file: UploadFile) -> Document:
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
        document_id = document.id
        try:
            parsed = await run_in_threadpool(
                parse_document,
                stored.data,
                Path(stored.name).suffix,
                self.settings.max_document_chars,
                self.settings.max_pages,
            )
            chunks = await run_in_threadpool(self.chunker.split, parsed.pages)
            if len(chunks) > self.settings.max_chunks:
                raise AppError("too_many_chunks", "Document exceeds the chunk limit.", 422)
            vectors = await self.embeddings.embed([chunk.text for chunk in chunks])
            # Lock only for finalization. Concurrent deletion cancels indexing safely.
            current = await self.session.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if current is None:
                raise AppError("document_deleted", "Document was deleted during processing.", 409)
            self.session.add_all(
                [
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.index,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        embedding=vector,
                        chunk_metadata={"filename": stored.filename, "strategy": "page_words_v1"},
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
            )
            current.page_count = parsed.page_count
            current.chunk_count = len(chunks)
            current.embedding_model = self.settings.embedding_model
            current.status = "ready"
            current.processed_at = datetime.now(UTC)
            await self.session.commit()
            return current
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

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Document, DocumentChunk
from app.services.embeddings import EmbeddingService


@dataclass(frozen=True)
class Source:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity: float


class Retriever(Protocol):
    async def retrieve(
        self, workspace_id: UUID, question: str, document_ids: list[UUID] | None = None
    ) -> list[Source]: ...


class VectorRetriever:
    def __init__(self, session: AsyncSession, embeddings: EmbeddingService, settings: Settings):
        self.session = session
        self.embeddings = embeddings
        self.settings = settings

    async def retrieve(
        self, workspace_id: UUID, question: str, document_ids: list[UUID] | None = None
    ) -> list[Source]:
        filters = [Document.workspace_id == workspace_id, Document.status == "ready"]
        if document_ids is not None:
            filters.append(Document.id.in_(document_ids))
        # No paid embedding request when this workspace has no eligible documents.
        models = list(
            await self.session.scalars(select(Document.embedding_model).where(*filters).distinct())
        )
        if not models:
            return []
        if any(model != self.settings.embedding_model for model in models):
            raise AppError(
                "reindex_required", "Embedding model changed. Reindex documents first.", 409
            )
        vector = (await self.embeddings.embed([question], "query"))[0]
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = (
            await self.session.execute(
                select(DocumentChunk, Document.filename, distance.label("distance"))
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(*filters, distance <= 1 - self.settings.min_similarity)
                .order_by(distance, DocumentChunk.id)
                .limit(self.settings.top_k)
            )
        ).all()
        return [
            Source(chunk.id, chunk.document_id, filename, chunk.page_number, chunk.text, 1 - score)
            for chunk, filename, score in rows
        ]

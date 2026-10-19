from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Document, DocumentChunk
from app.observability.trace import Candidate, current_trace, traced_stage
from app.retrieval.filters import RetrievalFilters
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
        self,
        workspace_id: UUID,
        question: str,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[Source]: ...


class VectorRetriever:
    def __init__(self, session: AsyncSession, embeddings: EmbeddingService, settings: Settings):
        self.session = session
        self.embeddings = embeddings
        self.settings = settings

    async def retrieve(
        self,
        workspace_id: UUID,
        question: str,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[Source]:
        selected = filters or RetrievalFilters()
        if document_ids is not None:
            selected = replace(selected, document_ids=document_ids)
        conditions = selected.conditions(workspace_id)
        doc_conditions = [Document.workspace_id == workspace_id, Document.status == "ready"]
        if selected.document_ids is not None:
            doc_conditions.append(Document.id.in_(selected.document_ids))
        # No paid embedding request when this workspace has no eligible documents.
        models = list(
            await self.session.scalars(
                select(Document.embedding_model).where(*doc_conditions).distinct()
            )
        )
        if not models:
            return []
        if any(model != self.settings.embedding_model for model in models):
            raise AppError(
                "reindex_required", "Embedding model changed. Reindex documents first.", 409
            )
        with traced_stage("embed_query"):
            vector = (await self.embeddings.embed([question], "query"))[0]
        distance = DocumentChunk.embedding.cosine_distance(vector)
        with traced_stage("vector_search"):
            rows = (
                await self.session.execute(
                    select(DocumentChunk, Document.filename, distance.label("distance"))
                    .join(Document, Document.id == DocumentChunk.document_id)
                    # Embedding cosine scores are not calibrated confidence values. Return the
                    # nearest candidates and let the grounded generator decide whether they
                    # contain enough evidence. A fixed cutoff rejected valid overview queries.
                    .where(*conditions)
                    .order_by(distance, DocumentChunk.id)
                    .limit(self.settings.top_k)
                )
            ).all()
        if (trace := current_trace()) is not None:
            trace.candidates["vector"] = [
                Candidate(str(chunk.id), rank, round(1 - score, 4))
                for rank, (chunk, _, score) in enumerate(rows, 1)
            ]
        return [
            Source(chunk.id, chunk.document_id, filename, chunk.page_number, chunk.text, 1 - score)
            for chunk, filename, score in rows
        ]


def build_retriever(
    session: AsyncSession, embeddings: EmbeddingService, settings: Settings
) -> Retriever:
    """The retriever selected by settings.retrieval_mode, returning retrieval_depth chunks."""
    settings = settings.model_copy(update={"top_k": max(settings.top_k, settings.retrieval_depth)})
    if settings.retrieval_mode == "hybrid":
        from app.retrieval.hybrid import HybridRetriever

        return HybridRetriever(session, embeddings, settings)
    return VectorRetriever(session, embeddings, settings)

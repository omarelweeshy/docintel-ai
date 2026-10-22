import asyncio
from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.entities import Document, DocumentChunk
from app.observability.trace import Candidate, current_trace, traced_stage
from app.rag.retrieval import Source
from app.retrieval.filters import RetrievalFilters
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.keyword import TextConfig, keyword_search
from app.retrieval.rerank import get_reranker, rerank_order
from app.retrieval.vector import vector_search
from app.services.embeddings import EmbeddingService


class HybridRetriever:
    """Vector search plus keyword search over the 'english' and 'simple' text configurations,
    merged by reciprocal rank fusion. Each retriever contributes its top `candidate_pool` chunks."""

    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingService,
        settings: Settings,
        keyword_configs: tuple[TextConfig, ...] | None = None,
        use_vector: bool = True,
    ):
        self.session = session
        self.embeddings = embeddings
        self.settings = settings
        self.keyword_configs: tuple[TextConfig, ...] = keyword_configs or (
            ("english", "simple") if settings.identifier_search else ("english",)
        )
        self.use_vector = use_vector

    async def retrieve(
        self,
        workspace_id: UUID,
        question: str,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[Source]:
        filters = filters or RetrievalFilters()
        if document_ids is not None:
            filters = replace(filters, document_ids=document_ids)
        conditions = filters.conditions(workspace_id)
        doc_conditions = conditions[:2] + (
            [Document.id.in_(filters.document_ids)] if filters.document_ids is not None else []
        )
        models = list(
            await self.session.scalars(
                select(Document.embedding_model).where(*doc_conditions).distinct()
            )
        )
        if not models:
            return []
        if self.use_vector and any(m != self.settings.embedding_model for m in models):
            raise AppError(
                "reindex_required", "Embedding model changed. Reindex documents first.", 409
            )
        pool = self.settings.candidate_pool
        lists: dict[str, list[tuple[DocumentChunk, str, float]]] = {}
        if self.use_vector:
            with traced_stage("embed_query"):
                vector = (await self.embeddings.embed([question], "query"))[0]
            with traced_stage("vector_search"):
                lists["vector"] = await vector_search(self.session, conditions, vector, pool)
        for config in self.keyword_configs:
            with traced_stage(f"keyword_{config}"):
                lists[f"keyword_{config}"] = await keyword_search(
                    self.session, conditions, question, config, pool
                )
        with traced_stage("fusion"):
            fused = reciprocal_rank_fusion(
                [[chunk.id for chunk, _, _ in rows] for rows in lists.values()],
                k=self.settings.rrf_k,
            )
        by_id = {
            chunk.id: (chunk, filename) for rows in lists.values() for chunk, filename, _ in rows
        }
        if self.settings.reranker != "none" and fused:
            fused = await self._rerank(question, fused, by_id)
        if (trace := current_trace()) is not None:
            for name, rows in lists.items():
                trace.candidates[name] = [
                    Candidate(str(chunk.id), rank, round(score, 4))
                    for rank, (chunk, _, score) in enumerate(rows, 1)
                ]
            trace.candidates["fused"] = [
                Candidate(str(chunk_id), rank, round(score, 5))
                for rank, (chunk_id, score) in enumerate(fused[: self.settings.top_k], 1)
            ]
        return [
            Source(chunk.id, chunk.document_id, filename, chunk.page_number, chunk.text, score)
            for chunk_id, score in fused[: self.settings.top_k]
            for chunk, filename in [by_id[chunk_id]]
        ]

    async def _rerank(
        self,
        question: str,
        fused: list[tuple[UUID, float]],
        by_id: dict[UUID, tuple[DocumentChunk, str]],
    ) -> list[tuple[UUID, float]]:
        """Reorder the first `rerank_candidates` fused chunks with the configured cross-encoder.
        Chunks below that depth keep their fused order after the reranked ones."""
        head = fused[: self.settings.rerank_candidates]
        passages = [by_id[chunk_id][0].text for chunk_id, _ in head]
        with traced_stage("rerank"):
            reranker = await asyncio.to_thread(get_reranker, self.settings.reranker)
            order = await asyncio.to_thread(rerank_order, reranker, question, passages)
        reranked = [head[i] for i in order] + fused[len(head) :]
        if (trace := current_trace()) is not None:
            trace.candidates["reranked"] = [
                Candidate(str(chunk_id), rank, round(score, 5))
                for rank, (chunk_id, score) in enumerate(reranked[: self.settings.top_k], 1)
            ]
        return reranked

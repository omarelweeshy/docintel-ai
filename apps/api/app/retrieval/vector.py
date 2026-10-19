from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk


async def vector_search(
    session: AsyncSession,
    conditions: list[ColumnElement[bool]],
    vector: list[float],
    limit: int,
) -> list[tuple[DocumentChunk, str, float]]:
    """Nearest chunks by cosine distance. Returns (chunk, filename, cosine similarity)."""
    distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")
    rows = (
        await session.execute(
            select(DocumentChunk, Document.filename, distance)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*conditions)
            .order_by(distance, DocumentChunk.id)
            .limit(limit)
        )
    ).all()
    return [(chunk, filename, 1 - float(d)) for chunk, filename, d in rows]

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.entities import Conversation, Document, Message, Workspace
from app.schemas.api import Stats


class CatalogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def workspace(self, workspace_id: UUID) -> Workspace:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise AppError("not_found", "Workspace not found.", 404)
        return workspace

    async def document(self, workspace_id: UUID, document_id: UUID) -> Document:
        document = await self.session.scalar(
            select(Document).where(
                Document.id == document_id, Document.workspace_id == workspace_id
            )
        )
        if document is None:
            raise AppError("not_found", "Document not found in this workspace.", 404)
        return document

    async def duplicate(self, workspace_id: UUID, sha256: str) -> Document | None:
        return cast(
            Document | None,
            await self.session.scalar(
                select(Document).where(
                    Document.workspace_id == workspace_id, Document.sha256 == sha256
                )
            ),
        )

    async def documents(self, workspace_id: UUID, offset: int, limit: int) -> list[Document]:
        await self.workspace(workspace_id)
        return list(
            await self.session.scalars(
                select(Document)
                .where(Document.workspace_id == workspace_id)
                .order_by(Document.created_at.desc(), Document.id)
                .offset(offset)
                .limit(limit)
            )
        )

    async def stats(self, workspace_id: UUID) -> Stats:
        await self.workspace(workspace_id)
        rows = (
            await self.session.execute(
                select(
                    Document.status, func.count(), func.coalesce(func.sum(Document.chunk_count), 0)
                )
                .where(Document.workspace_id == workspace_id)
                .group_by(Document.status)
            )
        ).all()
        counts = {status: count for status, count, _ in rows}
        return Stats(
            documents=sum(counts.values()),
            ready=counts.get("ready", 0),
            processing=counts.get("processing", 0),
            failed=counts.get("failed", 0),
            chunks=sum(chunks for _, _, chunks in rows),
        )

    async def conversation(self, workspace_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.workspace_id == workspace_id
            )
        )
        if conversation is None:
            raise AppError("not_found", "Conversation not found in this workspace.", 404)
        return conversation

    async def messages(self, conversation_id: UUID) -> list[Message]:
        return list(
            await self.session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        )

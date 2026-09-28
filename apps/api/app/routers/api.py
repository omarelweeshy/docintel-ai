import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.errors import AppError
from app.models.entities import Conversation, Document, Message, Workspace
from app.providers.interfaces import AIProvider
from app.rag.chunking import WordChunker
from app.rag.pipeline import RAGPipeline
from app.rag.retrieval import VectorRetriever
from app.repositories.catalog import CatalogRepository
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    DocumentOut,
    MessageOut,
    Stats,
    WorkspaceCreate,
    WorkspaceOut,
)
from app.services.embeddings import EmbeddingService
from app.services.ingestion import IngestionService
from app.services.storage import FileStorage

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
logger = logging.getLogger(__name__)


def get_provider(request: Request) -> AIProvider:
    return request.app.state.provider  # type: ignore[no-any-return]


Provider = Annotated[AIProvider, Depends(get_provider)]


@router.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["operations"])
async def ready(session: Session) -> dict[str, str]:
    await session.execute(text("SELECT 1 FROM workspaces LIMIT 1"))
    return {"status": "ready"}


@router.get("/config", tags=["operations"])
async def public_config(settings: Config) -> dict[str, int | bool | str]:
    return {
        "max_upload_bytes": settings.max_upload_bytes,
        "max_question_chars": settings.max_question_chars,
        "ai_provider": settings.ai_provider,
        "ai_configured": settings.ai_provider == "ollama"
        or bool(settings.openai_api_key.get_secret_value()),
    }


@router.get("/workspaces", response_model=list[WorkspaceOut], tags=["workspaces"])
async def list_workspaces(session: Session) -> list[Workspace]:
    return list(await session.scalars(select(Workspace).order_by(Workspace.created_at)))


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, tags=["workspaces"])
async def create_workspace(body: WorkspaceCreate, session: Session) -> Workspace:
    workspace = Workspace(name=body.name)
    session.add(workspace)
    await session.commit()
    return workspace


@router.get("/workspaces/{workspace_id}/stats", response_model=Stats, tags=["workspaces"])
async def stats(workspace_id: UUID, session: Session) -> Stats:
    return await CatalogRepository(session).stats(workspace_id)


@router.get("/documents", response_model=list[DocumentOut], tags=["documents"])
async def list_documents(
    workspace_id: UUID,
    session: Session,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Document]:
    return await CatalogRepository(session).documents(workspace_id, offset, limit)


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=201,
    tags=["documents"],
    description="Creates and processes one document inline. Inspect status/error_message.",
)
async def upload_document(
    session: Session,
    settings: Config,
    provider: Provider,
    workspace_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> Document:
    try:
        return await IngestionService(
            session,
            FileStorage(settings.storage_dir, settings.max_upload_bytes),
            WordChunker(settings.chunk_words, settings.chunk_overlap, settings.max_chunk_chars),
            EmbeddingService(provider, settings.embedding_dimensions),
            settings,
        ).upload(workspace_id, file)
    finally:
        await file.close()


@router.get("/documents/{document_id}", response_model=DocumentOut, tags=["documents"])
async def document_metadata(document_id: UUID, workspace_id: UUID, session: Session) -> Document:
    return await CatalogRepository(session).document(workspace_id, document_id)


@router.get("/documents/{document_id}/download", tags=["documents"])
async def download(
    document_id: UUID,
    workspace_id: UUID,
    session: Session,
    settings: Config,
) -> FileResponse:
    document = await CatalogRepository(session).document(workspace_id, document_id)
    path = FileStorage(settings.storage_dir, settings.max_upload_bytes).path(document.storage_name)
    if not path.is_file():
        raise AppError("file_missing", "Stored file is unavailable.", 404)
    return FileResponse(path, filename=document.filename, media_type="application/octet-stream")


@router.delete("/documents/{document_id}", status_code=204, tags=["documents"])
async def delete_document(
    document_id: UUID,
    workspace_id: UUID,
    session: Session,
    settings: Config,
) -> Response:
    document = await CatalogRepository(session).document(workspace_id, document_id)
    storage_name = document.storage_name
    await session.delete(document)  # Database foreign key cascades delete all vectors.
    await session.commit()
    try:
        FileStorage(settings.storage_dir, settings.max_upload_bytes).delete(storage_name)
    except OSError as exc:
        logger.error("file_cleanup_failed", extra={"document_id": str(document_id)})
        raise AppError(
            "file_cleanup_failed",
            "Index removed, but file cleanup failed. Administrator cleanup is required.",
            500,
        ) from exc
    return Response(status_code=204)


@router.get("/conversations", response_model=list[ConversationOut], tags=["conversations"])
async def conversations(workspace_id: UUID, session: Session) -> list[Conversation]:
    await CatalogRepository(session).workspace(workspace_id)
    return list(
        await session.scalars(
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id)
            .order_by(Conversation.created_at.desc())
        )
    )


@router.post(
    "/conversations", response_model=ConversationOut, status_code=201, tags=["conversations"]
)
async def create_conversation(body: ConversationCreate, session: Session) -> Conversation:
    await CatalogRepository(session).workspace(body.workspace_id)
    conversation = Conversation(workspace_id=body.workspace_id, title=body.title)
    session.add(conversation)
    await session.commit()
    return conversation


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationDetail, tags=["conversations"]
)
async def conversation_detail(
    conversation_id: UUID,
    workspace_id: UUID,
    session: Session,
) -> ConversationDetail:
    repo = CatalogRepository(session)
    conversation = await repo.conversation(workspace_id, conversation_id)
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in await repo.messages(conversation_id)],
    )


@router.delete("/conversations/{conversation_id}", status_code=204, tags=["conversations"])
async def delete_conversation(
    conversation_id: UUID,
    workspace_id: UUID,
    session: Session,
) -> Response:
    conversation = await CatalogRepository(session).conversation(workspace_id, conversation_id)
    await session.delete(conversation)
    await session.commit()
    return Response(status_code=204)


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    body: ChatRequest,
    session: Session,
    settings: Config,
    provider: Provider,
) -> ChatResponse:
    repo = CatalogRepository(session)
    await repo.conversation(body.workspace_id, body.conversation_id)
    if body.document_ids:
        for document_id in body.document_ids:
            await repo.document(body.workspace_id, document_id)
    # Serialize exchanges in a conversation so history remains ordered.
    await session.execute(
        select(Conversation).where(Conversation.id == body.conversation_id).with_for_update()
    )
    question = body.question[: settings.max_question_chars]
    result = await RAGPipeline(
        VectorRetriever(
            session, EmbeddingService(provider, settings.embedding_dimensions), settings
        ),
        provider,
        settings,
    ).answer(body.workspace_id, question, body.document_ids)
    user_message = Message(conversation_id=body.conversation_id, role="user", content=question)
    session.add(user_message)
    await session.flush()
    # Explicit timestamps prevent transaction-level now() ties between turns.
    from datetime import UTC, datetime

    assistant = Message(
        conversation_id=body.conversation_id,
        role="assistant",
        content=result.answer,
        citations=[c.model_dump(mode="json") for c in result.citations],
        created_at=datetime.now(UTC),
    )
    session.add(assistant)
    await session.commit()
    return result

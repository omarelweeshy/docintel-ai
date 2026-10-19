import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.errors import AppError
from app.models.entities import Conversation, Document, Message, Workspace
from app.observability.trace import Trace, bind_trace
from app.providers.interfaces import AIProvider
from app.rag.chunking import WordChunker
from app.rag.pipeline import RAGPipeline
from app.rag.retrieval import build_retriever
from app.repositories.catalog import CatalogRepository
from app.retrieval.filters import RetrievalFilters
from app.retrieval.query import HistoryTurn, QueryPlanner
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
        "uses_history": settings.query_planning and settings.history_messages > 0,
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


@router.delete("/workspaces/{workspace_id}", status_code=204, tags=["workspaces"])
async def delete_workspace(workspace_id: UUID, session: Session, settings: Config) -> Response:
    workspace = await CatalogRepository(session).workspace(workspace_id)
    storage_names = list(
        await session.scalars(
            select(Document.storage_name).where(Document.workspace_id == workspace_id)
        )
    )
    await session.delete(workspace)
    await session.commit()
    storage = FileStorage(settings.storage_dir, settings.max_upload_bytes)
    failed = False
    for storage_name in storage_names:
        try:
            storage.delete(storage_name)
        except OSError:
            failed = True
            logger.error("workspace_file_cleanup_failed", extra={"workspace_id": str(workspace_id)})
    if failed:
        raise AppError(
            "file_cleanup_failed",
            "Workspace data was removed, but file cleanup requires administrator attention.",
            500,
        )
    return Response(status_code=204)


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


async def prepare_chat(
    body: ChatRequest, session: AsyncSession, settings: Settings, provider: AIProvider
) -> tuple[str, RAGPipeline, RetrievalFilters | None, list[HistoryTurn]]:
    """Checks, locking and pipeline construction shared by /chat and /chat/stream."""
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
    filters = (
        RetrievalFilters(
            file_types=body.filters.file_types,
            page_from=body.filters.page_from,
            page_to=body.filters.page_to,
        )
        if body.filters
        else None
    )
    history: list[HistoryTurn] = []
    if settings.query_planning and settings.history_messages:
        recent = await session.scalars(
            select(Message)
            .where(Message.conversation_id == body.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(settings.history_messages)
        )
        history = [HistoryTurn(m.role, m.content) for m in reversed(list(recent))]
    pipeline = RAGPipeline(
        build_retriever(
            session, EmbeddingService(provider, settings.embedding_dimensions), settings
        ),
        provider,
        settings,
        QueryPlanner(provider, settings.history_messages) if settings.query_planning else None,
    )
    return question, pipeline, filters, history


async def save_exchange(
    session: AsyncSession, conversation_id: UUID, question: str, result: ChatResponse
) -> None:
    user_created_at = datetime.now(UTC)
    session.add(
        Message(
            conversation_id=conversation_id,
            role="user",
            content=question,
            created_at=user_created_at,
        )
    )
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=result.answer,
            citations=[c.model_dump(mode="json") for c in result.citations],
            # Keep the pair ordered even if the host clock has coarse resolution.
            created_at=max(datetime.now(UTC), user_created_at + timedelta(microseconds=1)),
        )
    )
    await session.commit()


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(
    body: ChatRequest,
    session: Session,
    settings: Config,
    provider: Provider,
) -> ChatResponse:
    question, pipeline, filters, history = await prepare_chat(body, session, settings, provider)
    trace = Trace()
    with bind_trace(trace), trace.stage("total"):
        result = await pipeline.answer(
            body.workspace_id, question, body.document_ids, filters, history
        )
    # Ids, scores, timings and token counts only: no question or document text.
    logger.info("rag_trace", extra={"trace": trace.to_dict()})
    await save_exchange(session, body.conversation_id, question, result)
    return result


def sse(event: str, data: object) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    tags=["chat"],
    response_class=StreamingResponse,
    description=(
        "Server-Sent Events. 'stage' reports progress, 'delta' carries provisional answer text "
        "that is not yet validated, 'final' carries the validated answer (same shape as /chat) "
        "and 'error' a safe error. The exchange is saved only after a successful final event."
    ),
)
async def chat_stream(
    body: ChatRequest,
    session: Session,
    settings: Config,
    provider: Provider,
) -> StreamingResponse:
    # Validation errors (unknown conversation or document) still return normal HTTP errors.
    question, pipeline, filters, history = await prepare_chat(body, session, settings, provider)

    async def events() -> AsyncIterator[str]:
        trace = Trace()
        try:
            with bind_trace(trace), trace.stage("total"):
                async for item in pipeline.answer_stream(
                    body.workspace_id, question, body.document_ids, filters, history
                ):
                    if item.event == "final" and isinstance(item.data, ChatResponse):
                        await save_exchange(session, body.conversation_id, question, item.data)
                    yield sse(item.event, item.data)
        except AppError as exc:
            await session.rollback()
            yield sse("error", {"code": exc.code, "message": exc.message})
        except Exception:
            await session.rollback()
            logger.exception("chat_stream_failed")
            yield sse("error", {"code": "internal_error", "message": "Answering failed."})
        finally:
            logger.info("rag_trace", extra={"trace": trace.to_dict()})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

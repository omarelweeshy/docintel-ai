from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class WorkspaceOut(ORMModel):
    id: UUID
    name: str
    created_at: datetime


class DocumentOut(ORMModel):
    id: UUID
    workspace_id: UUID
    filename: str
    content_type: str
    file_size: int
    sha256: str
    status: Literal["processing", "ready", "failed"]
    page_count: int | None
    chunk_count: int
    created_at: datetime
    processed_at: datetime | None
    error_message: str | None


class ConversationCreate(BaseModel):
    workspace_id: UUID
    title: str = Field(default="New conversation", min_length=1, max_length=100)


class ConversationOut(ORMModel):
    id: UUID
    workspace_id: UUID
    title: str
    created_at: datetime


class Citation(BaseModel):
    document_id: UUID
    filename: str
    page_number: int | None
    chunk_id: UUID
    snippet: str


class MessageOut(ORMModel):
    id: UUID
    role: str
    content: str
    citations: list[Citation]
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ChatRequest(BaseModel):
    workspace_id: UUID
    conversation_id: UUID
    question: str = Field(min_length=1, max_length=10000)
    document_ids: list[UUID] | None = Field(default=None, max_length=100)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=12000)
    source_ids: list[str] = Field(max_length=20)
    insufficient_context: bool


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    insufficient_context: bool


class Stats(BaseModel):
    documents: int
    ready: int
    processing: int
    failed: int
    chunks: int

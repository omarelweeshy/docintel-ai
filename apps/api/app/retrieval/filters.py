from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, or_

from app.models.entities import Document, DocumentChunk

FileType = Literal["pdf", "docx", "txt"]
CONTENT_TYPES: dict[FileType, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


@dataclass(frozen=True)
class RetrievalFilters:
    """Metadata filters applied to every retriever before ranking, so filtered-out chunks never
    take a slot in the candidate lists."""

    document_ids: list[UUID] | None = None
    file_types: list[FileType] | None = None
    page_from: int | None = None
    page_to: int | None = None

    def conditions(self, workspace_id: UUID) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [
            Document.workspace_id == workspace_id,
            Document.status == "ready",
        ]
        if self.document_ids is not None:
            conditions.append(Document.id.in_(self.document_ids))
        if self.file_types:
            conditions.append(
                Document.content_type.in_([CONTENT_TYPES[t] for t in self.file_types])
            )
        # Page filters apply to paginated formats only; DOCX and TXT chunks have no page and are
        # kept, otherwise a page range would silently drop every non-PDF document.
        if self.page_from is not None:
            conditions.append(
                or_(
                    DocumentChunk.page_number.is_(None), DocumentChunk.page_number >= self.page_from
                )
            )
        if self.page_to is not None:
            conditions.append(
                or_(DocumentChunk.page_number.is_(None), DocumentChunk.page_number <= self.page_to)
            )
        return conditions

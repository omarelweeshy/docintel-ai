import re
from typing import Literal

from sqlalchemy import ColumnElement, Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk

TextConfig = Literal["english", "simple"]


def any_term_query(config: TextConfig, question: str) -> ColumnElement[str]:
    """plainto_tsquery normalises the question (stemming, stop words) but joins terms with AND,
    which a natural-language question almost never satisfies in one chunk. Rewriting its output to
    OR lets any shared term match; ranking then prefers chunks with more and denser matches."""
    plain = cast(func.plainto_tsquery(config, question), Text)
    return cast(func.replace(plain, " & ", " | "), TSQUERY())


# Tokens with a digit: document numbers, codes, quantities ("800-61r3", "HC-412", "250").
TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.\-/:][A-Za-z0-9]+)*")


def identifiers(question: str) -> list[str]:
    return [t for t in TOKEN.findall(question) if any(c.isdigit() for c in t)]


def identifier_query(question: str) -> ColumnElement[str] | None:
    """'simple' search is restricted to identifier-like tokens, each matched as an exact phrase
    and OR-ed together. PostgreSQL's ranking has no inverse document frequency, so letting common
    words such as "which" or "does" (not removed by 'simple') score would drown the identifiers."""
    found = list(dict.fromkeys(identifiers(question)))[:10]
    if not found:
        return None
    query: ColumnElement[str] = func.phraseto_tsquery("simple", found[0])
    for token in found[1:]:
        query = query.op("||")(func.phraseto_tsquery("simple", token))
    return query


async def keyword_search(
    session: AsyncSession,
    conditions: list[ColumnElement[bool]],
    question: str,
    config: TextConfig,
    limit: int,
) -> list[tuple[DocumentChunk, str, float]]:
    column = DocumentChunk.fts_english if config == "english" else DocumentChunk.fts_simple
    query = any_term_query(config, question) if config == "english" else identifier_query(question)
    if query is None:
        return []
    rank = func.ts_rank_cd(column, query).label("rank")
    rows = (
        await session.execute(
            select(DocumentChunk, Document.filename, rank)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*conditions, column.op("@@")(query))
            .order_by(rank.desc(), DocumentChunk.id)
            .limit(limit)
        )
    ).all()
    return [(chunk, filename, float(score)) for chunk, filename, score in rows]

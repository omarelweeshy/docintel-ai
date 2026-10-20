import re

from app.ingest.structure import Block
from app.rag.chunking import Chunk

SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9•\"(])")


def _words(text: str) -> int:
    return len(text.split())


def _split_long(text: str, max_words: int) -> list[str]:
    """Split an over-long paragraph at sentence ends, falling back to word windows."""
    if _words(text) <= max_words:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in SENTENCE_END.split(text):
        candidate = f"{current} {sentence}".strip()
        if current and _words(candidate) > max_words:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    out: list[str] = []
    for piece in pieces:
        words = piece.split()
        out.extend(" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words))
    return out


class StructureChunker:
    """Pack parsed blocks into small chunks that never cross a heading or a page.

    Each chunk starts with its heading path ("2 Retention periods > 2.1 Clinical records"), so a
    chunk read on its own still says what it is about. Table rows are rendered as self-contained
    "Header: value" lines and are packed like paragraphs, so a table is split only between rows.
    Chunks of one section share a section id in their metadata (the parent for later expansion).
    """

    def __init__(
        self,
        target_words: int = 180,
        max_words: int = 300,
        heading_prefix: bool = True,
        max_chars: int = 6000,
    ):
        if not 20 <= target_words <= max_words:
            raise ValueError("Invalid structure chunk configuration")
        self.target_words = target_words
        self.max_words = max_words
        self.heading_prefix = heading_prefix
        self.max_chars = max_chars

    def split(self, blocks: list[Block]) -> list[Chunk]:
        chunks: list[Chunk] = []
        path: list[tuple[int, str]] = []
        section = 0
        buffer: list[str] = []
        kinds: set[str] = set()
        page: int | None = None

        def flush() -> None:
            nonlocal buffer, kinds
            if not buffer:
                return
            heading = " > ".join(text for _, text in path)
            body = "\n".join(buffer)
            text = f"{heading}\n{body}" if self.heading_prefix and heading else body
            chunks.append(
                Chunk(
                    len(chunks),
                    page,
                    text[: self.max_chars],
                    {
                        "strategy": "structure_v1",
                        "section": heading[:500],
                        "section_id": section,
                        "kinds": sorted(kinds),
                    },
                )
            )
            buffer, kinds = [], set()

        for block in blocks:
            if block.kind == "heading":
                flush()
                while path and path[-1][0] >= block.level:
                    path.pop()
                path.append((block.level, block.text))
                section += 1
                continue
            if block.page != page:
                flush()
                page = block.page
            for piece in _split_long(block.text, self.max_words):
                size = sum(_words(b) for b in buffer)
                if buffer and size + _words(piece) > self.target_words:
                    flush()
                buffer.append(piece)
                kinds.add(block.kind)
        flush()
        return chunks


def table_chunks(blocks: list[Block], start_index: int, max_words: int = 220) -> list[Chunk]:
    """Chunks made only of table rows, prefixed by the nearest heading and the text line just
    before the table (usually its caption). Rows are grouped up to max_words per chunk."""
    chunks: list[Chunk] = []
    heading = ""
    previous_text = ""
    current: str | None = None
    rows: list[str] = []
    page: int | None = None

    def flush() -> None:
        nonlocal rows
        if rows:
            context = " > ".join(x for x in (heading, previous_text) if x)
            body = "\n".join(rows)
            chunks.append(
                Chunk(
                    start_index + len(chunks),
                    page,
                    f"{context}\n{body}" if context else body,
                    {"strategy": "table_rows_v1", "section": heading[:500], "kinds": ["table_row"]},
                )
            )
        rows = []

    for block in blocks:
        if block.kind != "table_row":
            flush()
            current = None
            if block.kind == "heading":
                heading, previous_text = block.text, ""
            elif len(block.text.split()) <= 30:
                previous_text = block.text
            continue
        if block.table != current or block.page != page:
            flush()
            current, page = block.table, block.page
        if rows and sum(len(r.split()) for r in rows) + len(block.text.split()) > max_words:
            flush()
        rows.append(block.text)
    flush()
    return chunks

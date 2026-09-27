from dataclasses import dataclass
from typing import Protocol

from app.services.parsing import Page, normalize_text


@dataclass(frozen=True)
class Chunk:
    index: int
    page_number: int | None
    text: str


class Chunker(Protocol):
    def split(self, pages: list[Page]) -> list[Chunk]: ...


class WordChunker:
    def __init__(self, target: int = 350, overlap: int = 50, max_chars: int = 6000):
        if target <= 0 or not 0 <= overlap < target or max_chars < 1:
            raise ValueError("Invalid chunk configuration")
        self.target = target
        self.overlap = overlap
        self.max_chars = max_chars

    def split(self, pages: list[Page]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for page in pages:
            # Split pathological long tokens as well as bounding normal word windows.
            words = [
                word[i : i + self.max_chars]
                for word in normalize_text(page.text).split()
                for i in range(0, len(word), self.max_chars)
            ]
            start = 0
            while start < len(words):
                end = start
                size = 0
                while end < len(words) and end - start < self.target:
                    added = len(words[end]) + (1 if end > start else 0)
                    if size + added > self.max_chars:
                        break
                    size += added
                    end += 1
                chunks.append(Chunk(len(chunks), page.number, " ".join(words[start:end])))
                if end == len(words):
                    break
                start = max(start + 1, end - self.overlap)
        return chunks

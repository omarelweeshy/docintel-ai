from typing import Literal, Protocol

from app.schemas.api import ModelAnswer


class EmbeddingProvider(Protocol):
    async def embed(
        self, texts: list[str], purpose: Literal["document", "query"] = "document"
    ) -> list[list[float]]: ...


class GenerationProvider(Protocol):
    async def generate(self, system: str, user: str) -> ModelAnswer: ...


class AIProvider(EmbeddingProvider, GenerationProvider, Protocol):
    async def close(self) -> None: ...

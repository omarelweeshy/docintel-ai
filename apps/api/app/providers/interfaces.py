from typing import Protocol

from app.schemas.api import ModelAnswer


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class GenerationProvider(Protocol):
    async def generate(self, system: str, user: str) -> ModelAnswer: ...

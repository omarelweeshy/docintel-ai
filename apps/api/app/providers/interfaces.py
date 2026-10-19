from typing import Literal, Protocol

from pydantic import BaseModel

from app.schemas.api import ModelAnswer


class EmbeddingProvider(Protocol):
    async def embed(
        self, texts: list[str], purpose: Literal["document", "query"] = "document"
    ) -> list[list[float]]: ...


class GenerationProvider(Protocol):
    async def generate(self, system: str, user: str) -> ModelAnswer: ...

    async def generate_structured[M: BaseModel](
        self, system: str, user: str, schema: type[M], purpose: str = "generate"
    ) -> M:
        """Schema-constrained JSON output for auxiliary calls (query planning, checks).
        `purpose` labels token and latency accounting in the request trace."""
        ...


class AIProvider(EmbeddingProvider, GenerationProvider, Protocol):
    async def close(self) -> None: ...

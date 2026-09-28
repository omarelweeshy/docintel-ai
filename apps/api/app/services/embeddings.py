import math
from typing import Literal

from app.core.errors import ProviderError
from app.providers.interfaces import EmbeddingProvider


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider, dimensions: int):
        self.provider = provider
        self.dimensions = dimensions

    async def embed(
        self, texts: list[str], purpose: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await self.provider.embed(texts, purpose)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError() from exc
        if len(vectors) != len(texts) or any(
            len(v) != self.dimensions
            or not all(math.isfinite(x) for x in v)
            or sum(x * x for x in v) == 0
            for v in vectors
        ):
            raise ProviderError("Embedding provider returned invalid vectors.")
        return vectors

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.errors import ProviderError
from app.schemas.api import ModelAnswer


class OpenAIProvider:
    """SDK details stay here; services depend only on the two provider protocols."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: AsyncOpenAI | None = None

    def _client(self) -> AsyncOpenAI:
        if not self.settings.openai_api_key.get_secret_value():
            raise ProviderError("Set OPENAI_API_KEY on the API server to enable AI processing.")
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                timeout=self.settings.provider_timeout_seconds,
                max_retries=1,
            )
        return self.client

    async def close(self) -> None:
        if self.client:
            await self.client.close()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._client()
        vectors: list[list[float]] = []
        try:
            # 16 * 6000 characters bounds request size even for token-dense text.
            for start in range(0, len(texts), 16):
                response = await client.embeddings.create(
                    model=self.settings.embedding_model,
                    dimensions=self.settings.embedding_dimensions,
                    input=texts[start : start + 16],
                )
                vectors.extend(
                    item.embedding for item in sorted(response.data, key=lambda x: x.index)
                )
        except Exception as exc:
            raise ProviderError() from exc
        return vectors

    async def generate(self, system: str, user: str) -> ModelAnswer:
        client = self._client()
        try:
            response = await client.responses.parse(
                model=self.settings.chat_model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text_format=ModelAnswer,
                max_output_tokens=2500,
                store=False,
            )
            if response.output_parsed is None:
                raise ProviderError("The model did not return a valid grounded answer. Try again.")
            return response.output_parsed
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "AI generation failed or returned invalid output. Try again."
            ) from exc

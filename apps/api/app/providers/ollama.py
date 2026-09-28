from typing import Any, Literal

import httpx

from app.core.config import Settings
from app.core.errors import ProviderError
from app.schemas.api import ModelAnswer

QUERY_INSTRUCTION = "Instruct: Given a user question, retrieve passages that answer it.\nQuery: "


class OllamaProvider:
    """Local Ollama adapter. No document or question content is sent to a cloud API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=settings.provider_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self.client.post(path, json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Ollama returned a non-object response")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "Local AI is unavailable. Start Ollama and pull the configured models."
            ) from exc

    async def embed(
        self, texts: list[str], purpose: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        inputs = [QUERY_INSTRUCTION + text if purpose == "query" else text for text in texts]
        data = await self._post(
            "/api/embed",
            {
                "model": self.settings.embedding_model,
                "input": inputs,
                "dimensions": self.settings.embedding_dimensions,
                "truncate": False,
            },
        )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise ProviderError("Local embedding model returned invalid vectors.")
        return embeddings

    async def generate(self, system: str, user: str) -> ModelAnswer:
        schema = ModelAnswer.model_json_schema()
        data = await self._post(
            "/api/chat",
            {
                "model": self.settings.chat_model,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": f"Return JSON matching this schema: {schema}\n\n{user}",
                    },
                ],
                "format": schema,
                "stream": False,
                "think": False,
                "options": {"temperature": 0, "num_ctx": self.settings.ollama_num_ctx},
            },
        )
        try:
            message = data["message"]
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("missing content")
            return ModelAnswer.model_validate_json(message["content"])
        except (KeyError, ValueError) as exc:
            raise ProviderError("Local model returned an invalid grounded answer.") from exc

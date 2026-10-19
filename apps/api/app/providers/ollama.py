import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import ProviderError
from app.observability.trace import current_trace
from app.schemas.api import ModelAnswer

QUERY_INSTRUCTION = "Instruct: Given a user question, retrieve passages that answer it.\nQuery: "


def record_usage(data: dict[str, Any], kind: str) -> None:
    """Copy Ollama's token counts and model load time into the bound trace, if any."""
    trace = current_trace()
    if trace is None:
        return
    for field, suffix in (("prompt_eval_count", "prompt"), ("eval_count", "output")):
        if isinstance(value := data.get(field), int):
            trace.add_tokens(f"{kind}_{suffix}", value)
    if isinstance(load := data.get("load_duration"), int) and load > 0:
        # Nanoseconds. Large values mean a cold model load, which latency reports must show.
        key = f"{kind}_load_ms"
        trace.attributes[key] = round(trace.attributes.get(key, 0.0) + load / 1e6, 1)


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
        record_usage(data, "embed")
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise ProviderError("Local embedding model returned invalid vectors.")
        return embeddings

    def _chat_body(
        self, system: str, user: str, schema: type[BaseModel], stream: bool
    ) -> dict[str, Any]:
        json_schema = schema.model_json_schema()
        return {
            "model": self.settings.chat_model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"Return JSON matching this schema: {json_schema}\n\n{user}",
                },
            ],
            "format": json_schema,
            "stream": stream,
            "think": False,
            "options": {"temperature": 0, "num_ctx": self.settings.ollama_num_ctx},
        }

    async def generate(self, system: str, user: str) -> ModelAnswer:
        return await self.generate_structured(system, user, ModelAnswer)

    async def generate_structured[M: BaseModel](
        self, system: str, user: str, schema: type[M], purpose: str = "generate"
    ) -> M:
        data = await self._post("/api/chat", self._chat_body(system, user, schema, stream=False))
        record_usage(data, purpose)
        try:
            message = data["message"]
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("missing content")
            return schema.model_validate_json(message["content"])
        except (KeyError, ValueError) as exc:
            raise ProviderError("Local model returned an invalid grounded answer.") from exc

    async def generate_stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Stream the raw JSON text of a ModelAnswer as Ollama produces it. The caller parses
        and validates the complete text; partial text is only ever shown as provisional."""
        body = self._chat_body(system, user, ModelAnswer, stream=True)
        try:
            async with self.client.stream("POST", "/api/chat", json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        raise ValueError("Ollama returned a non-object stream line")
                    if data.get("error"):
                        raise ValueError("Ollama stream error")
                    content = (data.get("message") or {}).get("content")
                    if isinstance(content, str) and content:
                        yield content
                    if data.get("done"):
                        record_usage(data, "generate")
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "Local AI is unavailable. Start Ollama and pull the configured models."
            ) from exc

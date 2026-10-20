"""Record and replay provider for the CI eval subset.

In record mode it wraps the real Ollama provider and saves every embedding and generation it
returns. In replay mode it serves those saved outputs and fails on anything unrecorded, so CI runs
the real retrieval, prompting, validation and scoring code with no model present. Replay numbers
show the pipeline and the scorer are deterministic; they say nothing new about model quality.

Fixture keys hash the model name, the purpose and the exact input text, so any change to chunking,
prompts or questions makes the replay fail loudly instead of silently reusing stale outputs.
Vectors are stored as float16 to keep the fixture small. Record mode returns the same rounded
vectors it stores, so the recorded run and every replay see identical inputs.

Chunk ids are random UUIDs that change with every ingestion, so generation prompts are keyed with
ids replaced by their position in the context, and recorded source_ids are stored as positions.
"""

import base64
import gzip
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Literal

from app.core.errors import ProviderError
from app.schemas.api import ModelAnswer


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class ReplayProvider:
    def __init__(
        self,
        path: Path,
        mode: Literal["record", "replay"],
        embed_model: str,
        chat_model: str,
        inner: Any = None,
    ):
        self.path = path
        self.mode = mode
        self.inner = inner
        self.embed_model = embed_model
        self.chat_model = chat_model
        self.embeddings: dict[str, str] = {}
        self.generations: dict[str, dict[str, Any]] = {}
        if mode == "replay" or path.exists():
            data = json.loads(gzip.decompress(path.read_bytes()))
            self.embeddings = data["embeddings"]
            self.generations = data["generations"]
        if mode == "record" and inner is None:
            raise ValueError("record mode needs the real provider")

    async def embed(
        self, texts: list[str], purpose: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        keys = [_key(self.embed_model, purpose, t) for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self.embeddings]
        if missing:
            if self.mode == "replay":
                raise ProviderError(f"Replay fixture has no embedding for {len(missing)} input(s).")
            vectors = await self.inner.embed([texts[i] for i in missing], purpose)
            for i, vector in zip(missing, vectors, strict=True):
                packed = struct.pack(f"<{len(vector)}e", *vector)
                self.embeddings[keys[i]] = base64.b64encode(packed).decode()
        decoded = [base64.b64decode(self.embeddings[k]) for k in keys]
        return [list(struct.unpack(f"<{len(raw) // 2}e", raw)) for raw in decoded]

    async def generate_structured(
        self, system: str, user: str, schema: type[Any], purpose: str = "generate"
    ) -> Any:
        if schema is ModelAnswer:
            return await self.generate(system, user)
        key = _key(self.chat_model, schema.__name__, system, user)
        if key not in self.generations:
            if self.mode == "replay":
                raise ProviderError("Replay fixture has no structured output for this prompt.")
            result = await self.inner.generate_structured(system, user, schema, purpose)
            self.generations[key] = result.model_dump()
        return schema.model_validate(self.generations[key])

    async def generate(self, system: str, user: str) -> ModelAnswer:
        ids = [item["id"] for item in json.loads(user).get("untrusted_context", [])]
        canonical = user
        for position, chunk_id in enumerate(ids):
            canonical = canonical.replace(chunk_id, f"<context {position}>")
        key = _key(self.chat_model, system, canonical)
        if key not in self.generations:
            if self.mode == "replay":
                raise ProviderError("Replay fixture has no generation for this prompt.")
            answer = await self.inner.generate(system, user)
            recorded = answer.model_dump()
            # Positions survive re-ingestion; ids the model invented are kept as-is so the
            # pipeline's citation validation still sees them.
            recorded["source_ids"] = [
                f"<context {ids.index(s)}>" if s in ids else s for s in answer.source_ids
            ]
            self.generations[key] = recorded
        stored = dict(self.generations[key])
        stored["source_ids"] = [
            ids[int(s[9:-1])] if s.startswith("<context ") else s for s in stored["source_ids"]
        ]
        return ModelAnswer.model_validate(stored)

    def save(self) -> None:
        payload = {"embeddings": self.embeddings, "generations": self.generations}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(
            gzip.compress(json.dumps(payload, sort_keys=True).encode(), 9, mtime=0)
        )

    async def close(self) -> None:
        if self.inner is not None:
            await self.inner.close()

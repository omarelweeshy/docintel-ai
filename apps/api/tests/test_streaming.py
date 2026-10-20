import io
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.answer.streaming import partial_json_string
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.rag.pipeline import RAGPipeline
from app.rag.retrieval import Source
from app.routers.api import get_provider
from app.schemas.api import ChatResponse, ModelAnswer
from tests.test_integration import db  # noqa: F401


def test_partial_json_string_decodes_what_has_arrived() -> None:
    assert partial_json_string('{"answer": "Within 30 min') == "Within 30 min"
    assert partial_json_string('{"answer": "a \\"b\\" c", "source_ids"') == 'a "b" c'
    # An escape cut in half is held back until the rest arrives.
    assert partial_json_string('{"answer": "x\\') == "x"
    assert partial_json_string('{"answer": "caf\\u00') == "caf"
    assert partial_json_string('{"answer": "caf\\u00e9"') == "café"
    assert partial_json_string('{"ans') == ""


class StreamingProvider:
    def __init__(self, pieces: list[str]):
        self.pieces = pieces

    async def generate(self, system: str, user: str) -> ModelAnswer:
        raise AssertionError("streaming providers are streamed")

    async def generate_stream(self, system: str, user: str, schema=None) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        context = json.loads(user)["untrusted_context"]
        for piece in self.pieces:
            yield piece.replace("SOURCE", context[0]["id"])


class OneSource:
    def __init__(self, text: str = "Retention is thirty days."):
        self.source = Source(uuid4(), uuid4(), "policy.txt", None, text, 0.9)

    async def retrieve(self, workspace_id, question, document_ids=None, filters=None):  # type: ignore[no-untyped-def]
        return [self.source]


async def test_answer_stream_emits_provisional_text_then_validated_final() -> None:
    pieces = [
        '{"answer": "Thirty',
        ' days.", "source_ids": ["SOURCE"], ',
        '"insufficient_context": false}',
    ]
    pipeline = RAGPipeline(OneSource(), StreamingProvider(pieces), Settings())  # type: ignore[arg-type]
    events = [e async for e in pipeline.answer_stream(uuid4(), "How long?")]
    kinds = [e.event for e in events]
    assert kinds[:2] == ["stage", "stage"] and kinds[-1] == "final"
    assert "".join(e.data["text"] for e in events if e.event == "delta") == "Thirty days."  # type: ignore[index]
    final = events[-1].data
    assert isinstance(final, ChatResponse) and final.citations[0].filename == "policy.txt"


async def test_answer_stream_rejects_invented_citations() -> None:
    pieces = ['{"answer": "x", "source_ids": ["not-a-source"], "insufficient_context": false}']
    pipeline = RAGPipeline(OneSource(), StreamingProvider(pieces), Settings())  # type: ignore[arg-type]
    with pytest.raises(Exception, match="outside the retrieved context"):
        _ = [e async for e in pipeline.answer_stream(uuid4(), "How long?")]


def parse_sse(text: str) -> list[tuple[str, object]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.mark.integration
async def test_stream_endpoint_saves_the_exchange(db, tmp_path):  # noqa: F811
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def session_override():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    provider = AsyncMock()
    provider.embed.side_effect = lambda texts, purpose="document": [
        [1.0] + [0.0] * 1023 for _ in texts
    ]

    async def generate(system, user):  # type: ignore[no-untyped-def]
        context = json.loads(user)["untrusted_context"]
        return ModelAnswer(
            answer="Thirty days.", source_ids=[context[0]["id"]], insufficient_context=False
        )

    # AsyncMock has no class-level generate_stream, so this exercises the non-streaming fallback
    # that the OpenAI provider uses.
    provider.generate.side_effect = generate
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path)
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            workspace_id = (await client.post("/workspaces", json={"name": "SSE"})).json()["id"]
            db.info.setdefault("workspaces", []).append(UUID(workspace_id))
            await client.post(
                "/documents",
                data={"workspace_id": workspace_id},
                files={"file": ("p.txt", io.BytesIO(b"Retention is thirty days."), "text/plain")},
            )
            conversation = (
                await client.post(
                    "/conversations", json={"workspace_id": workspace_id, "title": "SSE"}
                )
            ).json()
            body = {
                "workspace_id": workspace_id,
                "conversation_id": conversation["id"],
                "question": "How long?",
            }
            response = await client.post("/chat/stream", json=body)
            assert response.headers["content-type"].startswith("text/event-stream")
            events = parse_sse(response.text)
            assert [e for e, _ in events][-1] == "final"
            assert events[-1][1]["answer"] == "Thirty days."  # type: ignore[index]
            url = f"/conversations/{conversation['id']}?workspace_id={workspace_id}"
            messages = (await client.get(url)).json()["messages"]
            assert [m["role"] for m in messages] == ["user", "assistant"]
            provider.generate.side_effect = RuntimeError("secret failure")
            failed = parse_sse((await client.post("/chat/stream", json=body)).text)
            assert failed[-1][0] == "error" and "secret" not in json.dumps(failed)
            assert len((await client.get(url)).json()["messages"]) == 2
            missing = {**body, "conversation_id": str(uuid4())}
            assert (await client.post("/chat/stream", json=missing)).status_code == 404
    finally:
        app.dependency_overrides.clear()

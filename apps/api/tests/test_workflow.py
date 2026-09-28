import io
import json
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.routers.api import get_provider
from app.schemas.api import ModelAnswer
from tests.test_integration import db  # noqa: F401

pytestmark = pytest.mark.integration


async def test_full_rest_workflow(db, tmp_path):  # noqa: F811
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    async def session_override():
        async with factory() as session:
            yield session

    provider = AsyncMock()
    provider.embed.side_effect = lambda texts, purpose="document": [
        [1.0] + [0.0] * 1023 for _ in texts
    ]

    async def generate(system, user):
        context = json.loads(user)["untrusted_context"]
        return ModelAnswer(
            answer="Records are retained for thirty days.",
            source_ids=[context[0]["id"]],
            insufficient_context=False,
        )

    provider.generate.side_effect = generate
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path)
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/workspaces", json={"name": "REST workflow"})
            assert response.status_code == 201
            workspace_id = response.json()["id"]
            db.info.setdefault("workspaces", []).append(UUID(workspace_id))
            uploaded = await client.post(
                "/documents",
                data={"workspace_id": workspace_id},
                files={
                    "file": (
                        "policy.txt",
                        io.BytesIO(b"Records are retained for thirty days."),
                        "text/plain",
                    )
                },
            )
            assert uploaded.status_code == 201
            document = uploaded.json()
            assert document["status"] == "ready"
            assert "storage_name" not in document
            duplicate = await client.post(
                "/documents",
                data={"workspace_id": workspace_id},
                files={
                    "file": (
                        "copy.txt",
                        io.BytesIO(b"Records are retained for thirty days."),
                        "text/plain",
                    )
                },
            )
            assert duplicate.status_code == 409
            conversation = (
                await client.post(
                    "/conversations",
                    json={
                        "workspace_id": workspace_id,
                        "title": "Retention policy",
                    },
                )
            ).json()
            body = {
                "workspace_id": workspace_id,
                "conversation_id": conversation["id"],
                "question": "How long are records kept?",
            }
            result = await client.post("/chat", json=body)
            assert result.status_code == 200
            assert result.json()["citations"][0]["document_id"] == document["id"]
            history_url = f"/conversations/{conversation['id']}?workspace_id={workspace_id}"
            history = (await client.get(history_url)).json()
            assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
            provider.generate.side_effect = RuntimeError("secret provider failure")
            failure = await client.post("/chat", json=body)
            assert failure.status_code == 503
            assert "secret provider failure" not in failure.text
            assert len((await client.get(history_url)).json()["messages"]) == 2
            response = await client.delete(
                f"/documents/{document['id']}?workspace_id={workspace_id}"
            )
            assert response.status_code == 204
            assert (await client.get(f"/workspaces/{workspace_id}/stats")).json()["chunks"] == 0
            empty = await client.post("/chat", json=body)
            assert empty.status_code == 200
            assert empty.json()["insufficient_context"] is True
            # Historical snapshots are retained until their conversation is deleted.
            assert (await client.delete(history_url)).status_code == 204
            assert (await client.get(history_url)).status_code == 404
    finally:
        app.dependency_overrides.clear()

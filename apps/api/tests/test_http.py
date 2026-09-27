from fastapi.testclient import TestClient

from app.main import app


def test_health_config_and_request_id():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers["x-request-id"]
        assert response.json() == {"status": "ok"}
        assert "openai_api_key" not in client.get("/config").text


def test_validation_does_not_echo_question():
    with TestClient(app) as client:
        response = client.post("/chat", json={"question": "sensitive-test-content"})
        assert response.status_code == 422
        assert "sensitive-test-content" not in response.text


def test_openapi_is_generated():
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
        assert "/documents" in spec["paths"]
        assert "/chat" in spec["paths"]

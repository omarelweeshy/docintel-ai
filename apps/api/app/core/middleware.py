import json
import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "event": record.getMessage(),
                **{
                    k: getattr(record, k)
                    for k in ("request_id", "status", "duration_ms", "document_id")
                    if hasattr(record, k)
                },
            }
        )


class RequestMiddleware:
    """Limit the entire multipart body before Starlette writes an oversized spool."""

    def __init__(self, app: ASGIApp, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.monotonic()
        total = 0
        status = 500
        # Buffer a bounded request before passing it to multipart parsing.
        body: list[Message] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.max_body_bytes:
                payload = json.dumps(
                    {
                        "error": {
                            "code": "request_too_large",
                            "message": "Request exceeds upload limit.",
                            "request_id": request_id,
                        }
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"x-request-id", request_id.encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": payload})
                return
            body.append(message)
            if not message.get("more_body", False):
                break
        position = 0

        async def bounded_receive() -> Message:
            nonlocal position
            if position < len(body):
                message = body[position]
                position += 1
                return message
            return await receive()

        async def wrapped_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
            await send(message)

        try:
            await self.app(scope, bounded_receive, wrapped_send)
        finally:
            logging.getLogger("requests").info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "status": status,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                },
            )

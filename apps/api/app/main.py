import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import AppError
from app.core.middleware import JsonFormatter, RequestMiddleware
from app.providers.factory import create_provider
from app.routers.api import router

settings = get_settings()
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
# Provider HTTP request URLs and bodies do not belong in application logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    provider = create_provider(settings)
    app.state.provider = provider
    yield
    await provider.close()
    await engine.dispose()


app = FastAPI(
    title="DocIntel AI",
    version="0.1.0",
    description="Production-oriented document RAG. Trusted local use; authentication deferred.",
    lifespan=lifespan,
)
app.add_middleware(RequestMiddleware, max_body_bytes=settings.max_upload_bytes + 1024 * 1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
    )


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo Pydantic's input field: it can contain document or question text.
    return error_response(request, "invalid_request", "Request fields are invalid.", 422)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logging.getLogger(__name__).error("database_error", exc_info=exc)
    return error_response(
        request, "database_unavailable", "Database operation failed. Try again.", 503
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).error("unexpected_error", exc_info=exc)
    return error_response(request, "internal_error", "An unexpected error occurred.", 500)


app.include_router(router)

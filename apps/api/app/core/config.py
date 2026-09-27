from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://docintel:docintel@localhost:5432/docintel"
    storage_dir: Path = Path("storage")
    openai_api_key: SecretStr = SecretStr("")
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    # A schema migration and full reindex are required to change dimensionality.
    embedding_dimensions: int = Field(default=1536, ge=1536, le=1536)
    cors_origins: list[str] = ["http://localhost:3000"]
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_document_chars: int = Field(default=2_000_000, gt=0)
    max_pages: int = Field(default=500, gt=0)
    chunk_words: int = Field(default=350, ge=20, le=1000)
    chunk_overlap: int = Field(default=50, ge=0)
    max_chunk_chars: int = Field(default=6000, ge=100, le=8000)
    max_chunks: int = Field(default=2000, ge=1)
    top_k: int = Field(default=6, ge=1, le=20)
    min_similarity: float = Field(default=0.25, ge=-1, le=1)
    max_question_chars: int = Field(default=2000, ge=1, le=10000)
    max_context_chars: int = Field(default=24000, ge=1000, le=100000)
    provider_timeout_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_words:
            raise ValueError("chunk_overlap must be less than chunk_words")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

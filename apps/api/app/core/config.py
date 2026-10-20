from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://docintel:docintel@localhost:5432/docintel"
    storage_dir: Path = Path("storage")
    ai_provider: Literal["ollama", "openai"] = "ollama"
    openai_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "qwen3.5:4b"
    embedding_model: str = "qwen3-embedding:0.6b"
    # A schema migration and full reindex are required to change dimensionality.
    embedding_dimensions: int = Field(default=1024, ge=256, le=4096)
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=32768)
    cors_origins: list[str] = ["http://localhost:3000"]
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_document_chars: int = Field(default=2_000_000, gt=0)
    max_pages: int = Field(default=500, gt=0)
    chunk_words: int = Field(default=350, ge=20, le=1000)
    chunk_overlap: int = Field(default=50, ge=0)
    max_chunk_chars: int = Field(default=6000, ge=100, le=8000)
    # "words": fixed word windows per page (original). "structure": headings, table rows and
    # paragraphs with heading-path prefixes (app/ingest). Changing it requires a reindex.
    # "words_tables": word windows plus one extra chunk group per detected table.
    chunking: Literal["words", "structure", "words_tables"] = "words"
    chunk_target_words: int = Field(default=260, ge=20, le=1000)
    # "inline": parse and embed during the upload request (original). "queue": the upload returns
    # 202 and a worker process (python -m app.worker) ingests from the durable job table.
    ingestion_mode: Literal["inline", "queue"] = "inline"
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_lease_seconds: float = Field(default=120, ge=10, le=3600)
    worker_poll_seconds: float = Field(default=2, gt=0, le=60)
    max_chunks: int = Field(default=2000, ge=1)
    top_k: int = Field(default=6, ge=1, le=20)
    # "hybrid" (default) fuses vector and keyword search by RRF; "vector" is the original
    # behaviour. Hybrid improved test-split recall@5 and answer correctness (docs/EVAL_RESULTS.md).
    retrieval_mode: Literal["vector", "hybrid"] = "hybrid"
    rrf_k: int = Field(default=60, ge=1, le=1000)
    candidate_pool: int = Field(default=30, ge=1, le=200)
    # Extra keyword list for identifier-like tokens ("800-61r3", "HC-412"). Off: it did not help
    # on the dev split (docs/EVAL_RESULTS.md, row 1 tuning).
    identifier_search: bool = False
    # Retrievers return this many ranked chunks; the generator sees the first top_k. A deeper list
    # lets multi-query fusion and evaluation work on the same ranking the API uses.
    retrieval_depth: int = Field(default=20, ge=1, le=100)
    # Rewrite follow-up questions into standalone ones using recent history (one extra model call,
    # only when there is history). On the test split it fixed 3 of 13 follow-up turns.
    query_planning: bool = True
    # Also split multi-part first-turn questions into sub-queries. Off: in the measured run it
    # triggered once and turned a correct answer into an abstention.
    query_decomposition: bool = False
    # "answer": one answer with chunk-level citations (original). "sentences": each sentence cites
    # passages, is aligned to a span and is checked for lexical support.
    answer_format: Literal["answer", "sentences"] = "answer"
    history_messages: int = Field(default=6, ge=0, le=20)
    max_question_chars: int = Field(default=2000, ge=1, le=10000)
    max_context_chars: int = Field(default=24000, ge=1000, le=100000)
    # Cold-loading the local generation model can exceed one minute on laptop GPUs.
    provider_timeout_seconds: float = Field(default=180, gt=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_words:
            raise ValueError("chunk_overlap must be less than chunk_words")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
